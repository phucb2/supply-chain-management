#!/bin/sh
set -eu

CONNECT_URL="${KAFKA_CONNECT_URL:-http://debezium-connect:8083}"
POSTGRES_DB="${POSTGRES_DB:-supplychain}"
DEBEZIUM_DB_PASSWORD="${DEBEZIUM_DB_PASSWORD:-debezium_secret}"

echo "Waiting for Kafka Connect at ${CONNECT_URL}..."
i=0
while [ "$i" -lt 90 ]; do
  if curl -sf "${CONNECT_URL}/" >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 2
done
if ! curl -sf "${CONNECT_URL}/" >/dev/null 2>&1; then
  echo "Connect did not become ready in time." >&2
  exit 1
fi

CONNECTOR_NAME="supplychain-postgres-cdc"
if curl -sf "${CONNECT_URL}/connectors/${CONNECTOR_NAME}" >/dev/null 2>&1; then
  echo "Connector ${CONNECTOR_NAME} already registered."
  exit 0
fi

echo "Registering ${CONNECTOR_NAME}..."

# shellcheck disable=SC2016
BODY=$(printf '%s' "{
  \"name\": \"${CONNECTOR_NAME}\",
  \"config\": {
    \"connector.class\": \"io.debezium.connector.postgresql.PostgresConnector\",
    \"tasks.max\": \"1\",
    \"database.hostname\": \"postgresql\",
    \"database.port\": \"5432\",
    \"database.user\": \"debezium\",
    \"database.password\": \"${DEBEZIUM_DB_PASSWORD}\",
    \"database.dbname\": \"${POSTGRES_DB}\",
    \"topic.prefix\": \"supplychain.cdc\",
    \"plugin.name\": \"pgoutput\",
    \"publication.autocreate.mode\": \"disabled\",
    \"publication.name\": \"dbz_publication\",
    \"table.include.list\": \"public.orders,public.order_items,public.order_events,public.shipments,public.shipment_packages,public.inventory_reservations,public.outbox_events,public.drivers,public.webhook_subscriptions,public.predictions,public.prediction_actuals\",
    \"slot.name\": \"debezium_supplychain\",
    \"schema.history.internal.kafka.bootstrap.servers\": \"kafka:29092\",
    \"schema.history.internal.kafka.topic\": \"schemahistory.supplychain\",
    \"topic.creation.default.replication.factor\": \"1\",
    \"topic.creation.default.partitions\": \"4\"
  }
}")

curl -sf -X POST -H "Content-Type: application/json" \
  --data-binary "$BODY" \
  "${CONNECT_URL}/connectors"

echo ""
echo "Connector registered."
