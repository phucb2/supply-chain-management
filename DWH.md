# DWH.md

**Use this file when:** you need to refresh the delivery-quality star schema, interpret `dw.*` tables, or run monthly KPI queries. **Scope:** batch ETL from operational Postgres (`public`) into schema `dw` (not Kafka/CDC or ML).

---

## Schema (`dw`)

| Object | Role |
|--------|------|
| `dw.dim_date` | Calendar; `date_key` is `YYYYMMDD` integer; `year_month` is `'YYYY-MM'`. |
| `dw.dim_sales_order` | One row per `sale_orders.sale_order_id`; `current_status` from latest `sale_order_status` by time, else `sale_orders.status`. |
| `dw.fact_delivery_quality` | Grain: one row per sales order. Measures: date keys, `delay_days`, binary flags (`is_not_yet_delivered`, on-time / late buckets). |

Source tables: `public.sale_orders`, `public.sale_order_status` (actual delivery = max `status_timestamp` where `status = 'delivered'`).

DDL: [`infra/postgres/init.sql`](infra/postgres/init.sql).

## Reporting month (`is_not_yet_delivered`)

Per assignment spec §6.4.2, `is_not_yet_delivered = 1` only if the order has **no** delivered status **and** `sale_orders.order_date` falls in the **reporting month** (`YYYY-MM`). Other open orders keep `0` on that flag.

- **Default:** first run of [`scripts/load_delivery_quality_dw.sql`](scripts/load_delivery_quality_dw.sql) seeds `_dw_reporting_params` with `to_char(current_date, 'YYYY-MM')`.
- **Pinned month (same `psql` session):** create/fill `_dw_reporting_params` *before* loading; see comments at the top of the load script.

Align the KPI reporting month with the ETL month when interpreting `is_not_yet_delivered` and totals.

## Run the ETL

**Docker (recommended):** Postgres service must be up.

```powershell
# Windows — optional: -ReportingMonth 2026-04
.\scripts\run_dw_etl.ps1
```

```bash
# Linux/macOS — optional: ./scripts/run_dw_etl.sh 2026-04
./scripts/run_dw_etl.sh
```

**Pipe SQL into the container** (one session; sets month then loads):

```powershell
$month = Get-Date -Format 'yyyy-MM'
$init = @"
CREATE TEMP TABLE IF NOT EXISTS _dw_reporting_params (reporting_year_month TEXT NOT NULL);
DELETE FROM _dw_reporting_params;
INSERT INTO _dw_reporting_params VALUES ('$month');
"@
$init + (Get-Content -Raw scripts\load_delivery_quality_dw.sql) | docker compose exec -T postgresql psql -U supplychain -d supplychain -v ON_ERROR_STOP=1
```

**Local `psql`:** use the same URL/credentials as [`docker-compose.yml`](docker-compose.yml) (`POSTGRES_*` defaults).

Refresh is a **full** truncate + reload of `dw.fact_delivery_quality`, `dw.dim_sales_order`, and `dw.dim_date` (single `TRUNCATE` for FK safety).

## KPI queries

[`scripts/dw_delivery_quality_kpis.sql`](scripts/dw_delivery_quality_kpis.sql) implements Table 4–style aggregates: filter facts by **`order_date_key` → `dim_date.year_month`**, using `_dw_reporting_params` the same way as the load script. Run in a session whose reporting month matches the ETL run you care about.

Example via Docker:

```powershell
Get-Content -Raw scripts\dw_delivery_quality_kpis.sql | docker compose exec -T postgresql psql -U supplychain -d supplychain -v ON_ERROR_STOP=1
```

## Grafana

After the ETL load, open **http://localhost:3000** and use the provisioned dashboard **DW — Delivery quality KPIs** (`dw-delivery-quality-kpis`). Choose **Order cohort month** (from `dim_date`, plus current calendar month as fallback). The datasource **Supply Chain DW** is provisioned in [`infra/grafana/provisioning/datasources/datasources.yaml`](infra/grafana/provisioning/datasources/datasources.yaml) (PostgreSQL: `postgresql:5432`, database `supplychain`).

## Operational notes

- **Seed data:** [`scripts/seed_training_data.sql`](scripts/seed_training_data.sql) can populate orders/statuses for local checks.
- **Compose hint:** the Postgres service comment in `docker-compose.yml` points at the ETL scripts.
- **Out of scope here:** streaming CDC to Kafka, ML training/inference — see project design docs for those paths.
