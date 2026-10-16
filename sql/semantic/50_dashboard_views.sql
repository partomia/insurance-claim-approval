-- Dashboard views (Data Visualization datasets "MCC - ..."): flat, numeric 0/1 flags, display
-- labels and is_latest. Figures come from the KPI / MIS views or gold, never re-derived.

DROP VIEW IF EXISTS rsingh_mcc_semantic.dash_claims;

CREATE VIEW rsingh_mcc_semantic.dash_claims
COMMENT 'Dashboard: one row per claim per snapshot business date, with garage, telematics and VIN checks (gold.fact_claim)'
AS
SELECT m.*, CASE WHEN m.business_date = l.latest_date THEN 1 ELSE 0 END AS is_latest
FROM (
SELECT f.business_date, f.claim_id, f.policy_number, f.golden_customer_id, f.claim_type, f.status, f.decided_by,
       f.reason_code, f.channel, f.incident_city, f.fnol_date,
       concat(CAST(year(f.fnol_ts) AS STRING), '-', lpad(CAST(month(f.fnol_ts) AS STRING), 2, '0')) AS fnol_month,
       CAST(f.amount_requested AS DOUBLE)                                   AS amount_requested,
       CAST(coalesce(f.amount_approved, 0) AS DOUBLE)                       AS amount_approved,
       f.report_delay_days, f.cycle_days, f.garage_id, f.garage_name, f.garage_network_status,
       CASE WHEN f.crash_event_match THEN 1 ELSE 0 END                      AS is_crash_match,
       CASE WHEN f.telematics_enrolled THEN 1 ELSE 0 END                    AS is_telematics,
       CASE WHEN f.vin_mismatch THEN 1 ELSE 0 END                           AS is_vin_mismatch,
       CASE WHEN f.status IN ('APPROVED', 'REJECTED') THEN 0 ELSE 1 END     AS is_open,
       CASE WHEN f.reason_code = 'FRAUD_CONFIRMED' THEN 1 ELSE 0 END        AS is_fraud_confirmed,
       CASE WHEN f.vin_mismatch OR f.garage_network_status = 'WATCHLIST' OR f.report_delay_days > 7
                 OR (f.telematics_enrolled AND NOT f.crash_event_match
                     AND f.claim_type IN ('Collision', 'ThirdParty'))
            THEN 1 ELSE 0 END                                               AS has_red_flag
FROM rsingh_mcc_gold.fact_claim f
) m
CROSS JOIN (SELECT MAX(business_date) AS latest_date FROM rsingh_mcc_gold.fact_claim) l;

DROP VIEW IF EXISTS rsingh_mcc_semantic.dash_garage_risk;

CREATE VIEW rsingh_mcc_semantic.dash_garage_risk
COMMENT 'Dashboard: garage network risk (gold.garage_risk_signals and gold.scoring_context_garage)'
AS
SELECT g.garage_name, g.claim_count, CAST(g.avg_payout AS DOUBLE) AS avg_payout,
       CAST(g.payout_anomaly_score AS DOUBLE) AS payout_anomaly_score,
       CASE WHEN g.flagged_high_risk THEN 1 ELSE 0 END AS is_flagged,
       CASE WHEN g.flagged_high_risk THEN 'High risk' ELSE 'Normal' END AS risk_flag,
       c.garage_id, c.garage_network_status, CAST(c.garage_risk_score AS DOUBLE) AS garage_risk_score,
       c.garage_claims_30d
FROM rsingh_mcc_gold.garage_risk_signals g
LEFT JOIN rsingh_mcc_gold.scoring_context_garage c ON c.garage_name = g.garage_name;

DROP VIEW IF EXISTS rsingh_mcc_semantic.dash_recon;

CREATE VIEW rsingh_mcc_semantic.dash_recon
COMMENT 'Dashboard: every reconciliation and KPI consistency check per business date (ref.recon_results)'
AS
SELECT r.business_date, r.batch_id, r.layer,
       CASE r.layer WHEN 'bronze' THEN '1 bronze' WHEN 'stream' THEN '2 stream' WHEN 'silver' THEN '3 silver'
                    WHEN 'mdm' THEN '4 mdm' WHEN 'gold' THEN '5 gold' WHEN 'semantic' THEN '6 semantic (KPI consumers)'
                    ELSE r.layer END AS layer_label,
       r.entity, r.check_name, r.expected, r.actual, r.difference, r.status, r.detail,
       CASE WHEN r.status = 'MATCHED' THEN 1 ELSE 0 END   AS is_ok,
       CASE WHEN r.status = 'EXPLAINED' THEN 1 ELSE 0 END AS is_explained,
       CASE WHEN r.status = 'LATE' THEN 1 ELSE 0 END      AS is_late,
       CASE WHEN r.status = 'MISMATCH' THEN 1 ELSE 0 END  AS is_mismatch,
       CASE WHEN r.business_date = l.latest_date THEN 1 ELSE 0 END AS is_latest
FROM rsingh_mcc_ref.recon_results r
CROSS JOIN (SELECT MAX(business_date) AS latest_date FROM rsingh_mcc_ref.recon_results) l;

DROP VIEW IF EXISTS rsingh_mcc_semantic.dash_load_audit;

CREATE VIEW rsingh_mcc_semantic.dash_load_audit
COMMENT 'Dashboard: every stage and entity commit or failure per batch (ref.load_audit)'
AS
SELECT m.*, CASE WHEN m.business_date = l.latest_date THEN 1 ELSE 0 END AS is_latest
FROM (
SELECT a.business_date, a.batch_id, a.pipeline_run, a.stage, a.entity, a.status,
       a.rows_in, a.rows_out, a.rows_rejected, a.snapshot_after, a.started_at, a.ended_at, a.message,
       CASE WHEN a.status = 'FAILED' THEN 1 ELSE 0 END AS is_failed
FROM rsingh_mcc_ref.load_audit a
) m
CROSS JOIN (SELECT MAX(business_date) AS latest_date FROM rsingh_mcc_ref.load_audit) l;

DROP VIEW IF EXISTS rsingh_mcc_semantic.dash_customer_master;

CREATE VIEW rsingh_mcc_semantic.dash_customer_master
COMMENT 'Dashboard: how each source customer record resolved to a golden customer, by rule (mdm.customer_xref)'
AS
SELECT m.*, CASE WHEN m.business_date = l.latest_date THEN 1 ELSE 0 END AS is_latest
FROM (
SELECT x.business_date, x.golden_customer_id, x.source_system, x.source_key, x.match_rule, x.match_score,
       CASE x.match_rule WHEN 'SELF' THEN '0 anchor record' WHEN 'EMAIL' THEN '1 same email'
                         WHEN 'DOB_MOBILE' THEN '2 DOB + mobile' WHEN 'DOB_NAME' THEN '3 DOB + name'
                         WHEN 'BUREAU_DOB_MOBILE' THEN '4 bureau DOB + mobile'
                         WHEN 'BUREAU_DOB_NAME' THEN '5 bureau DOB + name' ELSE x.match_rule END AS rule_label
FROM rsingh_mcc_mdm.customer_xref x
) m
CROSS JOIN (SELECT MAX(business_date) AS latest_date FROM rsingh_mcc_mdm.customer_xref) l;

DROP VIEW IF EXISTS rsingh_mcc_semantic.dash_match_exception;

CREATE VIEW rsingh_mcc_semantic.dash_match_exception
COMMENT 'Dashboard: customer records MDM could not resolve on its own (mdm.match_exception)'
AS
SELECT m.*, CASE WHEN m.business_date = l.latest_date THEN 1 ELSE 0 END AS is_latest
FROM (
SELECT e.business_date, e.source_system, e.source_key, e.reason, e.candidates
FROM rsingh_mcc_mdm.match_exception e
) m
CROSS JOIN (SELECT MAX(business_date) AS latest_date FROM rsingh_mcc_mdm.match_exception) l;
