# Refresh dw delivery-quality star schema. Sets reporting month for is_not_yet_delivered (report §6.4.2).
# Usage: .\scripts\run_dw_etl.ps1 [-ReportingMonth 2026-04] [-PostgresUrl "postgresql://user:pass@localhost:5432/supplychain"]
param(
    [string]$ReportingMonth = (Get-Date -Format 'yyyy-MM'),
    [string]$PostgresUrl = 'postgresql://supplychain:supplychain_secret@localhost:5432/supplychain'
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$initParams = @"
CREATE TEMP TABLE IF NOT EXISTS _dw_reporting_params (reporting_year_month TEXT NOT NULL);
DELETE FROM _dw_reporting_params;
INSERT INTO _dw_reporting_params VALUES ('$ReportingMonth');
"@
& psql $PostgresUrl -v ON_ERROR_STOP=1 -c $initParams -f (Join-Path $here 'load_delivery_quality_dw.sql')
