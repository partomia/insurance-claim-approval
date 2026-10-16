-- MIS views: aggregates of the certified KPI views only, never a re-derived formula, so every
-- figure here reconciles to its KPI view (scripts/run_semantic.py check).

DROP VIEW IF EXISTS rsingh_mcc_semantic.mis_stp_by_month;

CREATE VIEW rsingh_mcc_semantic.mis_stp_by_month
COMMENT 'MIS: straight-through rate by decision month and claim type (kpi_straight_through_rate)'
AS
SELECT m.*, CASE WHEN m.business_date = l.latest_date THEN 1 ELSE 0 END AS is_latest
FROM (
SELECT business_date, decision_month, claim_type,
       COUNT(*)                                  AS decided_claims,
       SUM(is_stp)                               AS stp_claims,
       CAST(SUM(is_stp) AS DOUBLE) / COUNT(*)    AS stp_rate
FROM rsingh_mcc_semantic.kpi_straight_through_rate
GROUP BY business_date, decision_month, claim_type
) m
CROSS JOIN (SELECT MAX(business_date) AS latest_date FROM rsingh_mcc_semantic.kpi_straight_through_rate) l;

DROP VIEW IF EXISTS rsingh_mcc_semantic.mis_cycle_time;

CREATE VIEW rsingh_mcc_semantic.mis_cycle_time
COMMENT 'MIS: claim cycle time (days) by decision month and claim type: average, median and P90 (kpi_claim_cycle_time)'
AS
SELECT m.*, CASE WHEN m.business_date = l.latest_date THEN 1 ELSE 0 END AS is_latest
FROM (
SELECT business_date, decision_month, claim_type,
       COUNT(*)                                              AS decided_claims,
       SUM(cycle_days)                                       AS total_days,
       AVG(cycle_days)                                       AS avg_days,
       MIN(CASE WHEN pr >= 0.5 THEN cycle_days END)          AS median_days,
       MIN(CASE WHEN pr >= 0.9 THEN cycle_days END)          AS p90_days
FROM (
    SELECT k.business_date, k.decision_month, k.claim_type, k.cycle_days,
           PERCENT_RANK() OVER (PARTITION BY k.business_date, k.decision_month, k.claim_type
                                ORDER BY k.cycle_days) AS pr
    FROM rsingh_mcc_semantic.kpi_claim_cycle_time k
) r
GROUP BY business_date, decision_month, claim_type
) m
CROSS JOIN (SELECT MAX(business_date) AS latest_date FROM rsingh_mcc_semantic.kpi_claim_cycle_time) l;

DROP VIEW IF EXISTS rsingh_mcc_semantic.mis_loss_ratio_by_month;

CREATE VIEW rsingh_mcc_semantic.mis_loss_ratio_by_month
COMMENT 'MIS: loss ratio by calendar month (kpi_loss_ratio)'
AS
SELECT m.*, CASE WHEN m.business_date = l.latest_date THEN 1 ELSE 0 END AS is_latest
FROM (
SELECT business_date, premium_month,
       COUNT(*)                                                   AS policy_months,
       SUM(earned_premium)                                        AS earned_premium,
       SUM(approved_amount)                                       AS approved_amount,
       SUM(approved_claims)                                       AS approved_claims,
       CASE WHEN SUM(earned_premium) > 0 THEN SUM(approved_amount) / SUM(earned_premium) END AS loss_ratio
FROM rsingh_mcc_semantic.kpi_loss_ratio
GROUP BY business_date, premium_month
) m
CROSS JOIN (SELECT MAX(business_date) AS latest_date FROM rsingh_mcc_semantic.kpi_loss_ratio) l;
