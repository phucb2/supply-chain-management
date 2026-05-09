-- One-time direct cutover migration for redesigned schema.
-- Use this when upgrading an existing initialized database.

-- BEGIN;

-- DROP TABLE IF EXISTS prediction_actuals CASCADE;
-- DROP TABLE IF EXISTS predictions CASCADE;
-- DROP TABLE IF EXISTS shipment_packages CASCADE;
-- DROP TABLE IF EXISTS shipments CASCADE;
-- DROP TABLE IF EXISTS inventory_reservations CASCADE;
-- DROP TABLE IF EXISTS order_events CASCADE;
-- DROP TABLE IF EXISTS order_items CASCADE;
-- DROP TABLE IF EXISTS orders CASCADE;
-- DROP TABLE IF EXISTS outbox_events CASCADE;
-- DROP TABLE IF EXISTS webhook_subscriptions CASCADE;
-- DROP TABLE IF EXISTS drivers CASCADE;

-- DROP TYPE IF EXISTS reservation_status CASCADE;
-- DROP TYPE IF EXISTS shipment_status CASCADE;
-- DROP TYPE IF EXISTS order_status CASCADE;

-- COMMIT;
