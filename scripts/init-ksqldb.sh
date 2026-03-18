#!/bin/bash
set -e

KSQLDB_URL="http://ksqldb-server:8088"

echo "Waiting for ksqlDB server to be ready..."
until curl -sf "$KSQLDB_URL/info" > /dev/null 2>&1; do
  sleep 2
done

echo "Applying ksqlDB init statements..."
ksql "$KSQLDB_URL" -f /tmp/init.sql

echo "ksqlDB streams and tables created."
