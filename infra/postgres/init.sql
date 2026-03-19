-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enum types
CREATE TYPE order_status AS ENUM (
    'received', 'validated', 'erp_synced', 'allocated',
    'shipped', 'delivered', 'cancelled', 'exception'
);

CREATE TYPE shipment_status AS ENUM (
    'requested', 'created', 'picked_up', 'in_transit',
    'out_for_delivery', 'delivered', 'exception'
);

CREATE TYPE reservation_status AS ENUM ('reserved', 'committed', 'released');

-- Orders
CREATE TABLE orders (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_order_id TEXT NOT NULL UNIQUE,
    channel         TEXT NOT NULL,
    status          order_status NOT NULL DEFAULT 'received',
    customer_name   TEXT NOT NULL,
    customer_email  TEXT,
    shipping_address TEXT NOT NULL,
    raw_payload     JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

-- Order items
CREATE TABLE order_items (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id    UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    sku         TEXT NOT NULL,
    product_name TEXT NOT NULL,
    quantity    INTEGER NOT NULL,
    unit_price  DOUBLE PRECISION NOT NULL
);

-- Order events (audit trail)
CREATE TABLE order_events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id    UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    payload     JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_order_events_created_at ON order_events (created_at);

-- Shipments
CREATE TABLE shipments (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id        UUID NOT NULL REFERENCES orders(id),
    carrier         TEXT,
    tracking_number TEXT,
    status          shipment_status NOT NULL DEFAULT 'requested',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at    TIMESTAMPTZ
);

-- Shipment packages
CREATE TABLE shipment_packages (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    shipment_id UUID NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    weight      DOUBLE PRECISION,
    dimensions  TEXT,
    label_url   TEXT
);

-- Inventory reservations
CREATE TABLE inventory_reservations (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id    UUID NOT NULL REFERENCES orders(id),
    sku         TEXT NOT NULL,
    quantity    INTEGER NOT NULL,
    status      reservation_status NOT NULL DEFAULT 'reserved',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Outbox (transactional outbox pattern)
CREATE TABLE outbox_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    aggregate_type  TEXT NOT NULL,
    aggregate_id    UUID NOT NULL,
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    published_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_outbox_unpublished ON outbox_events (created_at) WHERE published_at IS NULL;

-- Drivers
CREATE TABLE drivers (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    phone           TEXT,
    vendor          TEXT,
    vehicle_plate   TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

-- Webhook subscriptions
CREATE TABLE webhook_subscriptions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    url         TEXT NOT NULL,
    events      JSONB NOT NULL,
    secret      TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ML: ETA predictions
CREATE TABLE predictions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    shipment_id         UUID NOT NULL REFERENCES shipments(id),
    predicted_eta_hours DOUBLE PRECISION NOT NULL,
    model_version       TEXT NOT NULL,
    input_features      JSONB,
    predicted_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ML: prediction vs actual comparison (feedback loop)
CREATE TABLE prediction_actuals (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    shipment_id         UUID NOT NULL REFERENCES shipments(id),
    prediction_id       UUID NOT NULL REFERENCES predictions(id),
    actual_eta_hours    DOUBLE PRECISION NOT NULL,
    absolute_error      DOUBLE PRECISION NOT NULL,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
