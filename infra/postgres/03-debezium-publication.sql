-- Logical-replication publication for Debezium (tables owned by POSTGRES_USER).
CREATE PUBLICATION dbz_publication FOR TABLE
  public.orders,
  public.order_items,
  public.order_events,
  public.shipments,
  public.shipment_packages,
  public.inventory_reservations,
  public.outbox_events,
  public.drivers,
  public.webhook_subscriptions,
  public.predictions,
  public.prediction_actuals;

ALTER PUBLICATION dbz_publication OWNER TO debezium;
