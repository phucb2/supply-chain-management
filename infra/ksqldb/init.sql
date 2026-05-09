-- ksqlDB streams and tables for supply-chain order querying.
-- Applied once by scripts/init-ksqldb.sh at stack startup.

-- ============================================================================
-- STREAMS  (one per Kafka topic, mirrors the JSON payload)
-- ============================================================================

CREATE STREAM IF NOT EXISTS order_received (
    order_id        VARCHAR KEY,
    external_order_id VARCHAR,
    channel         VARCHAR,
    customer_name   VARCHAR,
    shipping_address VARCHAR,
    items           ARRAY<STRUCT<
                        sku          VARCHAR,
                        product_name VARCHAR,
                        quantity     INTEGER,
                        unit_price   DOUBLE
                    >>
) WITH (
    KAFKA_TOPIC  = 'order.received',
    VALUE_FORMAT = 'JSON'
);

CREATE STREAM IF NOT EXISTS order_validated (
    order_id          VARCHAR KEY,
    external_order_id VARCHAR
) WITH (
    KAFKA_TOPIC  = 'order.validated',
    VALUE_FORMAT = 'JSON'
);

CREATE STREAM IF NOT EXISTS order_erp_created (
    order_id     VARCHAR KEY,
    erp_order_id VARCHAR
) WITH (
    KAFKA_TOPIC  = 'order.erp.created',
    VALUE_FORMAT = 'JSON'
);

CREATE STREAM IF NOT EXISTS order_allocated (
    order_id     VARCHAR KEY,
    reservations ARRAY<STRUCT<
                     sku      VARCHAR,
                     quantity INTEGER,
                     id       VARCHAR
                 >>
) WITH (
    KAFKA_TOPIC  = 'order.allocated',
    VALUE_FORMAT = 'JSON'
);

CREATE STREAM IF NOT EXISTS order_exception (
    order_id       VARCHAR KEY,
    reason         VARCHAR,
    original_event VARCHAR
) WITH (
    KAFKA_TOPIC  = 'order.exception',
    VALUE_FORMAT = 'JSON'
);

CREATE STREAM IF NOT EXISTS order_cancelled (
    order_id VARCHAR KEY,
    status   VARCHAR
) WITH (
    KAFKA_TOPIC  = 'order.cancelled',
    VALUE_FORMAT = 'JSON'
);

CREATE STREAM IF NOT EXISTS shipment_created (
    order_id        VARCHAR KEY,
    delivery_order_id VARCHAR,
    carrier         VARCHAR,
    tracking_number VARCHAR
) WITH (
    KAFKA_TOPIC  = 'shipment.created',
    VALUE_FORMAT = 'JSON'
);

CREATE STREAM IF NOT EXISTS shipment_status_updated (
    delivery_order_id VARCHAR KEY,
    order_id    VARCHAR,
    status      VARCHAR,
    location    VARCHAR,
    `timestamp` VARCHAR
) WITH (
    KAFKA_TOPIC  = 'shipment.status-updated',
    VALUE_FORMAT = 'JSON'
);

-- ============================================================================
-- TABLES  (materialized aggregations, continuously updated)
-- ============================================================================

-- Live count of orders per channel
CREATE TABLE IF NOT EXISTS orders_by_channel AS
    SELECT channel,
           COUNT(*) AS order_count
    FROM   order_received
    GROUP BY channel
    EMIT CHANGES;

-- Live count of shipments per carrier
CREATE TABLE IF NOT EXISTS shipments_by_carrier AS
    SELECT carrier,
           COUNT(*) AS shipment_count
    FROM   shipment_created
    GROUP BY carrier
    EMIT CHANGES;

-- Live count of exceptions by reason
CREATE TABLE IF NOT EXISTS exceptions_by_reason AS
    SELECT reason,
           COUNT(*) AS exception_count
    FROM   order_exception
    GROUP BY reason
    EMIT CHANGES;
