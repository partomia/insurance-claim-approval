-- Certified KPI: straight-through rate (ref.kpi_definition kpi_code = 'STP').
-- Grain: decided claim x snapshot business date. is_stp = decided by ref.kpi_parameter
-- stp_decided_by (AUTO): no adjuster or SIU touch. Consumers: SUM(is_stp) / COUNT(*).

DROP VIEW IF EXISTS rsingh_mcc_semantic.kpi_straight_through_rate;

CREATE VIEW rsingh_mcc_semantic.kpi_straight_through_rate
COMMENT 'Certified KPI STP v1.0: one row per decided claim per snapshot business date; is_stp = decided automatically'
AS
SELECT f.business_date,
       CAST(f.decided_ts AS DATE)                                      AS decision_date,
       concat(CAST(year(f.decided_ts) AS STRING), '-', lpad(CAST(month(f.decided_ts) AS STRING), 2, '0'))
                                                                       AS decision_month,
       f.claim_id, f.claim_type, f.status, f.decided_by,
       CASE WHEN instr(concat(',', p.value, ','), concat(',', f.decided_by, ',')) > 0 THEN 1 ELSE 0 END AS is_stp
FROM rsingh_mcc_gold.fact_claim f
CROSS JOIN (SELECT value FROM rsingh_mcc_ref.kpi_parameter WHERE parameter = 'stp_decided_by') p
WHERE f.status IN ('APPROVED', 'REJECTED');
