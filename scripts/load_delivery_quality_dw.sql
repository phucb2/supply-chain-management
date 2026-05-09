-- Build and refresh dw.dim_date, dw.dim_sales_order, dw.fact_delivery_quality from OLTP (public).

TRUNCATE TABLE dw.fact_delivery_quality;
TRUNCATE TABLE dw.dim_sales_order;
TRUNCATE TABLE dw.dim_date;

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
    so.status
FROM sale_orders so;

WITH delivered_status AS (
    SELECT
        sos.sale_order_id,
        MAX(sos.status_timestamp)::date AS actual_delivery_date
    FROM sale_order_status sos
    WHERE sos.status = 'delivered'
    GROUP BY sos.sale_order_id
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
    CASE WHEN ds.actual_delivery_date IS NULL THEN 1 ELSE 0 END AS is_not_yet_delivered,
    CASE
        WHEN ds.actual_delivery_date IS NOT NULL
         AND (ds.actual_delivery_date - so.req_delivery_date) <= 0
        THEN 1 ELSE 0
    END AS is_on_time,
    CASE
        WHEN ds.actual_delivery_date IS NOT NULL
         AND (ds.actual_delivery_date - so.req_delivery_date) BETWEEN 1 AND 7
        THEN 1 ELSE 0
    END AS is_late_under_1_week,
    CASE
        WHEN ds.actual_delivery_date IS NOT NULL
         AND (ds.actual_delivery_date - so.req_delivery_date) BETWEEN 8 AND 14
        THEN 1 ELSE 0
    END AS is_late_under_2_weeks,
    CASE
        WHEN ds.actual_delivery_date IS NOT NULL
         AND (ds.actual_delivery_date - so.req_delivery_date) > 14
        THEN 1 ELSE 0
    END AS is_late_over_2_weeks
FROM sale_orders so
JOIN dw.dim_sales_order dso ON dso.sale_order_id = so.sale_order_id
LEFT JOIN delivered_status ds ON ds.sale_order_id = so.sale_order_id;
