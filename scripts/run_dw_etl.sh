#!/usr/bin/env bash
# Refresh dw delivery-quality star schema. Args: [YYYY-MM] (default: current month).
set -euo pipefail
MONTH="${1:-$(date +%Y-%m)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
USER="${POSTGRES_USER:-supplychain}"
PASS="${POSTGRES_PASSWORD:-supplychain_secret}"
DB="${POSTGRES_DB:-supplychain}"
URL="${DATABASE_URL:-postgresql://${USER}:${PASS}@localhost:5432/${DB}}"
psql "$URL" -v ON_ERROR_STOP=1 \
  -c "CREATE TEMP TABLE IF NOT EXISTS _dw_reporting_params (reporting_year_month TEXT NOT NULL); DELETE FROM _dw_reporting_params; INSERT INTO _dw_reporting_params VALUES ('${MONTH}');" \
  -f "${HERE}/load_delivery_quality_dw.sql"
