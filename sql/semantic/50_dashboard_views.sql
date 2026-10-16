-- Dashboard views (Data Visualization datasets "MCC ..."): the latest snapshot only, flat, with
-- display-ready labels. Figures come from the MIS / KPI views or gold, never re-derived.

DROP VIEW IF EXISTS rsingh_mcc_semantic.dash_kpi_summary;

CREATE VIEW rsingh_mcc_semantic.dash_kpi_summary
COMMENT 'Dashboard: the three certified KPIs for the latest snapshot, all decisions on record'
AS
SELECT s.business_date,
       s.decided_claims, s.stp_claims, s.stp_rate,
       c.avg_cycle_days,
       lr.earned_premium, lr.approved_amount, lr.loss_ratio
FROM (SELECT business_date, SUM(decided_claims) AS decided_claims, SUM(stp_claims) AS stp_claims,
             CAST(SUM(stp_claims) AS DOUBLE) / SUM(decided_claims) AS stp_rate
      FROM rsingh_mcc_semantic.mis_stp_by_month WHERE is_latest = 1 GROUP BY business_date) s
JOIN (SELECT business_date, SUM(total_days) / SUM(decided_claims) AS avg_cycle_days
      FROM rsingh_mcc_semantic.mis_cycle_time WHERE is_latest = 1 GROUP BY business_date) c
  ON c.business_date = s.business_date
JOIN (SELECT business_date, SUM(earned_premium) AS earned_premium, SUM(approved_amount) AS approved_amount,
             SUM(approved_amount) / SUM(earned_premium) AS loss_ratio
      FROM rsingh_mcc_semantic.mis_loss_ratio_by_month WHERE is_latest = 1 GROUP BY business_date) lr
  ON lr.business_date = s.business_date;

DROP VIEW IF EXISTS rsingh_mcc_semantic.dash_claims;

CREATE VIEW rsingh_mcc_semantic.dash_claims
COMMENT 'Dashboard: one row per claim in the latest snapshot, with garage, telematics and VIN checks'
AS
SELECT f.claim_id, f.policy_number, f.golden_customer_id, f.claim_type, f.status, f.decided_by,
       f.reason_code, f.channel, f.incident_city,
       CAST(f.fnol_ts AS DATE)                                 AS fnol_date,
       concat(CAST(year(f.fnol_ts) AS STRING), '-', lpad(CAST(month(f.fnol_ts) AS STRING), 2, '0')) AS fnol_month,
       CAST(f.amount_requested AS DOUBLE)                      AS amount_requested,
       CAST(f.amount_approved AS DOUBLE)                       AS amount_approved,
       f.report_delay_days, f.cycle_days,
       f.garage_id, f.garage_name, f.garage_network_status,
       CASE WHEN f.crash_event_match THEN 'Matched crash event' ELSE 'No crash event' END AS telematics_check,
       CASE WHEN f.vin_mismatch THEN 'VIN mismatch' ELSE 'VIN matches policy' END        AS vin_check,
       f.business_date
FROM rsingh_mcc_gold.fact_claim f
WHERE f.business_date = (SELECT MAX(business_date) FROM rsingh_mcc_gold.fact_claim);

DROP VIEW IF EXISTS rsingh_mcc_semantic.dash_garage_risk;

CREATE VIEW rsingh_mcc_semantic.dash_garage_risk
COMMENT 'Dashboard: garage network risk (gold.garage_risk_signals + scoring context)'
AS
SELECT g.garage_name, g.claim_count, g.avg_payout, g.payout_anomaly_score,
       CASE WHEN g.flagged_high_risk THEN 'High risk' ELSE 'Normal' END AS risk_flag,
       c.garage_id, c.garage_network_status, c.garage_risk_score, c.garage_claims_30d
FROM rsingh_mcc_gold.garage_risk_signals g
LEFT JOIN rsingh_mcc_gold.scoring_context_garage c ON c.garage_name = g.garage_name;

DROP VIEW IF EXISTS rsingh_mcc_semantic.dash_recon;

CREATE VIEW rsingh_mcc_semantic.dash_recon
COMMENT 'Dashboard: reconciliation results per business date, layer and status (ref.recon_results)'
AS
SELECT business_date, layer, entity, check_name, status, expected, actual, difference, detail
FROM rsingh_mcc_ref.recon_results;
