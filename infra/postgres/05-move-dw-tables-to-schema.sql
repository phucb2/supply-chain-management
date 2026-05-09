-- One-time migration: move star-schema tables from public to dw.
-- Backup the database first. Run only on DBs created before dw schema split.
-- New installs: use init.sql only (tables are created in dw already).

CREATE SCHEMA IF NOT EXISTS dw;

ALTER TABLE public.dim_date SET SCHEMA dw;
ALTER TABLE public.dim_sales_order SET SCHEMA dw;
ALTER TABLE public.fact_delivery_quality SET SCHEMA dw;
