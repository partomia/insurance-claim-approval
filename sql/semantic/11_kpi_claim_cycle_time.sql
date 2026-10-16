-- Certified KPI: claim cycle time (ref.kpi_definition kpi_code = 'CCT').
-- Grain: decided claim x snapshot business date. cycle_days = (decided_ts - fnol_ts) / 86400.
-- Consumers report the median and P90 by claim type and decision month (mis_cycle_time).

DROP VIEW IF EXISTS rsingh_mcc_semantic.kpi_claim_cycle_time;

CREATE VIEW rsingh_mcc_semantic.kpi_claim_cycle_time
COMMENT 'Certified KPI CCT v1.0: one row per decided claim per snapshot business date, days from FNOL to decision'
AS
SELECT f.business_date,
       CAST(f.decided_ts AS DATE)                                      AS decision_date,
       concat(CAST(year(f.decided_ts) AS STRING), '-', lpad(CAST(month(f.decided_ts) AS STRING), 2, '0'))
                                                                       AS decision_month,
       f.claim_id, f.claim_type, f.status, f.decided_by, f.fnol_ts, f.decided_ts,
       CAST((unix_timestamp(f.decided_ts) - unix_timestamp(f.fnol_ts)) / 86400.0 AS DOUBLE) AS cycle_days
FROM rsingh_mcc_gold.fact_claim f
WHERE f.status IN ('APPROVED', 'REJECTED') AND f.decided_ts IS NOT NULL;
