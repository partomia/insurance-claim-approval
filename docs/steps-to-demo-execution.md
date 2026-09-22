# Steps to Demo Execution — OLTP + Lakehouse Story

A click/command runbook for demoing the full **OLTP + Lakehouse** story
end-to-end, in order. Written for the person driving the demo, not for
someone setting the environment up.

**Assumes everything is already running and ready:**
- CAI Application (or a Session with `bash cml/cli.sh start --bg`) is up and
  reachable.
- CDE jobs are deployed and the pipeline has run at least once (gold tables
  populated — `insurance_lakehouse.{policy_master,policy_clauses,
  policy_risk_signals,garage_risk_signals}`).
- `bash cml/cli.sh lakehouse ingest` has been run at least once (lakehouse
  data is in the app's SQLite DB + Chroma).

If any of that isn't true yet, stop and see [`cml/README.md`](../cml/README.md)
(§ Data lakehouse) and [`cde/README.md`](../cde/README.md) first — this doc
is the "day of the demo" script, not the setup guide.

Total runtime: **~10-12 minutes** end to end, all 4 beats.

---

## Cheat sheet (all commands, no explanation)

```bash
# 0. Preflight
bash cml/cli.sh smoke
bash cml/cli.sh lakehouse verify

# Beat 2 — risk score drives the decision engine
bash cml/cli.sh test-claim find --band HIGH --not-expired
bash cml/cli.sh test-claim submit --policy-number <LH-POL-XXXX>
bash cml/cli.sh test-claim find --band LOW --not-expired
bash cml/cli.sh test-claim submit --policy-number <LH-POL-XXXX>

# Beat 3 — app claims flow back into the lakehouse
bash cml/cli.sh lakehouse export-claims --dry-run
bash cml/cli.sh lakehouse export-claims

# Beat 4 — Iceberg time travel / audit
bash cml/cli.sh lakehouse history --table policy_risk_signals
bash cml/cli.sh lakehouse as-of --table policy_risk_signals \
  --policy-number <LH-POL-XXXX> --snapshot <id from history>

# (run ahead of time, from your local machine, not the CAI session, if you
# want a guaranteed fresh diff for Beat 4 instead of relying on whatever
# history already exists)
./cde/scripts/time_travel_drill.sh
```

Demo logins: insurer `insurer1@claimcopilot.in` / `password123` / OTP
`112233`. Lakehouse-ingested customers (`customerNN@example.com`) need a
password set once via `set_demo_password.py` (§ Beat 1 below) before you can
log in as one — `test-claim submit` does this automatically for you.

---

## Beat 1 — Lakehouse risk data surfaced in the app UI

**Story point:** lakehouse analytics (`fraud_risk_score`, `claim_risk_band`)
aren't buried in a table somewhere — an insurer sees them directly in the
UI they already use.

1. Log in to the app as the demo insurer: `insurer1@claimcopilot.in` /
   `password123` / OTP `112233`.
2. Open **Book of Business**. Sort/filter by risk band — point out the
   `claim_risk_band` (`HIGH`/`MEDIUM`/`LOW`) and `fraud_risk_score` columns
   on every `LH-POL-*` policy. This data originated in the CDE Spark
   pipeline, not hand-entered.
3. Pick a `HIGH`-band policy's customer (e.g. one from `lakehouse verify` /
   Book of Business — the transcript has used `LH-POL-2050` /
   `customer50@example.com` before). If that customer doesn't have a known
   password yet:
   ```bash
   cd backend
   uv run python scripts/set_demo_password.py --list-lakehouse-customers
   uv run python scripts/set_demo_password.py --role customer \
     --email customer50@example.com --password password123
   ```
4. Log in as that customer (OTP `112233`), file a claim against their
   `LH-POL-*` policy (use the synthetic evidence docs in
   [`docs/demo-assets/claim-docs/`](demo-assets/claim-docs/README.md) for
   the Evidence Upload step).
5. Log back in as the insurer, open that claim for review — the **Claim
   Insights risk card** shows the same `fraud_risk_score`/`claim_risk_band`
   next to the claim itself, pulled through the same shared query path
   (`backend/services/policy_risk_service.py`) as Book of Business — one
   signal, two surfaces, always consistent.

Skip straight to Beat 2 if you'd rather not run a full claim wizard live —
`test-claim submit` (below) does steps 3-4 headlessly in one command.

---

## Beat 2 — the risk score actually drives the decision, not just cosmetic

**Story point:** `fraud_risk_score`/`claim_risk_band` don't just decorate a
UI — they feed `fraud_detection.py` and `escalation_service.py`, and can
flip a claim's outcome to `PENDING_REVIEW`.

1. Find a non-expired `HIGH`-band policy to demo with:
   ```bash
   bash cml/cli.sh test-claim find --band HIGH --not-expired
   ```
   Pick any policy number from the output, e.g. `LH-POL-2059`.

2. File and submit a full claim against it in one shot (sets the customer's
   password, logs in, drafts, links the policy, uploads synthetic evidence,
   submits, polls for the decision):
   ```bash
   bash cml/cli.sh test-claim submit --policy-number LH-POL-2059
   ```
   Expect:
   ```
   status: PENDING_REVIEW
   fraud_score: 0.4
   escalation_flags: ['high_fraud_score', 'lakehouse_high_risk_policy']
   - This policy's claims history is flagged HIGH risk by the lakehouse
     analytics pipeline (score 70/100, 22 historical claims) — underwriting
     review recommended
   ```
   Call out: `fraud_score` (0.40) exactly matches the `lakehouse_risk_high`
   signal weight in `fraud_detection.py` — this claim didn't need any other
   red flag to land on manual review; the lakehouse signal alone did it.

3. **Contrast with a LOW-band policy** — same flow, different outcome,
   proving the signal is additive and correctly gated by risk band (not a
   blanket "always escalate" rule):
   ```bash
   bash cml/cli.sh test-claim find --band LOW --not-expired
   bash cml/cli.sh test-claim submit --policy-number LH-POL-2000
   ```
   Expect `status: ANALYSIS_COMPLETE`, no `lakehouse_high_risk_policy` flag,
   no score bump.

4. **(Optional, deeper regression proof)** — a policy with *no* lakehouse
   signal at all behaves identically to how it always did (true no-op):
   ```bash
   bash cml/cli.sh test-claim find --no-signal --not-expired
   bash cml/cli.sh test-claim submit --policy-number POL-MTR-1001
   ```

---

## Beat 3 — claims filed in the app flow back into the lakehouse

**Story point:** the loop is two-way. Lakehouse risk data flows into the
app (Beats 1-2); claims actually filed *through the app* — including the
one you just submitted in Beat 2 — flow back into the same analytics, not
just the CDE pipeline's synthetic claims history.

1. Preview what would be exported (no writes):
   ```bash
   bash cml/cli.sh lakehouse export-claims --dry-run
   ```
   You should see the claim(s) submitted in Beat 2 listed (any decided
   claim linked to a policy that hasn't been exported yet).

2. Actually export:
   ```bash
   bash cml/cli.sh lakehouse export-claims
   ```
   This writes into `insurance_lakehouse_bronze.app_claims_raw` via Impala
   and marks the claim(s) as exported (`claims.lakehouse_exported_at`) —
   idempotent, safe to re-run.

3. **(Optional, full loop-closure)** — feed the newly-exported claim(s)
   back through the CDE pipeline and re-ingest, to show the risk score
   itself can move because of app-originated data:
   ```bash
   cde job run --name rsingh-insurance-transform-claims-silver --wait
   cde job run --name rsingh-insurance-curate-risk-signals-gold --wait
   ```
   Then, back in the app:
   ```bash
   bash cml/cli.sh lakehouse ingest
   ```
   Skip this sub-step if you're short on time — Beats 1-2 already prove the
   inbound direction, and Beat 4 will show the outbound MERGE committing
   regardless.

---

## Beat 4 — Iceberg time travel / audit trail

**Story point:** the gold tables write via `MERGE INTO`, not
drop+recreate — every pipeline run commits a real Iceberg snapshot. For a
bank, this *is* the audit/regulatory pitch: "what did we know about this
policy's risk on date X, and can you prove it?"

1. List every snapshot committed to a gold table:
   ```bash
   bash cml/cli.sh lakehouse history --table policy_risk_signals
   ```
   Example output:
   ```
   creation_time                  snapshot_id          parent_id            is_current_ancestor
   2026-09-21 11:41:02.199000000  4967580225782225719  NULL                 TRUE
   2026-09-22 13:53:07.023000000  6300977543968207922  4967580225782225719  TRUE
   ```

2. Pick a policy and an older snapshot ID from that list, and diff it
   against the current row:
   ```bash
   bash cml/cli.sh lakehouse as-of --table policy_risk_signals \
     --policy-number LH-POL-2059 --snapshot 4967580225782225719
   ```
   Talking point from a real run: `LH-POL-2059` was `HIGH`-band (score
   69.6, 22 claims) at that snapshot and `MEDIUM`-band (score 36.4, 4
   claims) at the current one — `as-of` prints both rows side by side plus
   an automatic column-level diff (9 columns changed, zero manual
   comparison). This is provable, queryable history — not "trust today's
   number."

3. **If `history` only shows one snapshot** (e.g. a fresh environment, or
   the pipeline hasn't crossed a day boundary yet), you won't have a second
   point to diff against yet. Run the on-demand drill **ahead of the demo**,
   from your local machine (needs the `cde` CLI, not the CAI session):
   ```bash
   ./cde/scripts/time_travel_drill.sh              # earlier date defaults to 7 days ago
   ./cde/scripts/time_travel_drill.sh 2026-09-10   # or pick a specific date
   ```
   This runs the full generate → validate → transform → curate chain
   twice — once seeded as an earlier date, once as today — guaranteeing
   two meaningfully different snapshots to show in step 1-2 above, without
   waiting for a real calendar day to pass. Takes as long as two full CDE
   pipeline passes (budget 15-30+ min depending on vcluster scale-up —
   run this well before the demo, not live during it).

   **Pick the right snapshot pair, or the diff will look empty.** The
   drill's Pass 2 always reseeds as *today* — if the pipeline already ran
   once today before you ran the drill, Pass 2 reproduces byte-identical
   data to that earlier same-day run, so diffing them shows only
   `ingested_at` changed (confirmed live — not a bug, see
   [`cde/README.md`](../cde/README.md#gotchas-we-actually-hit) Gotcha #9).
   The script prints wall-clock timestamps around each pass specifically so
   you can match them against `creation_time` in `history`'s output and
   pick **Pass 1's snapshot** (seeded as the explicit earlier date) to
   diff against CURRENT — that pairing is guaranteed to differ, since it
   spans two different seed-dates.

---

## Wrap-up talking points

By the end of these 4 beats you've shown, live, that the "OLTP +
Lakehouse" story is a real closed loop, not a one-way demo:

1. **Lakehouse → App**: risk analytics computed in Spark surface directly
   in the insurer UI (Book of Business + Claim Insights risk card).
2. **Lakehouse → Decision**: that same risk signal isn't cosmetic — it
   feeds `fraud_detection.py`/`escalation_service.py` and can flip a
   claim to `PENDING_REVIEW`, gated correctly by risk band (proven via the
   HIGH vs. LOW vs. no-signal contrast in Beat 2).
3. **App → Lakehouse**: claims filed through the live app flow back into
   the same analytics (`export-claims`), so the risk model keeps learning
   from real usage, not just synthetic history.
4. **Audit trail**: every gold-table write is a real Iceberg snapshot via
   `MERGE INTO` — `DESCRIBE HISTORY` / `FOR SYSTEM_TIME|VERSION AS OF` let
   you prove what the system knew and when, which is exactly what a bank's
   compliance/audit function needs from a data platform.

See also: [`README.md`](../README.md) (§ Data Lakehouse, architecture
diagram), [`cde/README.md`](../cde/README.md) (pipeline internals,
roadmap), [`cml/README.md`](../cml/README.md) (full command reference).
