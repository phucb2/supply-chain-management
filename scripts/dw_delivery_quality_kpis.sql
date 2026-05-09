-- KPI aggregations over dw.fact_delivery_quality (assignment report Table 4).
-- Scope: orders whose order_date falls in the reporting month (join dim_date on order_date_key).
-- Run after load_delivery_quality_dw.sql with the same reporting month in _dw_reporting_params,
-- or create the temp table first (see load script header). Standalone: defaults to current month.

CREATE TEMP TABLE IF NOT EXISTS _dw_reporting_params (
    reporting_year_month TEXT NOT NULL
);

INSERT INTO _dw_reporting_params (reporting_year_month)
SELECT to_char(CURRENT_DATE, 'YYYY-MM')
WHERE NOT EXISTS (SELECT 1 FROM _dw_reporting_params);

WITH params AS (
    SELECT reporting_year_month AS ym FROM _dw_reporting_params LIMIT 1
),
scoped AS (
    SELECT
        f.is_not_yet_delivered,
        f.is_on_time,
        f.is_late_under_1_week,
        f.is_late_under_2_weeks,
        f.is_late_over_2_weeks
    FROM dw.fact_delivery_quality f
    JOIN dw.dim_date dd ON dd.date_key = f.order_date_key
    WHERE dd.year_month = (SELECT ym FROM params)
)
SELECT
    (SELECT ym FROM params) AS reporting_year_month,
    SUM(
        is_not_yet_delivered + is_on_time + is_late_under_1_week
        + is_late_under_2_weeks + is_late_over_2_weeks
    ) AS total_orders_per_month,
    SUM(is_on_time + is_late_under_1_week + is_late_under_2_weeks + is_late_over_2_weeks) AS delivery_successful,
    SUM(is_not_yet_delivered) AS not_yet_delivered,
    CASE
        WHEN SUM(
            is_not_yet_delivered + is_on_time + is_late_under_1_week
            + is_late_under_2_weeks + is_late_over_2_weeks
        ) = 0 THEN NULL
        ELSE ROUND(
            SUM(is_on_time)::numeric
            / NULLIF(
                SUM(
                    is_not_yet_delivered + is_on_time + is_late_under_1_week
                    + is_late_under_2_weeks + is_late_over_2_weeks
                ),
                0
            ),
            4
        )
    END AS on_time_delivery_rate,
    CASE
        WHEN SUM(
            is_not_yet_delivered + is_on_time + is_late_under_1_week
            + is_late_under_2_weeks + is_late_over_2_weeks
        ) = 0 THEN NULL
        ELSE ROUND(
            SUM(is_late_under_1_week)::numeric
            / NULLIF(
                SUM(
                    is_not_yet_delivered + is_on_time + is_late_under_1_week
                    + is_late_under_2_weeks + is_late_over_2_weeks
                ),
                0
            ),
            4
        )
    END AS late_under_1_week_rate,
    CASE
        WHEN SUM(
            is_not_yet_delivered + is_on_time + is_late_under_1_week
            + is_late_under_2_weeks + is_late_over_2_weeks
        ) = 0 THEN NULL
        ELSE ROUND(
            SUM(is_late_under_2_weeks)::numeric
            / NULLIF(
                SUM(
                    is_not_yet_delivered + is_on_time + is_late_under_1_week
                    + is_late_under_2_weeks + is_late_over_2_weeks
                ),
                0
            ),
            4
        )
    END AS late_under_2_weeks_rate,
    CASE
        WHEN SUM(
            is_not_yet_delivered + is_on_time + is_late_under_1_week
            + is_late_under_2_weeks + is_late_over_2_weeks
        ) = 0 THEN NULL
        ELSE ROUND(
            SUM(is_late_over_2_weeks)::numeric
            / NULLIF(
                SUM(
                    is_not_yet_delivered + is_on_time + is_late_under_1_week
                    + is_late_under_2_weeks + is_late_over_2_weeks
                ),
                0
            ),
            4
        )
    END AS late_over_2_weeks_rate
FROM scoped;
