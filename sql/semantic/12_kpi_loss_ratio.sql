-- Certified KPI: loss ratio (ref.kpi_definition kpi_code = 'LR').
-- Grain: policy x calendar month of its current term x snapshot business date (gold.fact_policy_month).
-- Earned premium is the annual premium pro rata for the days in force in the month; approved
-- amount is the claims approved on incidents in that month and term.
-- Consumers: SUM(approved_amount) / SUM(earned_premium).

DROP VIEW IF EXISTS rsingh_mcc_semantic.kpi_loss_ratio;

CREATE VIEW rsingh_mcc_semantic.kpi_loss_ratio
COMMENT 'Certified KPI LR v1.0: policy x month x snapshot business date, earned premium and approved claims (INR)'
AS
SELECT m.business_date, m.policy_number,
       concat(CAST(year(m.premium_month) AS STRING), '-', lpad(CAST(month(m.premium_month) AS STRING), 2, '0'))
                                                       AS premium_month,
       m.days_in_force,
       CAST(m.earned_premium AS DOUBLE)                AS earned_premium,
       CAST(m.approved_amount AS DOUBLE)               AS approved_amount,
       m.approved_claims
FROM rsingh_mcc_gold.fact_policy_month m;
