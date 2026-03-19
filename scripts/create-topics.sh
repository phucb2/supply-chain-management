#!/bin/bash
set -e

BROKER="kafka:29092"

echo "Waiting for Kafka to be ready..."
cub kafka-ready -b "$BROKER" 1 60

TOPICS=(
  "order.received"
  "order.validated"
  "order.erp.create"
  "order.erp.created"
  "order.allocated"
  "order.cancelled"
  "order.exception"
  "shipment.requested"
  "shipment.created"
  "shipment.status-updated"
  "eta.predicted"
  "dlq.order.received"
  "dlq.order.validated"
  "dlq.shipment.status-updated"
)

for TOPIC in "${TOPICS[@]}"; do
  echo "Creating topic: $TOPIC"
  kafka-topics --bootstrap-server "$BROKER" \
    --create --if-not-exists \
    --topic "$TOPIC" \
    --partitions 4 \
    --replication-factor 1
done

echo "All topics created."
