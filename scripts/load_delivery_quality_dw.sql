-- Refresh dw.dim_date, dw.dim_sales_order, dw.fact_delivery_quality from OLTP (public).
-- Assignment report §6.4.2: is_not_yet_delivered applies only when the order is undelivered
-- AND sale_orders.order_date falls in the reporting month.
--
-- Reporting month default: calendar month of CURRENT_DATE. To pin a month in the same psql session:
--   CREATE TEMP TABLE IF NOT EXISTS _dw_reporting_params (reporting_year_month TEXT NOT NULL);
--   DELETE FROM _dw_reporting_params;
--   INSERT INTO _dw_reporting_params VALUES ('2026-04');
--   \i scripts/load_delivery_quality_dw.sql
--
-- Docker (from host): .\scripts\run_dw_etl.ps1  OR  bash scripts/run_dw_etl.sh
-- Manual psql: psql "postgresql://supplychain:supplychain_secret@localhost:5432/supplychain" -f scripts/load_delivery_quality_dw.sql

CREATE TEMP TABLE IF NOT EXISTS _dw_reporting_params (
    reporting_year_month TEXT NOT NULL
);

INSERT INTO _dw_reporting_params (reporting_year_month)
SELECT to_char(CURRENT_DATE, 'YYYY-MM')
WHERE NOT EXISTS (SELECT 1 FROM _dw_reporting_params);

TRUNCATE TABLE dw.fact_delivery_quality, dw.dim_sales_order, dw.dim_date;

INSERT INTO dw.dim_date (date_key, full_date, month, year, year_month)
SELECT
    CAST(TO_CHAR(d, 'YYYYMMDD') AS INTEGER) AS date_key,
    d AS full_date,
    EXTRACT(MONTH FROM d)::INTEGER AS month,
    EXTRACT(YEAR FROM d)::INTEGER AS year,
    TO_CHAR(d, 'YYYY-MM') AS year_month
FROM generate_series(
    (SELECT MIN(order_date) FROM sale_orders),
    COALESCE((SELECT MAX(req_delivery_date) FROM sale_orders), CURRENT_DATE),
    INTERVAL '1 day'
) AS t(d);

INSERT INTO dw.dim_sales_order (sale_order_id, current_status)
SELECT
    so.sale_order_id,
    COALESCE(ls.status, so.status)
FROM sale_orders so
LEFT JOIN (
    SELECT DISTINCT ON (sos.sale_order_id)
        sos.sale_order_id,
        sos.status
    FROM sale_order_status sos
    ORDER BY sos.sale_order_id, sos.status_timestamp DESC
) ls ON ls.sale_order_id = so.sale_order_id;

WITH delivered_status AS (
    SELECT
        sos.sale_order_id,
        MAX(sos.status_timestamp)::date AS actual_delivery_date
    FROM sale_order_status sos
    WHERE sos.status = 'delivered'
    GROUP BY sos.sale_order_id
),
params AS (
    SELECT reporting_year_month FROM _dw_reporting_params LIMIT 1
)
INSERT INTO dw.fact_delivery_quality (
    order_key,
    order_date_key,
    planned_delivery_date_key,
    actual_delivery_date_key,
    delay_days,
    is_not_yet_delivered,
    is_on_time,
    is_late_under_1_week,
    is_late_under_2_weeks,
    is_late_over_2_weeks
)
SELECT
    dso.order_key,
    CAST(TO_CHAR(so.order_date, 'YYYYMMDD') AS INTEGER) AS order_date_key,
    CAST(TO_CHAR(so.req_delivery_date, 'YYYYMMDD') AS INTEGER) AS planned_delivery_date_key,
    CASE
        WHEN ds.actual_delivery_date IS NULL THEN NULL
        ELSE CAST(TO_CHAR(ds.actual_delivery_date, 'YYYYMMDD') AS INTEGER)
    END AS actual_delivery_date_key,
    CASE
        WHEN ds.actual_delivery_date IS NULL THEN NULL
        ELSE (ds.actual_delivery_date - so.req_delivery_date)
    END AS delay_days,
    CASE
        WHEN ds.actual_delivery_date IS NULL
            AND to_char(so.order_date, 'YYYY-MM') = (SELECT reporting_year_month FROM params)
        THEN 1
        ELSE 0
    END AS is_not_yet_delivered,
    CASE
        WHEN ds.actual_delivery_date IS NOT NULL
            AND (ds.actual_delivery_date - so.req_delivery_date) <= 0
        THEN 1
        ELSE 0
    END AS is_on_time,
    CASE
        WHEN ds.actual_delivery_date IS NOT NULL
            AND (ds.actual_delivery_date - so.req_delivery_date) BETWEEN 1 AND 7
        THEN 1
        ELSE 0
    END AS is_late_under_1_week,
    CASE
        WHEN ds.actual_delivery_date IS NOT NULL
            AND (ds.actual_delivery_date - so.req_delivery_date) BETWEEN 8 AND 14
        THEN 1
        ELSE 0
    END AS is_late_under_2_weeks,
    CASE
        WHEN ds.actual_delivery_date IS NOT NULL
            AND (ds.actual_delivery_date - so.req_delivery_date) > 14
        THEN 1
        ELSE 0
    END AS is_late_over_2_weeks
FROM sale_orders so
JOIN dw.dim_sales_order dso ON dso.sale_order_id = so.sale_order_id
LEFT JOIN delivered_status ds ON ds.sale_order_id = so.sale_order_id;
