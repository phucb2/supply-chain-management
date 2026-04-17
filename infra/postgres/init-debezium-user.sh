#!/bin/bash
set -euo pipefail
# Creates Debezium CDC user on first DB init only (docker-entrypoint-initdb.d).

psql -v ON_ERROR_STOP=1 \
  -v pw="${DEBEZIUM_DB_PASSWORD:-debezium_secret}" \
  -v db="${POSTGRES_DB}" \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" <<'EOSQL'
CREATE USER debezium WITH PASSWORD :'pw' REPLICATION;
GRANT CONNECT ON DATABASE :"db" TO debezium;
GRANT CREATE ON DATABASE :"db" TO debezium;
GRANT USAGE ON SCHEMA public TO debezium;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO debezium;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO debezium;
EOSQL
