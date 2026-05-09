"""Repository layer for redesigned sale-order and delivery-request schema."""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    B2BRequest,
    B2CRequest,
    CheckInRecord,
    Company,
    Customer,
    DeliveryOrder,
    Driver,
    Individual,
    OrderItem,
    Product,
    SaleOrder,
    SaleOrderStatus,
    ShipmentRequest,
    WebhookSubscription,
)


async def create_order(
    session: AsyncSession,
    *,
    external_order_id: str,
    source: str,
    customer_category: str,
    customer_name: str,
    customer_email: str | None,
    shipping_address: str,
    req_delivery_date: date,
    request_type: str,
    origin: str,
    destination: str,
    items: list[dict],
) -> tuple[SaleOrder, bool]:
    existing = await session.execute(select(SaleOrder).where(SaleOrder.external_order_id == external_order_id))
    row = existing.scalar_one_or_none()
    if row:
        return row, False

    customer = Customer(
        customer_category=customer_category,
        email=customer_email,
        address=shipping_address,
        city_province=destination,
    )
    session.add(customer)
    await session.flush()
    if customer_category == "b2b":
        session.add(
            Company(
                customer_id=customer.customer_id,
                company_name=customer_name,
                tax_id=f"AUTO-TAX-{customer.customer_id.hex[:12]}",
            )
        )
    else:
        session.add(
            Individual(
                customer_id=customer.customer_id,
                full_name=customer_name,
                ssi=f"AUTO-SSI-{customer.customer_id.hex[:12]}",
            )
        )

    request = ShipmentRequest(
        request_type=request_type,
        request_date=date.today(),
        origin=origin,
        destination=destination,
        planned_date=req_delivery_date,
    )
    session.add(request)
    await session.flush()

    if request_type == "b2b":
        b2b = B2BRequest(request_id=request.request_id, driver_id=(await _pick_driver_id(session)))
        session.add(b2b)
    else:
        # Minimal B2C row to satisfy specialization; vehicle assignment can be updated later.
        vehicle_id = await _pick_default_vehicle_id(session)
        b2c = B2CRequest(
            request_id=request.request_id,
            vehicle_id=vehicle_id,
            recipient_name=customer_name,
            contact_number=customer_email,
        )
        session.add(b2c)

    delivery = DeliveryOrder(request_id=request.request_id, warehouse_id=await _pick_default_warehouse_id(session), status="planned")
    session.add(delivery)
    await session.flush()

    order = SaleOrder(
        external_order_id=external_order_id,
        source=source,
        customer_id=customer.customer_id,
        delivery_order_id=delivery.delivery_order_id,
        order_date=date.today(),
        req_delivery_date=req_delivery_date,
        status="pending",
        total_amount=sum(item["quantity"] * item["unit_price"] for item in items),
    )
    session.add(order)
    await session.flush()

    for item in items:
        product = await _upsert_product(
            session,
            sku=item["sku"],
            product_name=item["product_name"],
            weight_per_unit_kg=item["weight_per_unit_kg"],
        )
        session.add(
            OrderItem(
                sale_order_id=order.sale_order_id,
                product_id=product.product_id,
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                weight_per_unit_kg=item["weight_per_unit_kg"],
                total_kg=item["quantity"] * item["weight_per_unit_kg"],
            )
        )

    session.add(SaleOrderStatus(sale_order_id=order.sale_order_id, status="pending", remarks="order.created"))
    await session.flush()
    return order, True


async def get_order(session: AsyncSession, order_id: uuid.UUID) -> SaleOrder | None:
    result = await session.execute(
        select(SaleOrder).options(selectinload(SaleOrder.items), selectinload(SaleOrder.statuses)).where(SaleOrder.sale_order_id == order_id)
    )
    return result.scalar_one_or_none()


async def list_orders(
    session: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    status_filter: str | None = None,
    channel_filter: str | None = None,
) -> list[SaleOrder]:
    stmt = select(SaleOrder).offset(skip).limit(limit).order_by(SaleOrder.created_at.desc())
    if status_filter:
        stmt = stmt.where(SaleOrder.status == status_filter)
    if channel_filter:
        stmt = stmt.where(SaleOrder.source == channel_filter)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_order_status(session: AsyncSession, order_id: uuid.UUID, new_status: str) -> SaleOrder | None:
    await session.execute(
        update(SaleOrder).where(SaleOrder.sale_order_id == order_id).values(status=new_status, updated_at=datetime.now(timezone.utc))
    )
    session.add(SaleOrderStatus(sale_order_id=order_id, status=new_status, remarks=f"order.{new_status}"))
    await session.flush()
    return await get_order(session, order_id)


async def create_order_event(session: AsyncSession, order_id: uuid.UUID, event_type: str, payload: dict | None = None) -> SaleOrderStatus:
    status_map = {
        "order.received": "pending",
        "order.validated": "confirmed",
        "order.allocated": "allocated",
        "order.shipped": "in_transit",
        "order.delivered": "delivered",
        "order.cancelled": "cancelled",
        "order.exception": "exception",
    }
    status = status_map.get(event_type, "pending")
    row = SaleOrderStatus(sale_order_id=order_id, status=status, remarks=event_type if payload is None else f"{event_type}:{payload}")
    session.add(row)
    await session.flush()
    return row


async def get_shipment(session: AsyncSession, shipment_id: uuid.UUID) -> DeliveryOrder | None:
    result = await session.execute(select(DeliveryOrder).where(DeliveryOrder.delivery_order_id == shipment_id))
    return result.scalar_one_or_none()


async def get_sale_order_id_for_delivery(session: AsyncSession, delivery_order_id: uuid.UUID) -> uuid.UUID | None:
    result = await session.execute(
        select(SaleOrder.sale_order_id).where(SaleOrder.delivery_order_id == delivery_order_id).limit(1)
    )
    return result.scalar_one_or_none()


async def update_shipment_status(session: AsyncSession, shipment_id: uuid.UUID, new_status: str) -> DeliveryOrder | None:
    mapped = {
        "picked_up": "in_transit",
        "in_transit": "in_transit",
        "out_for_delivery": "in_transit",
        "delivered": "delivered",
        "exception": "failed",
    }
    await session.execute(
        update(DeliveryOrder)
        .where(DeliveryOrder.delivery_order_id == shipment_id)
        .values(status=mapped.get(new_status, "in_transit"), delivery_date=date.today() if new_status == "delivered" else None)
    )
    await session.flush()
    return await get_shipment(session, shipment_id)


async def get_shipment_tracking_events(session: AsyncSession, shipment_id: uuid.UUID) -> list[SaleOrderStatus]:
    result = await session.execute(
        select(SaleOrderStatus)
        .join(SaleOrder, SaleOrder.sale_order_id == SaleOrderStatus.sale_order_id)
        .where(SaleOrder.delivery_order_id == shipment_id)
        .order_by(SaleOrderStatus.status_timestamp)
    )
    return list(result.scalars().all())


async def create_driver(session: AsyncSession, *, full_name: str, license_number: str, phone: str | None, vendor_id: uuid.UUID | None) -> Driver:
    driver = Driver(full_name=full_name, license_number=license_number, phone=phone, vendor_id=vendor_id)
    session.add(driver)
    await session.flush()
    return driver


async def soft_delete_driver(session: AsyncSession, driver_id: uuid.UUID) -> Driver | None:
    result = await session.execute(select(Driver).where(Driver.driver_id == driver_id))
    driver = result.scalar_one_or_none()
    if driver:
        driver.deleted_at = datetime.now(timezone.utc)
        driver.active = 0
        await session.flush()
    return driver


async def create_b2c_check_in(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    gate: str | None,
    delay_minutes: int,
    notes: str | None,
) -> CheckInRecord:
    checkin = CheckInRecord(
        request_id=request_id,
        gate=gate,
        check_in_time=datetime.now(timezone.utc),
        delay_minutes=delay_minutes,
        notes=notes,
    )
    session.add(checkin)
    await session.flush()
    return checkin


async def create_webhook_subscription(session: AsyncSession, *, url: str, events: list[str], secret: str | None = None) -> WebhookSubscription:
    sub = WebhookSubscription(url=url, events=events, secret=secret)
    session.add(sub)
    await session.flush()
    return sub


async def list_webhook_subscriptions(session: AsyncSession) -> list[WebhookSubscription]:
    result = await session.execute(select(WebhookSubscription).where(WebhookSubscription.active == 1))
    return list(result.scalars().all())


async def get_webhook_subscriptions_for_event(session: AsyncSession, event_type: str) -> list[WebhookSubscription]:
    all_subs = await list_webhook_subscriptions(session)
    return [s for s in all_subs if event_type in s.events]


async def _pick_default_warehouse_id(session: AsyncSession) -> uuid.UUID:
    from app.db.models import Warehouse
    row = await session.execute(select(Warehouse.warehouse_id).limit(1))
    found = row.scalar_one_or_none()
    if found:
        return found
    # Fallback explicit insert so local setup can bootstrap.
    from app.db.models import Warehouse as WarehouseModel
    warehouse = WarehouseModel(warehouse_name="Default Warehouse", location="HCM")
    session.add(warehouse)
    await session.flush()
    return warehouse.warehouse_id


async def _pick_default_vehicle_id(session: AsyncSession) -> uuid.UUID:
    from app.db.models import Vehicle, Vendor
    row = await session.execute(select(Vehicle.vehicle_id).limit(1))
    found = row.scalar_one_or_none()
    if found:
        return found
    vendor = Vendor(vendor_name="Default Vendor", phone="n/a", tax_no=f"TAX-{uuid.uuid4().hex[:10]}", address="n/a")
    session.add(vendor)
    await session.flush()
    vehicle = Vehicle(vendor_id=vendor.vendor_id, plate_number=f"PLATE-{uuid.uuid4().hex[:6]}", vehicle_type="van", capacity_quantity=100)
    session.add(vehicle)
    await session.flush()
    return vehicle.vehicle_id


async def _pick_driver_id(session: AsyncSession) -> uuid.UUID:
    row = await session.execute(select(Driver.driver_id).where(Driver.active == 1).limit(1))
    found = row.scalar_one_or_none()
    if found:
        return found
    driver = Driver(full_name="Default Driver", license_number=f"LIC-{uuid.uuid4().hex[:8]}", phone=None, vendor_id=None)
    session.add(driver)
    await session.flush()
    return driver.driver_id


async def _upsert_product(session: AsyncSession, *, sku: str, product_name: str, weight_per_unit_kg: float) -> Product:
    stmt = (
        pg_insert(Product)
        .values(sku=sku, product_name=product_name, weight_per_unit_kg=weight_per_unit_kg)
        .on_conflict_do_update(
            index_elements=["sku"],
            set_={"product_name": product_name, "weight_per_unit_kg": weight_per_unit_kg},
        )
        .returning(Product.product_id)
    )
    row = (await session.execute(stmt)).scalar_one()
    result = await session.execute(select(Product).where(Product.product_id == row))
    return result.scalar_one()
