-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Analytics star schema lives in dw; OLTP tables remain in public.
CREATE SCHEMA IF NOT EXISTS dw;

-- Domain enums
CREATE TYPE customer_type AS ENUM ('b2b', 'b2c');
CREATE TYPE shipment_request_type AS ENUM ('b2b', 'b2c');
CREATE TYPE order_status AS ENUM (
    'pending', 'confirmed', 'allocated', 'packed',
    'in_transit', 'delivered', 'cancelled', 'exception'
);
CREATE TYPE delivery_status AS ENUM (
    'planned', 'assigned', 'in_transit', 'delivered', 'failed'
);

-- Master tables
CREATE TABLE customers (
    customer_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_category    customer_type NOT NULL,
    email                TEXT,
    phone                TEXT,
    address              TEXT,
    ward                 TEXT,
    city_province        TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE companies (
    customer_id          UUID PRIMARY KEY REFERENCES customers(customer_id) ON DELETE CASCADE,
    company_name         TEXT NOT NULL,
    tax_id               TEXT NOT NULL UNIQUE
);

CREATE TABLE individuals (
    customer_id          UUID PRIMARY KEY REFERENCES customers(customer_id) ON DELETE CASCADE,
    full_name            TEXT NOT NULL,
    ssi                  TEXT NOT NULL UNIQUE
);

CREATE TABLE products (
    product_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sku                  TEXT NOT NULL UNIQUE,
    product_name         TEXT NOT NULL,
    category             TEXT,
    weight_per_unit_kg   DOUBLE PRECISION NOT NULL CHECK (weight_per_unit_kg > 0),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE warehouses (
    warehouse_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    warehouse_name       TEXT NOT NULL,
    location             TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE vendors (
    vendor_id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vendor_name          TEXT NOT NULL,
    phone                TEXT,
    tax_no               TEXT NOT NULL UNIQUE,
    address              TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE vehicles (
    vehicle_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vendor_id            UUID NOT NULL REFERENCES vendors(vendor_id),
    plate_number         TEXT NOT NULL UNIQUE,
    vehicle_type         TEXT NOT NULL,
    capacity_quantity    INTEGER NOT NULL CHECK (capacity_quantity > 0),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE drivers (
    driver_id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name            TEXT NOT NULL,
    license_number       TEXT NOT NULL UNIQUE,
    phone                TEXT,
    vendor_id            UUID REFERENCES vendors(vendor_id),
    active               INTEGER NOT NULL DEFAULT 1,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at           TIMESTAMPTZ
);

-- Transaction tables
CREATE TABLE shipment_requests (
    request_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_type         shipment_request_type NOT NULL,
    request_date         DATE NOT NULL,
    origin               TEXT NOT NULL,
    destination          TEXT NOT NULL,
    planned_date         DATE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE b2b_requests (
    request_id           UUID PRIMARY KEY REFERENCES shipment_requests(request_id) ON DELETE CASCADE,
    driver_id            UUID NOT NULL REFERENCES drivers(driver_id),
    loading_dock         TEXT,
    dispatch_time        TIMESTAMPTZ
);

CREATE TABLE b2c_requests (
    request_id           UUID PRIMARY KEY REFERENCES shipment_requests(request_id) ON DELETE CASCADE,
    vehicle_id           UUID NOT NULL REFERENCES vehicles(vehicle_id),
    recipient_name       TEXT NOT NULL,
    contact_number       TEXT,
    scheduled_time       TIMESTAMPTZ
);

CREATE TABLE check_in_records (
    check_in_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id           UUID UNIQUE NOT NULL REFERENCES b2c_requests(request_id) ON DELETE CASCADE,
    gate                 TEXT,
    check_in_time        TIMESTAMPTZ NOT NULL,
    delay_minutes        INTEGER NOT NULL DEFAULT 0 CHECK (delay_minutes >= 0),
    notes                TEXT
);

CREATE TABLE delivery_orders (
    delivery_order_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    warehouse_id         UUID NOT NULL REFERENCES warehouses(warehouse_id),
    request_id           UUID UNIQUE NOT NULL REFERENCES shipment_requests(request_id),
    delivery_date        DATE,
    status               delivery_status NOT NULL DEFAULT 'planned',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sale_orders (
    sale_order_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_order_id    TEXT NOT NULL UNIQUE,
    customer_id          UUID NOT NULL REFERENCES customers(customer_id),
    delivery_order_id    UUID NOT NULL REFERENCES delivery_orders(delivery_order_id),
    source               TEXT NOT NULL,
    order_date           DATE NOT NULL,
    req_delivery_date    DATE NOT NULL,
    status               order_status NOT NULL DEFAULT 'pending',
    total_amount         DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (order_date <= req_delivery_date)
);

CREATE TABLE order_items (
    sale_order_id        UUID NOT NULL REFERENCES sale_orders(sale_order_id) ON DELETE CASCADE,
    product_id           UUID NOT NULL REFERENCES products(product_id),
    quantity             INTEGER NOT NULL CHECK (quantity > 0),
    unit_price           DOUBLE PRECISION NOT NULL CHECK (unit_price >= 0),
    weight_per_unit_kg   DOUBLE PRECISION NOT NULL CHECK (weight_per_unit_kg > 0),
    total_kg             DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (sale_order_id, product_id)
);

CREATE TABLE sale_order_status (
    status_id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sale_order_id        UUID NOT NULL REFERENCES sale_orders(sale_order_id) ON DELETE CASCADE,
    status               order_status NOT NULL,
    status_timestamp     TIMESTAMPTZ NOT NULL DEFAULT now(),
    remarks              TEXT
);

CREATE INDEX ix_sale_order_status_order_time ON sale_order_status (sale_order_id, status_timestamp);

-- ML + outbox tables maintained in cutover schema
CREATE TABLE predictions (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sale_order_id        UUID NOT NULL REFERENCES sale_orders(sale_order_id),
    delivery_order_id    UUID NOT NULL REFERENCES delivery_orders(delivery_order_id),
    predicted_eta_hours  DOUBLE PRECISION NOT NULL,
    model_version        TEXT NOT NULL,
    input_features       JSONB,
    predicted_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE prediction_actuals (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sale_order_id        UUID NOT NULL REFERENCES sale_orders(sale_order_id),
    prediction_id        UUID NOT NULL REFERENCES predictions(id),
    actual_eta_hours     DOUBLE PRECISION NOT NULL,
    absolute_error       DOUBLE PRECISION NOT NULL,
    recorded_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE webhook_subscriptions (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    url                  TEXT NOT NULL,
    events               JSONB NOT NULL,
    secret               TEXT,
    active               INTEGER NOT NULL DEFAULT 1,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE outbox_events (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    aggregate_type       TEXT NOT NULL,
    aggregate_id         UUID NOT NULL,
    event_type           TEXT NOT NULL,
    payload              JSONB NOT NULL,
    published_at         TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_outbox_unpublished ON outbox_events (created_at) WHERE published_at IS NULL;

-- Data warehouse star schema (schema dw; live OLTP is public)
CREATE TABLE dw.dim_date (
    date_key             INTEGER PRIMARY KEY,
    full_date            DATE NOT NULL UNIQUE,
    month                INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    year                 INTEGER NOT NULL,
    year_month           TEXT NOT NULL
);

CREATE TABLE dw.dim_sales_order (
    order_key            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sale_order_id        UUID NOT NULL UNIQUE REFERENCES public.sale_orders(sale_order_id),
    current_status       order_status NOT NULL
);

CREATE TABLE dw.fact_delivery_quality (
    order_key                 UUID PRIMARY KEY REFERENCES dw.dim_sales_order(order_key),
    order_date_key            INTEGER NOT NULL REFERENCES dw.dim_date(date_key),
    planned_delivery_date_key INTEGER NOT NULL REFERENCES dw.dim_date(date_key),
    actual_delivery_date_key  INTEGER REFERENCES dw.dim_date(date_key),
    delay_days                INTEGER,
    is_not_yet_delivered      INTEGER NOT NULL CHECK (is_not_yet_delivered IN (0, 1)),
    is_on_time                INTEGER NOT NULL CHECK (is_on_time IN (0, 1)),
    is_late_under_1_week      INTEGER NOT NULL CHECK (is_late_under_1_week IN (0, 1)),
    is_late_under_2_weeks     INTEGER NOT NULL CHECK (is_late_under_2_weeks IN (0, 1)),
    is_late_over_2_weeks      INTEGER NOT NULL CHECK (is_late_over_2_weeks IN (0, 1))
);

-- Specialization constraints (total + disjoint)
CREATE OR REPLACE FUNCTION enforce_customer_specialization() RETURNS TRIGGER AS $$
DECLARE
    company_count INTEGER;
    individual_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO company_count FROM companies WHERE customer_id = NEW.customer_id;
    SELECT COUNT(*) INTO individual_count FROM individuals WHERE customer_id = NEW.customer_id;
    IF company_count + individual_count <> 1 THEN
        RAISE EXCEPTION 'customer % must appear in exactly one subtype table', NEW.customer_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_customer_specialization
AFTER INSERT OR UPDATE ON customers
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_customer_specialization();

CREATE OR REPLACE FUNCTION enforce_request_specialization() RETURNS TRIGGER AS $$
DECLARE
    b2b_count INTEGER;
    b2c_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO b2b_count FROM b2b_requests WHERE request_id = NEW.request_id;
    SELECT COUNT(*) INTO b2c_count FROM b2c_requests WHERE request_id = NEW.request_id;
    IF b2b_count + b2c_count <> 1 THEN
        RAISE EXCEPTION 'shipment_request % must appear in exactly one subtype table', NEW.request_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_request_specialization
AFTER INSERT OR UPDATE ON shipment_requests
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_request_specialization();
