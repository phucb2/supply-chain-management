-- Logical-replication publication for Debezium (tables owned by POSTGRES_USER).
CREATE PUBLICATION dbz_publication FOR TABLE
  public.customers,
  public.companies,
  public.individuals,
  public.products,
  public.warehouses,
  public.vendors,
  public.vehicles,
  public.drivers,
  public.shipment_requests,
  public.b2b_requests,
  public.b2c_requests,
  public.check_in_records,
  public.delivery_orders,
  public.sale_orders,
  public.order_items,
  public.sale_order_status,
  public.outbox_events,
  public.webhook_subscriptions,
  public.predictions,
  public.prediction_actuals;

ALTER PUBLICATION dbz_publication OWNER TO debezium;
