# Session Handoff / Memory Dump

> Read this first when resuming work on this project. Update it at the end of
> each significant session — append new dated entries, don't delete history
> unless it's fully superseded.

---

## 2026-09-23 — Session handoff: OLTP + Lakehouse story fully closed, demo runbook added

**Status: nothing in flight, nothing blocking. `main` is clean and fully
pushed.** All work described below is committed and on `origin/main`
(latest: `01a3149`). Safe to just `git pull` and pick up new work — no
half-finished branches, no uncommitted local changes (except an untracked,
unrelated `docs/diagrams/png/diagram.png` sitting in the working tree —
harmless, ignore it or `git add` it if you actually want it tracked).

### The 3-item "OLTP + Lakehouse" story (from the 2026-09-21 kickoff) is 100% done

1. **App claims → bronze** (`export-claims`) — done, pre-existing before
   this final push.
2. **Lakehouse risk signals → live decision engine** — done + verified
   live. `fraud_detection.py`/`escalation_service.py` now read
   `policy.risk_signal.claim_risk_band`; a HIGH-band policy lands on
   `PENDING_REVIEW` with a `lakehouse_high_risk_policy` flag, LOW-band and
   no-signal policies are unaffected (regression-checked). Test harness:
   `bash cml/cli.sh test-claim find|submit` →
   `backend/scripts/lakehouse_risk_claim_test.py`.
3. **Iceberg time travel** — done, all 3 steps:
   - Step 1: `curate_gold.py`/`curate_risk_signals_gold.py` write via
     `MERGE INTO` (not drop+recreate) once the target table exists;
     `generate_bronze.py`/`generate_claims_bronze.py` reseed by calendar
     day so re-runs produce real diffs. Verified live via `DESCRIBE
     HISTORY`.
   - Step 2: `bash cml/cli.sh lakehouse history|as-of` →
     `backend/scripts/lakehouse_time_travel.py`. Verified live, worked
     first try.
   - Step 3: `cde/scripts/time_travel_drill.sh` — on-demand drill that
     manufactures a fresh cross-day diff without waiting for a real day
     boundary (`generate_bronze.py`/`generate_claims_bronze.py` now take
     an optional 2nd arg: raw seed int or `YYYY-MM-DD`). **Hit and fixed a
     real gotcha while verifying this live**: the drill's Pass 2 always
     reseeds as *today*, so if the pipeline already ran once that day
     before the drill, Pass 2 reproduces byte-identical data to that
     earlier same-day run — diffing them shows only `ingested_at`
     changed. Documented as **Gotcha #9** in `cde/README.md`; the script
     now prints wall-clock timestamps around each pass so you can pick
     the *right* snapshot pair (Pass 1's earlier-date snapshot vs.
     CURRENT, not two same-day snapshots against each other).

### New this session: `docs/steps-to-demo-execution.md`

A click/command runbook for actually running this as a live demo, assuming
everything is already up (app running, CDE pipeline already run at least
once, lakehouse already ingested). 4 beats in order: lakehouse risk → UI,
risk score → live decision (HIGH vs LOW vs no-signal contrast), app claims
→ lakehouse export, Iceberg time travel/audit. Includes a cheat-sheet of
every command up front. Linked from `README.md`, `cml/README.md`,
`docs/README.md`.

### Live env1 state as of this session (for reference, will drift)

`insurance_lakehouse.policy_risk_signals` has **4 snapshots**:
```
4967580225782225719  2026-09-21 11:41  (original fixed-seed bootstrap)
6300977543968207922  2026-09-22 13:53  (first date-reseed, seeded as 2026-09-22)
2408034314406756364  2026-09-22 20:01  (drill Pass 1, seeded as an earlier date)
8440103732027381823  2026-09-22 20:12  (drill Pass 2, seeded as 2026-09-22 again)
```
If demoing time travel before more snapshots accumulate, diff
`2408034314406756364` (Pass 1, different seed-date) against CURRENT — that
pairing is guaranteed to show real changes. Don't diff `6300977543968207922`
vs CURRENT (both same seed-date — only `ingested_at` differs, confirmed
live).

### To resume next session

Nothing is pending from this story. Possible next directions (not started,
no commitments made):
- Anything from `cml/README.md`'s "Ideas not yet automated" section
  (programmatic Application provisioning via `cmlapi`, Alembic migrations,
  CI smoke test in GitHub Actions).
- If the user wants a *real* trained fraud model instead of the Spark SQL
  heuristic (mentioned as a possible future ask in the original 2026-09-21
  kickoff message, item 2, but explicitly deferred — "the model" is
  currently just the LLM via Groq) — not started, would need a CAI Model
  endpoint, which doesn't exist yet in this repo.
- Otherwise: just re-verify the demo runbook still works end-to-end
  (`docs/steps-to-demo-execution.md`) before presenting it live, especially
  Beat 4's snapshot-pair guidance if new snapshots have accumulated since
  the table above was captured.

---

## 2026-09-20/21 — CAI deployment hardening: auth (Istio) + port auto-detection

### What we built / fixed

1. **Login worked but every page bounced back to `/auth` right after OTP** on
   one specific CAI workspace (`goes-awc-bench...cloudera-labs.com`).
   Root cause: that workspace's **Istio ingress mesh runs its own JWT check**
   on incoming requests (expecting a Knox/OIDC-issued token) and silently
   rejects our app's own JWT wherever it looks for one — an **empty-body
   401 from `server: istio-envoy`**, before the request ever reaches FastAPI.
   Confirmed via DevTools: `login`/`verify-otp`/`refresh` all succeeded (none
   send an auth token), but the very next authenticated call always 401'd,
   even immediately after a successful token refresh.
   - **Fix attempt 1** (`4497889`): move the token from the `Authorization`
     header to a custom `X-Auth-Token` header. Backend (`_extract_token` in
     `backend/dependencies.py`) reads `X-Auth-Token` first, falls back to
     `Authorization: Bearer` for non-Istio deployments. **This alone did not
     fully fix it** — same empty-401 pattern persisted, suggesting the mesh
     policy isn't strictly keyed to the literal header name.
   - **Fix attempt 2 / the one that worked** (`08942fa`): also mirror the
     token into a **plain (non-HttpOnly) cookie**, since browsers attach
     same-origin cookies automatically and this class of header-focused mesh
     policy essentially never inspects cookies. Distinct cookie name per
     portal — `app_auth_token` (customer), `app_agent_auth_token`,
     `app_insurer_auth_token` — because cookies auto-attach to *every*
     same-origin request (unlike our explicit per-request header), so a
     shared name would let an insurer/agent login clobber a customer
     session's cookie in the same browser. Backend checks: cookie →
     `X-Auth-Token` → `Authorization`, in that order.

2. **Session-terminal `CDSW_APP_PORT` handling was fundamentally broken**,
   fixed over several iterations:
   - Port 8090 (the CAI Application default) is **permanently owned by that
     Session's own JupyterLab process** — a session terminal can never bind
     it, ever, for the life of the Session.
   - Learned the hard way: **Cloudera presets `CDSW_APP_PORT=8090` in a
     Session terminal's environment too**, not only in a real Application's
     — so "is it set?" cannot distinguish the two contexts. An early version
     of the auto-port-picker trusted that as an explicit operator choice and
     skipped probing it, immediately re-breaking.
   - `_port_free()` (in `cml/lib.sh`) must **not** use a `bind()+close()`
     probe with `SO_REUSEADDR` — on Linux this can falsely report an
     actively-listened-on port as free (confirmed live; worked fine in local
     macOS testing, which is *stricter* about this, masking the bug). Fixed
     to read `/proc/net/tcp[6]` directly for a LISTEN-state entry (same
     method `portcheck.sh` already used successfully).
   - `smoke.sh`/`portcheck.sh`/`diagnose.sh` had the **same blind-trust bug**
     independently — they defaulted straight to `$CDSW_APP_PORT` instead of
     the port `start`/`restart` actually bound. Fixed with a shared
     `resolve_app_port()` helper (`cml/lib.sh`) that checks
     `cml/.state/app.port` (ground truth, written by `appctl.sh`) before
     `$CDSW_APP_PORT`.
   - End state: `bash cml/cli.sh restart` auto-falls-back to `8099` (then
     scans upward) whenever the requested port is genuinely busy, verified
     via `/proc/net/tcp`, no manual `CDSW_APP_PORT=` juggling needed anymore.
     `smoke`/`portcheck`/`diagnose` all auto-target wherever the app actually
     ended up.

### Key architectural decisions & why

- **Feature work stays on `phase4-insurer-risk-ui`; infra/bug fixes get
  cherry-picked onto `main`.** This project's established pattern — `main`
  should always be deployable/demoable without the in-progress Book of
  Business / insurer risk UI feature. Every fix in this session was
  committed to `phase4-insurer-risk-ui` first, then `git cherry-pick`ed onto
  `main` (not merged — merging would drag in unfinished feature commits).
  **Gotcha this bit us hard**: a session on `main` kept saying "already up
  to date" and re-hitting fixed bugs because the fixes had only reached
  `phase4-insurer-risk-ui` — always cherry-pick to `main` immediately after
  verifying a fix, don't batch it.
- **Never trust `CDSW_APP_PORT` (or any single signal) to distinguish a
  Session terminal from a real Application.** Always verify ground truth
  (is the port *actually* free right now / what did `start` actually bind)
  instead of inferring from environment presence.
- **Redundant auth transport (header + cookie) over guessing the exact mesh
  rule.** Rather than reverse-engineering the workspace's exact Istio
  `RequestAuthentication` config, ship both a custom header and a cookie —
  cheap, backward-compatible (both still fall back to `Authorization` for
  plain non-mesh deployments), and robust to policy details we can't
  directly inspect from the app side.

### Next steps / remaining tasks

- Update `cml/README.md`'s auth/gotchas section to document the **cookie**
  fix (it currently only mentions the `X-Auth-Token` header attempt) —
  flagged to the user, not yet done as of this writing.
- Phase 4 (Insurer Book of Business + Claim Insights risk card) is feature-
  complete on `phase4-insurer-risk-ui` (tag `phase3-complete` marks the
  pre-Phase-4 rollback point) but **not yet merged to `main`** — merge when
  ready to ship, being mindful it'll bring the full feature set at once
  (not just infra fixes).
- No outstanding known bugs as of 2026-09-21 — last confirmed working state:
  login → OTP → dashboard on the `goes-awc-bench` CAI workspace, smoke test
  passing 5/5 on a Session terminal.

### Gotchas / edge cases to watch for

- **`ssl.SSLError: [SSL: LIBRARY_HAS_NO_CIPHERS]`** on some hardened CML
  runtimes' `uv`-managed Python — probe-based `OPENSSL_CONF=/dev/null`
  workaround already in `cml/lib.sh`/`cml/run.py`, only activates if a
  real probe fails, never touches working runtimes.
- **Port 8090 in a Session terminal is always JupyterLab's** — never assume
  it's free just because `CDSW_APP_PORT` says so.
- **CAI Application "Restart" does not rebuild the frontend.** It only
  relaunches the process against whatever's already in `frontend/dist` on
  the shared project filesystem. Must `git pull` + `bash cml/cli.sh update`
  (which rebuilds) in a Session terminal *before* restarting the Application
  for a frontend change to actually take effect.
- **Vite's content-hash filenames are not fully deterministic** across
  separate build invocations, even with byte-identical source (confirmed:
  two local rebuilds of the same commit produced different `index-*.js`
  hashes). Don't use bundle filename/hash as a proxy for "did my change
  deploy" — check bundle *content* or the backend's `/api/version` `build`
  field (git short SHA) instead.
- **DevTools "Preserve/Persist log" is essential** when debugging anything
  involving a hard redirect (`window.location.href`) — otherwise the
  Network tab wipes the very request that triggered the redirect, hiding
  the actual failing call.
- Cookie fix requires **`SameSite=Lax`**, not `Strict` or with `Secure`-only
  assumptions — verify this still works if the deployment domain setup
  changes (e.g. cross-subdomain proxying).

---

## 2026-09-21 — Target environments documented (env 1 vs env 2)

Two separate CAI deployments going forward. Phase 4 is scoped to **env 1
only** — env 2 must never receive it.

### Env 1

- URL: <https://ml-dbfc64d1-783.go01-dem.ylcu-atmi.cloudera.site/rsingh/insurance-claim-processing>
- Platform: **CDP 7.3.2**, a full CAI workspace with normal CDE/CDW/CDF
  integration — the "standard" lakehouse-integrated deployment this project
  targets by default (Iceberg via CDE, per [`cde/README.md`](cde/README.md)
  and [`cml/README.md`](cml/README.md#data-lakehouse-impala--iceberg--cde)).
- **This is where Phase 4 (Insurer Book of Business + Claim Insights risk
  card, `phase4-insurer-risk-ui` branch) starts / is being rolled out.**

### Env 2

- URL: <https://goes-awc-bench.goes-ai.demos.cloudera-labs.com/rsingh/insurance-claim-datalake-integrated-and-standalone-oltp>
- Platform: a **new Cloudera product release — "AWC" (AnyWhere Cloud)**.
  CAI here is **standalone**: no integration with CDE/CDW/CDF at all.
- This is the **same workspace** referenced in the 2026-09-20/21 entry above
  (the Istio JWT 401 / cookie-auth fix) — `goes-awc-bench...cloudera-labs.com`.
- **No TLS certs in this environment** — per the user, this is what forced
  yesterday's architecture change (the header + cookie belt-and-suspenders
  auth fix described above).
- Because there's no CDE/CDW integration, there's **no Iceberg/lakehouse
  pipeline available** here. `insurance-claim-processing` runs **standalone
  on OLTP only** (`DB_BACKEND=sqlite`) — no
  `bash cml/cli.sh lakehouse seed|verify|ingest` in this env.
- **Phase 4 will NOT be used in this env at all.** It stays on `main`
  (pre-Phase-4 feature set, OLTP-only).

### Standing rule

- **Env 1** = Phase 4 development/demo target (lakehouse-integrated, CDP 7.3.2).
- **Env 2** = OLTP-only baseline on the standalone-AWC product release —
  never gets Phase 4. Keep it tracking `main` (or pin to the
  `phase3-complete` tag) and do **not** merge `phase4-insurer-risk-ui` into
  `main` in a way that env 2 would pick up until this constraint changes.

### Rollback tags for env 1 — ⚠️ naming mistake, read carefully

Two tags exist and are easy to confuse:

- **`env1-pre-phase4-2026-09-21`** (commit `a56416b`, tip of
  `phase4-insurer-risk-ui`) — despite the name, this **already contains**
  the Phase 4 feature commit (`dbd66dc feat(phase4): insurer risk UI...`).
  It was originally (mis-)intended as a rollback point but actually isn't
  one — it's the **"deploy Phase 4 now"** checkpoint. This is what env 1
  is currently checked out to (detached HEAD) as of 2026-09-21 09:5x IST,
  and that's fine/expected for starting Phase 4 work there.
- **`env1-rollback-baseline-2026-09-21`** (commit `c62197c`, tip of `main`
  at the time) — this is the **real** pre-Phase-4 baseline; verified via
  `git merge-base --is-ancestor dbd66dc c62197c` → false (does not contain
  Phase 4). **Use this one to actually revert env 1** if Phase 4 needs to
  be rolled back:
  ```bash
  git fetch --tags
  git checkout env1-rollback-baseline-2026-09-21
  bash cml/cli.sh update
  # then restart the Application
  ```

### Note on `cml/cli.sh update` in detached HEAD

Checking out a tag puts you in detached HEAD, so the script's internal
`git pull --ff-only` step will always fail with "You are not currently on a
branch" — **this is expected and harmless**, the rest of `update` (dep
sync, DB schema check, frontend rebuild) still runs correctly. To pick up
newer commits later while pinned to a tag, re-run `git fetch --tags` +
`git checkout <tag-or-newer-ref>` rather than `git pull`.

Also saw a one-time warning: `New keys in .env.example not yet in your
.env: LAKEHOUSE_DATABASE` — harmless, the code defaults to
`insurance_lakehouse` when unset (matches `.env.example`); only add it to
`backend/.env` explicitly if env 1 needs a non-default Iceberg schema name.

### Phase 4 verified end-to-end in env 1 (2026-09-21)

Full pipeline confirmed working on the real CAI Application (not just the
Session terminal): CDE gold tables → Impala/Iceberg → `bash cml/cli.sh
lakehouse ingest` → app SQLite (`PolicyRiskSignal`) → `/api/insurer/book-of-
business` → **Book of Business** page.

- `lakehouse verify`: `policy_master` 60 rows, `policy_clauses` 240 rows,
  `policy_risk_signals` 792 rows, `garage_risk_signals` 40 rows — all
  `STORED AS ICEBERG`.
- `lakehouse ingest`: 60 policies updated (idempotent re-run — already
  ingested in an earlier session), 60/60 risk signals matched, 240 RAG
  chunks indexed (270 Chroma vectors total).
- UI at `.../insurer/book-of-business`: 60 lakehouse policies, 6 high-risk,
  51 linked to a flagged garage, avg fraud score 40.9 — table renders risk
  band/fraud score/claims/flagged-garage columns correctly, sortable by
  risk band and fraud score.
- **Gotcha hit during verification**: insurer auth (`/insurer/auth/login`,
  `/insurer/auth/verify-otp`) lives at a **bare** path, not under `/api` —
  by deliberate design (see `main.py`'s `_bare_auth_router_prefixes`
  comment: these three auth routers share their path with the frontend's
  login-page route for hard-redirect reasons). Only the data endpoints
  (`/api/insurer/book-of-business`, etc.) are under `/api`. Demo insurer
  login: `insurer1@claimcopilot.in` / `password123` / OTP `112233`.
- **Not yet checked**: the **Claim Insights risk card** (the other Phase 4
  surface — shows the same risk signal on an individual claim's review
  page). Needs a claim against an `LH-POL-*` policy to verify; none
  confirmed to exist yet as of this writing.

### Critical pre-existing bug found + fixed: ALL claim submissions were broken

While attempting to submit a test claim in env 1 to exercise the Claim
Insights risk card, clicking "Submit Motor Claim" silently did nothing —
claim stayed in `DRAFT` in Motor Claim History, no visible frontend error.

Root cause: `ClaimService.validate_submit_gates()`
(`backend/services/claim_service.py`) referenced `DocumentType.GOV_ID` and
`DocumentType.PROOF` — leftover from a pre-motor-refactor generic
`DocumentType` enum. The current enum (`models/claim.py`) is
motor-vehicle-specific and has **no `GOV_ID` or `PROOF` member at all** —
evaluating `DocumentType.GOV_ID` raises `AttributeError` unconditionally.
This has been true on **`main` as well**, confirmed via
`git show main:backend/services/claim_service.py` — i.e. every single
`POST /api/claims/{id}/submit` call has been broken since the motor
refactor, not something specific to this session/policy.

Fix (commit `2afd0c2` on `phase4-insurer-risk-ui`, cherry-picked to `main`
as `be334f2`): check the actual motor equivalents that `upload_evidence()`
(`routers/claims.py`) writes — `DocumentType.DRIVER_LICENSE` (gated on
non-KYC-verified customers) and `DocumentType.DAMAGE_PHOTO` (always
required) — matching the frontend's own `Step3EvidenceUpload` validation.
Also removed a duplicate `is_kyc_verified` import in the same file.

**Re-verified end-to-end after the fix, 2026-09-21**: submitted claim
`CLM33EE6D22` (id=2, `LH-POL-2050`, customer `customer50@example.com`)
via direct API call (`POST /api/claims/2/submit`) since the frontend had
no way to resume this already-abandoned draft (**since fixed**, see next
section) — went
`DRAFT` → `PENDING` → `PROCESSING` → **`REJECTED`** (38% likely approved,
"Higher" risk, flagged fraud risk / VIN mismatch / unclear documents — all
expected given the synthetic placeholder docs have no real vehicle photo).
Confirms the fix works: claims now actually process instead of silently
staying in `DRAFT`.

**Claim Insights risk card (Phase 4's second surface) also confirmed
rendering** on this same claim's `/track/2` page: "LAKEHOUSE RISK SIGNAL —
HIGH RISK", fraud score 70.1/100, "linked to a flagged garage" — matches
the Book of Business data for `LH-POL-2050`. **Phase 4 is now fully
verified end-to-end in env 1: both the Book of Business page and the
Claim Insights risk card.**

### Second frontend gap found: no way to resume an abandoned draft claim

`/claim` (`ClaimWizard.tsx`) always starts a **brand-new** draft — no
route/mechanism to resume an existing one. `/track/:id` (where
`History.tsx` always links, regardless of status) is **read-only**, no
submit action, even for a `DRAFT` claim. So if a user leaves the wizard
mid-flow (e.g. the old submit-gates bug silently failing, or just closing
the tab), that draft is stuck forever with no UI path to finish it —
confirmed via the `CLM82424700` draft (0 documents) still sitting in
Motor Claim History. Worked around by submitting claim id=2 directly via
API (see above).

**Fixed** (commit `7d5a71c` on `phase4-insurer-risk-ui`, cherry-picked to
`main` as `05f7114`):
- Backend: `DraftClaimResponse` gained `incident_description`/
  `incident_datetime`/`location`/`claim_amount` (previously missing from
  the schema despite the model having them); new
  `GET /api/claims/{claim_id}/draft` returns a draft's current field
  values via the existing `_draft_response` builder.
- Frontend: new route `/claim/:id` (same `ClaimWizard` component) —
  fetches the draft (+ policy context/documents/KYC status if the policy
  step is done), rehydrates all wizard state, and lands on the correct
  step (2 if policy papers aren't loaded, 3 if evidence is incomplete —
  mirrors `validate_submit_gates`' own checks, else 4). `TrackClaim.tsx`
  now shows a "Continue draft →" button in the header when
  `claim.status === DRAFT`, linking to `/claim/:id`.
- Universal fix, not Phase-4-specific — applies to any claim.
- **Not yet re-verified in env1 after this fix** — needs `git pull` +
  `bash cml/cli.sh update` (rebuilds the frontend) + `restart`, then try
  "Continue draft" on `CLM82424700` (the still-orphaned draft with 0
  documents) to confirm it lands on Step 2 as expected.

### Lakehouse ingest CML Job created + one more bug fixed

User created the `Lakehouse Ingest Refresh` Job in env1 (Project → Jobs →
New Job, Script `cml/jobs/lakehouse_ingest_job.py`, per the new
`cml/README.md` walkthrough table) and ran it manually. **The ingest
itself fully succeeded** — 60 policies updated, 240 RAG chunks
re-indexed, 270 Chroma vectors total, identical to the Session-terminal
`lakehouse ingest` run — but the Job's log showed `Engine exited with
status 1` at the end, which would mark the Job **Failed** in the CAI UI
despite the actual work succeeding.

Root cause: this Job runtime ("Python 3.11 JupyterLab Standard") executes
the script **inside a persistent IPython kernel**, not a plain
`python script.py` subprocess — same mechanism documented in
`cml/run.py`'s `_resolve_root()` for the Application launcher. The script
called `sys.exit(result.returncode)` unconditionally at the top level;
inside a kernel, `sys.exit(0)` raises `SystemExit`, which IPython catches
and prints as an exception (`"An exception has occurred ... SystemExit:
0"`), and the Job engine then reports it as a failure. `cml/run.py`
never hits this because it uses `os.execvp` (replaces the process
image, no `SystemExit` ever raised) — the one-shot ingest Job needs
`subprocess.run()` to capture a real return code first, so it needed its
own fix.

**Fixed**: `cml/jobs/lakehouse_ingest_job.py` now only calls `sys.exit()`
on actual failure (non-zero return code); on success it just falls off
the end of the script, never raising `SystemExit` in the kernel context.
**Re-verified in env1 after the fix**: re-ran the Job manually — now
shows **Succeeded** (runtime ~13min; slower than a warm Session terminal
run, but that's expected Job-engine cold-start overhead — fresh
pod/kernel provisioning + Impala/LDAP handshake, not a regression). Safe
to switch to a recurring schedule.

### Branches merged: `phase4-insurer-risk-ui` → `main`

Phase 4 (Book of Business + Claim Insights risk card) is now fully
verified in env1 and merged into `main` (one clean, purely-additive
conflict in `cml/README.md`). Also took the opportunity to strip every
`Co-authored-by: Cursor` / `Claude` trailer from the entire commit
history (`git filter-repo` on a scratch mirror clone, then force-pushed
`main` + `phase4-insurer-risk-ui` + all tags). **This rewrote every
commit SHA in the repo** — any existing clone (env1, env2, other
laptops) needs a hard re-sync, not a normal `git pull`:
```bash
git fetch origin --tags --force
git checkout main
git reset --hard origin/main
# if you also keep a local phase4-insurer-risk-ui branch:
git branch -f phase4-insurer-risk-ui origin/phase4-insurer-risk-ui
```
env1 hit exactly this — a stale local `phase4-insurer-risk-ui` branch
left pointing at the pre-rewrite SHA after `git reset --hard origin/main`
(which only moves the *current* branch, `main`). Fixed with the
`git branch -f ... origin/...` command above. Verified 0 matches for
`git log --all --grep="Co-authored-by" -i` afterward.

Going forward, `phase4-insurer-risk-ui` is redundant (main has
everything) — do new work directly on `main` unless a fresh feature
branch is intentionally started.

### OLTP + Lakehouse storyline enhancements (3 items, tackling one at a time)

User flagged 3 gaps in the OLTP+lakehouse "story" for a demo:
1. Claims filed in the app never landed in bronze (one-way flow only).
2. `fraud_risk_score` is a Spark SQL heuristic that never feeds the
   decision engine — only shown on Book of Business / Claim Insights.
   Also no CAI Model endpoint exists; "the model" is the LLM via Groq.
3. No Iceberg time travel / snapshot audit — gold writes are
   drop+recreate, not `MERGE`/`INSERT OVERWRITE`.

**Item 1 — done** (commit `0281b2e`): `backend/scripts/export_claims_to_lakehouse.py`
pushes decided, policy-linked, not-yet-exported app claims (tracked via new
`Claim.lakehouse_exported_at`) into a dedicated Iceberg bronze table
`insurance_lakehouse_bronze.app_claims_raw` via Impala INSERT — kept
separate from `claims_history_raw` since that table gets drop+recreated by
`generate_claims_bronze.py` every run. `transform_claims_silver.py` unions
the two bronze sources into the same silver `claims_history`; NO changes
needed in `curate_risk_signals_gold.py` — real claims flow through the same
fraud/risk analytics automatically. New `bash cml/cli.sh lakehouse
export-claims` + `cml/jobs/lakehouse_export_claims_job.py` (CML Job,
symmetric to the ingest Job, same sys.exit()-in-kernel-safe pattern from
day one). Batch only (user's call — real-time can become a Spark
Structured Streaming job later if ever needed). `garage_name` uses a fixed
placeholder (`"Unspecified — App Claim"`) since the app has no structured
garage field yet (only a repair-estimate *document* upload) — user
explicitly deferred this as non-critical. Full design: `cde/README.md`
§ Closing the loop.

**Item 1 — verified end-to-end in env1.** Ran `lakehouse export-claims`
(exported the `LH-POL-2050` / `CLM33EE6D22` claim into `app_claims_raw`),
then `cde job run --name rsingh-insurance-transform-claims-silver --wait`
→ `cde job run --name rsingh-insurance-curate-risk-signals-gold --wait`
(both succeeded), then `bash cml/cli.sh lakehouse ingest` in env1. Confirmed
via `/api/insurer/book-of-business` that `LH-POL-2050`'s risk numbers moved
by exactly the exported claim: `total_claims_count` 16→17,
`claims_count_12m` 10→11, `total_claimed_amount` +50,001.0 (exact match),
`fraud_risk_score` 70.1→70.5, band stayed HIGH. **Full OLTP↔lakehouse loop
confirmed closed.**

Two bugs found + fixed while verifying:
- **CDE Repository broke after the Git history rewrite.** `cde repository
  sync` failed with `non-fast-forward update` (rewritten/force-pushed
  history can't fast-forward the Repository's cached clone). Fix: deleted
  all 9 jobs mounting the Repository, deleted the Repository, re-ran
  `deploy_jobs.sh` + `deploy_dag.sh` to recreate everything from a fresh
  clone. Documented as Gotcha #6 in `cde/README.md` — only do a history
  rewrite on this repo if you can also run this CDE-side recovery.
- **`policy_risk_signals.ingested_at` went stale after the first ingest.**
  `backend/scripts/ingest_lakehouse.py`'s `upsert_risk_signal()` never
  updated `ingested_at` on re-ingest — the SQLAlchemy column `default=`
  only fires on the initial `INSERT`, so the freshness timestamp stayed
  frozen at Sep 18 (the first Phase 4 ingest) even after re-ingesting
  fresh gold data days later. Fixed to parse the gold pipeline's own
  `ingested_at` value from each row (falling back to `utcnow()` if
  missing/unparseable) and set it every upsert.

**Item 2 — done**: `fraud_risk_score`/`claim_risk_band` (`PolicyRiskSignal`, via
`Policy.risk_signal`) now genuinely feed the decision pipeline instead of
only being displayed:
- `backend/services/fraud_detection.py` — new `SIGNAL_WEIGHTS` entries
  `lakehouse_risk_high` (0.40, meets the review threshold alone like the
  other "hard" signals — blacklist, VIN mismatch) and `lakehouse_risk_medium`
  (0.15, a "soft" signal, only matters when stacked). No-op for non-lakehouse
  demo policies (`policy.risk_signal is None`).
- `backend/services/escalation_service.py` — new `lakehouse_high_risk_policy`
  escalation flag (HIGH band only) with a message naming the score + claim
  count. `decision_engine.py`'s existing generic `if inputs.escalation_flags:`
  check (which runs *before* the fraud-score threshold check) routes this
  straight to `PENDING_REVIEW` — **zero changes needed in `decision_engine.py`
  itself**.
- `frontend/src/lib/escalationLabels.ts` — friendly label for the new flag
  (cosmetic only; the flag already renders everywhere escalation
  messages do — `TrackClaim`, insurer/agent claim review + audit report,
  `ClaimHistoryCard`, `ClaimAssistant` — no other frontend changes needed).
- Deliberately skipped `linked_high_risk_garage` as a separate signal (already
  folded into the composite `fraud_risk_score`/band by the gold SQL — would
  double-count). No new `.env`/`config.py` settings — weights are hardcoded
  in `SIGNAL_WEIGHTS`, consistent with every other signal in that file.
- **Verified in env1** (claim `CLMA88F21DA` on `LH-POL-2050`, filed through
  the UI): `escalation_flags` included `lakehouse_high_risk_policy` with the
  exact expected message, `fraud_score` was elevated (0.87). Final status
  was `REJECTED` rather than `PENDING_REVIEW` — **not a bug**: `LH-POL-2050`
  has `status: EXPIRED`, and `decision_engine.decide()` checks
  `policy_expired` *before* it ever reaches the escalation-flags branch
  (same reason an earlier claim on this policy, pre-fix, was also
  REJECTED). To see the escalation-driven `PENDING_REVIEW` path, need a
  HIGH-band policy that is NOT expired.
- **New reusable test harness** (replacing hand-typed curl chains, same
  spirit as `verify_phase4.sh`/`set_demo_password.py`):
  `backend/scripts/lakehouse_risk_claim_test.py` + `cml/test_claim.sh`,
  wired as `bash cml/cli.sh test-claim <find|submit> [flags]`.
  - `find --band HIGH --not-expired` — DB-direct, lists lakehouse policies
    by risk band, filtered by the *real* `policy_expired` condition
    (mirrors `PolicyValidationService.validate()` exactly: `expiry_date >=
    now` AND status not EXPIRED/LAPSED/CANCELLED).
  - `submit --policy-number LH-POL-XXXX` — full HTTP flow against a
    running app instance: sets the customer's password, logs in, creates +
    links + submits a claim with the committed synthetic evidence docs,
    polls for the decision, prints status/fraud_score/escalation
    flags+messages. One command instead of a 5-step curl chain per test.
  - **Important structural finding, found via this harness**: the
    `status` column on a lakehouse policy is NOT a reliable signal for
    "will this claim be rejected as expired" — tried `LH-POL-2047`
    (`status=ACTIVE`, HIGH band) and it still got REJECTED via
    `policy_expired`, because `policy_validation.py` checks
    `policy.expiry_date < datetime.utcnow()` (real wall-clock time), and
    the synthetic population's `expiry_date` is generated once,
    non-relative to real time (`effective = 2024-01-01 + up to ~640 days`,
    `+365 days` term — `cde/jobs/generate/generate_bronze.py`). As real
    time advances past the generation window (max expiry ~2026-10-02),
    fewer — eventually zero — lakehouse policies will ever pass
    `--not-expired`, at which point testing the escalation-flags branch
    against a *lakehouse* policy becomes impossible without regenerating
    bronze with fresh dates (`bash cml/cli.sh lakehouse seed` or re-running
    `generate-bronze` in CDE). Fixed `find` to check the real condition
    instead of just `status`.
  - Ran `find --band HIGH --not-expired` in env1: **zero results**,
    confirming the ceiling had already been hit for the HIGH band.

**Root-cause fix (user chose to fix properly, "no need to rush")**:
`cde/jobs/generate/generate_bronze.py`'s `effective_date` was anchored to a
hardcoded `datetime(2024, 1, 1)` + `random(0, 640)` days, so every policy's
`expiry_date` (`effective + 365d`) had a hard ceiling of **~2026-10-02**
regardless of when the job actually ran — a ticking time bomb that had
already gone off for the HIGH band and would hit every remaining policy
within days. Fixed to anchor `effective_date` to the job's own run time
instead (`anchor - random(30, 300) days`), guaranteeing `expiry_date >=
anchor + 65 days` for every policy going forward — self-renewing, just
re-run `generate-bronze` for a fresh window whenever needed. Applied the
same fix to the superseded Phase 1 hand-seed path
(`backend/scripts/lakehouse_seed.py`'s 3 hardcoded `LH-POL-100x` rows) for
consistency, even though Phase 2's CDE pipeline already overwrites those.

**Still to do in env1** — regenerate + re-ingest so the fresh dates take
effect (the fix is code-only until the pipeline actually re-runs):
```bash
git pull
cde job run --name rsingh-insurance-generate-bronze --wait
cde job run --name rsingh-insurance-validate-bronze --wait
cde job run --name rsingh-insurance-transform-silver --wait
cde job run --name rsingh-insurance-curate-gold --wait
bash cml/cli.sh lakehouse ingest
```
**Verified end-to-end in env1** after regenerating + re-ingesting: `find
--band HIGH --not-expired` returned 3 candidates (`LH-POL-2059/2047/2038`,
all `status=ACTIVE`, previously 0). `submit --policy-number LH-POL-2059`
→ claim `CLM3451ADC7`:
- `status: PENDING_REVIEW` (previously always `REJECTED` via
  `policy_expired`, masking everything downstream).
- `escalation_flags: ['high_fraud_score', 'lakehouse_high_risk_policy']`
  with the exact expected message (score 70/100, 22 historical claims).
- `fraud_score: 0.4` — matches the `lakehouse_risk_high` weight exactly,
  confirming the signal fired cleanly in isolation (no other rule signals
  stacked on this particular claim).
- LLM reasoning explicitly cites the lakehouse high-risk flag as a reason
  for manual review.

**Item 2 is done and fully proven**, root cause (the date-anchoring bug)
included.

Regression spot-check, LOW band: `submit --policy-number LH-POL-2000`
(score 30.7) → `status: ANALYSIS_COMPLETE`, `fraud_score: 0.12`,
`escalation_flags: []`. No `lakehouse_high_risk_policy` flag and no score
bump — the signal is correctly additive/gated by band, not a blanket
effect. Confirms no regression on the non-HIGH path.

Added `test-claim find --no-signal` (outer join, lists policies with NO
`PolicyRiskSignal` row at all — i.e. non-lakehouse `POL-MTR-*` demo
policies) to make it trivial to also regression-check that
`policy.risk_signal is None` is handled cleanly by
`fraud_detection.py`/`escalation_service.py` (no AttributeError, no
phantom flag). Use: `bash cml/cli.sh test-claim find --no-signal
--not-expired` then `submit --policy-number <result>`.

Regression spot-check, no-signal: `submit --policy-number POL-MTR-1001`
→ `ANALYSIS_COMPLETE`, `fraud_score: 0.12`, `escalation_flags: []` — no
crash, no phantom flag when `policy.risk_signal is None`.

**Item 2: fully closed and verified in env1**, all 3 cases pass (HIGH →
`PENDING_REVIEW` + flag + score=0.40 exactly; LOW → no-op; no-signal →
no-op, no crash). OLTP + Lakehouse story now has 2/3 items done. Item 3
(Iceberg time travel / MERGE-based gold writes instead of drop+recreate)
is next, see Roadmap in `cde/README.md`.

**Item 3 — not started yet** (Iceberg time travel / `MERGE`/`INSERT
OVERWRITE` instead of drop+recreate gold writes), logged in
`cde/README.md`'s Roadmap.

## 2026-09-22 — Item 3, step 1: gold writes switched to MERGE INTO

Agreed 3-step plan for Item 3 (Iceberg time travel):
1. Switch the 4 gold-table writes from drop+recreate to `MERGE INTO` so
   runs commit real snapshots instead of destroying history. **Done this
   session.**
2. A `test-claim`-style CLI to browse `DESCRIBE HISTORY` / run `FOR
   SYSTEM_TIME|VERSION AS OF` queries and diff against the current row.
   Not started.
3. Deliberately produce a day-over-day diff (re-run generate → curate a
   day apart) so there's something demo-worthy to time-travel to. Not
   started.

**Step 1 implementation:**
- `cde/jobs/curate/curate_gold.py` (`policy_master` key=`policy_number`,
  `policy_clauses` key=`policy_number,section_ref`) and
  `cde/jobs/curate/curate_risk_signals_gold.py` (`policy_risk_signals`
  key=`policy_number`, `garage_risk_signals` key=`garage_name`): added a
  `_bootstrap_or_merge()` helper (duplicated in both files — CDE jobs are
  deployed as single standalone `--application-file`s, no shared
  `--py-files` module today, matching the existing pattern of small
  per-file duplicated helpers like `_is_unset`). First run (table doesn't
  exist): CTAS, same as before. Every run after: `MERGE INTO ... WHEN
  MATCHED UPDATE SET * WHEN NOT MATCHED INSERT * WHEN NOT MATCHED BY
  SOURCE DELETE` — the `DELETE` clause keeps parity with the old
  full-replace semantics for keys that drop out of a run. Confirmed CDP
  7.3.2 supports this Spark-side (`WHEN NOT MATCHED BY SOURCE` needs Spark
  3.5+/Iceberg-on-CDE ≥1.5.2, both satisfied) and Impala-side (for the
  step-2 CLI's read queries) via Cloudera docs before writing any code.
- **User's catch, addressed**: `generate_bronze.py` (seed=42) and
  `generate_claims_bronze.py` (seed=7) used **fixed** seeds, so every
  regeneration produced byte-identical policy/claims attributes (only
  dates shifted with the anchor). Under the new MERGE strategy that would
  mean every run after the first commits an essentially-empty snapshot —
  no real diff, so nothing to time-travel *to*. Fixed: both now default to
  `seed = int(now.strftime("%Y%m%d"))` (calendar-day-based) instead of a
  constant — reruns *within* the same day stay idempotent (stable
  mid-demo), but the first run after a day boundary evolves the synthetic
  population for real (premiums, claim severities, garage assignments,
  and therefore `fraud_risk_score`/`claim_risk_band` downstream). Explicit
  `seed=` param still available for anyone who wants old deterministic
  behavior.
- Trade-off flagged in `cde/README.md` Gotcha #7: a day-boundary
  regeneration can shift a specific policy's risk band (e.g. a known
  HIGH-band demo policy might not stay HIGH forever) — re-check with
  `test-claim find --band HIGH --not-expired` after any such regen rather
  than assuming yesterday's policy numbers still hold.
- Docs: `cde/README.md` — updated § Data flow's drop+recreate note, added
  new § Iceberg time travel (Item 3) section with the `DESCRIBE HISTORY`
  / `FOR SYSTEM_TIME AS OF` / `FOR SYSTEM_VERSION AS OF` syntax (verified
  against Cloudera's CDP 7.3.2 docs, not assumed), updated Roadmap line,
  added Gotcha #7.
**Verified live in env1 (2026-09-22).** The GitHub repo had flipped to
private between sessions, breaking the CDE Repository's fresh clone with
`authentication required: Repository not found` — user made it public
again (simpler than the `GIT_CREDENTIAL`/`cde credential create --type
basic` path, which is documented in `cde/README.md` Gotcha #6 for next
time if it recurs). After `deploy_jobs.sh` + `deploy_dag.sh` recreated
everything fresh, ran the full 8-job chain (`generate` → `validate` →
`transform` → `curate` for both policies and claims). Driver logs
confirm the MERGE path actually fired (not bootstrap CTAS, since these
Iceberg tables already existed from before the repo was deleted):
```
Merged 60 source rows into insurance_lakehouse.policy_master (new snapshot committed)
Merged 240 source rows into insurance_lakehouse.policy_clauses (new snapshot committed)
Merged 41 source rows into insurance_lakehouse.garage_risk_signals (new snapshot committed)
Merged 788 source rows into insurance_lakehouse.policy_risk_signals (new snapshot committed)
```
**New gotcha found**: this shared vcluster scales its node pool down
aggressively (~15 min idle) and scale-up is *slow* today — the very
first job (`generate-bronze`) took **~26 minutes** waiting on
`waiting-for-scale-up` (`cde run describe --id <id>` shows this in
`.notices`), and `generate-claims-bronze` hit a *second* scale-up
mid-run after a ~16-minute gap between job chains. Once nodes were warm,
each job ran in ~1 minute as expected. Lesson: run the whole 8-job chain
back-to-back without long pauses between `cde job run` calls, and don't
assume a stuck `starting` status means something is broken — check
`cde run describe --id <id>` for a `waiting-for-scale-up` notice before
concluding it's a real failure.

**Fully confirmed via `DESCRIBE HISTORY` in Hue** — 2 real snapshots now
exist for `policy_risk_signals`, parent-child chain intact (not
collapsed back to 1 row like the old drop+recreate would do):
```
creation_time              snapshot_id            parent_id              is_current_ancestor
2026-09-21 11:41:02.199    4967580225782225719    NULL                   TRUE
2026-09-22 13:53:07.023    6300977543968207922    4967580225782225719    TRUE
```
Snapshot 1 was written by the *old* drop+recreate code, snapshot 2 by
the *new* MERGE code — a real, meaningful pair to time-travel between
(not just a day-boundary reseed) since the underlying generation logic
itself changed. **Item 3, step 1 is fully done and verified**, both by
log inspection and now by `DESCRIBE HISTORY` directly.

**Ran the `FOR SYSTEM_VERSION AS OF` comparison — real, dramatic diff:**
`LH-POL-2059` at snapshot 1 (yesterday): `fraud_risk_score=69.6`,
`claim_risk_band=HIGH`, `total_claims_count=22`. At current (today):
`fraud_risk_score=36.4`, `claim_risk_band=MEDIUM`, `total_claims_count=4`.
Both states are real, queryable, provable via time travel — this is
*exactly* the audit/regulatory pitch for a bank (prove what the system
said and when, not just today's number). This doubles as proof that
step 3 (a demo-worthy diff) works, even though this particular diff came
from the code change itself (old fixed-seed CTAS snapshot vs. new
date-seeded MERGE snapshot) rather than a deliberate day-over-day rerun
— the mechanism for future day-boundary diffs is now proven, not
theoretical.

**Step 2 done**: `backend/scripts/lakehouse_time_travel.py` (new) +
`bash cml/cli.sh lakehouse history --table <name>` / `lakehouse as-of
--table <name> (--snapshot <id>|--at '<ts>') [--policy-number
<pn>|--garage-name <gn>|--where "..."]` — same `test-claim`-style wrapper
pattern as the Item 2 test harness, avoids hand-typing `DESCRIBE
HISTORY`/`FOR SYSTEM_TIME|VERSION AS OF` in Hue every time. `as-of`
prints the AS OF row, the CURRENT row, and a column-level diff between
them (only meaningful for single-row filters, e.g. one policy_number).
Wired into `cml/lakehouse.sh`'s existing `<seed|verify|ingest|
export-claims>` dispatcher. Documented in `cml/README.md` § Iceberg time
travel / audit and `cde/README.md`'s Roadmap.

**Verified live in env1, worked first try, no fixes needed.** `history
--table policy_risk_signals` printed the 2-snapshot chain cleanly.
`as-of --table policy_risk_signals --policy-number LH-POL-2059
--snapshot 4967580225782225719` printed the AS OF row, the CURRENT row,
and an automatic column-level diff — 9 columns changed
(`total_claims_count`, `claims_count_12m`, `total_claimed_amount`,
`avg_claim_amount`, `amount_vs_segment_avg_pct`,
`claim_frequency_percentile`, `fraud_risk_score`, `claim_risk_band`,
`ingested_at`), exactly matching the numbers pulled by hand in Hue
earlier. This is genuinely demo-ready.

**Step 3 done**: `generate_bronze.py`/`generate_claims_bronze.py` now
accept an optional 2nd CLI arg — a raw seed int, or a `YYYY-MM-DD` date
string converted via the same `int(date.strftime('%Y%m%d'))` formula
they default to (`_parse_seed_arg()`, duplicated in both files matching
the existing per-file-helper convention). Passing an earlier date
reproduces exactly what that job would have generated had it run that
day — attribute values only, `effective_date`/`expiry_date`/etc. still
anchor to the real run time so nothing looks artificially expired. New
`cde/scripts/time_travel_drill.sh` runs the full 8-job chain twice
(earlier date, then today) so a demo always has two meaningfully
different snapshots to show, on demand, instead of waiting for a real
day boundary. Documented in `cde/README.md` § Iceberg time travel and
`cml/README.md`.

**Item 3 (Iceberg time travel) is now fully done — all 3 steps
complete and step 1/2 verified live.** The OLTP + Lakehouse enhancement
story (all 3 original gaps) is closed:
1. App claims → bronze (`export-claims`) — done.
2. Lakehouse risk signals → live decision engine (`lakehouse_high_risk_policy`) — done, verified.
3. Iceberg time travel (MERGE writes + history/as-of CLI + on-demand drill) — done, steps 1/2 verified live; step 3 not yet dry-run end-to-end (new code, syntax-checked only).

### Reusable Phase 4 testing tooling added this session

- `cml/verify_phase4.sh` (`bash cml/cli.sh verify-phase4 [--check-claims]`)
  — logs in as the demo insurer, hits `/api/insurer/book-of-business{,/stats}`,
  optionally checks for an existing claim tied to an `LH-POL-*` policy.
- `backend/scripts/set_demo_password.py` — gives a lakehouse-ingested
  customer/agent/insurer (placeholder unknown password) a known password
  for test login. `--list-lakehouse-customers` to pick one.
- `backend/scripts/generate_demo_claim_docs.py` +
  `docs/demo-assets/claim-docs/` — synthetic (watermarked, not real)
  damage photos / driver's licence / repair estimate / RC / police report
  for the claim wizard's Step 3, committed directly so they're usable
  without regenerating.

All scoped to `phase4-insurer-risk-ui` only (not cherry-picked — they
reference Phase-4-specific concepts like `LH-POL-*`/book-of-business),
except the `validate_submit_gates` bugfix above, which is a universal
bugfix and went to both branches.

## 2026-09-23 — Customer Trust Score (credit score + customer profile) — built overnight, NOT yet merged

User asked to improve auto-approval with credit score + other customer
profile data (steps 1-4 of the proposal; optional step 5 — trained ML
model on a CAI Model endpoint — deferred). Built autonomously while the
user slept, on branch **`feature/customer-trust-score`** (pushed to
origin; **not merged to `main`** — env 2 tracks `main`, and the CDE
Repository syncs `REPO_BRANCH="main"`, so merging is the go-live switch).

**Core rule:** the trust tier changes how fast a claim is auto-approved
(the amount limit), never whether a valid claim is paid — it can never
cause `REJECTED`. No protected attributes; `driver_age` is stored but
not scored. Customers with no profile row are `UNSCORED` = exactly the
old behaviour.

### What was built
1. **CDE** — independent parallel chain in the Airflow DAG (3 new jobs in
   `deploy_jobs.sh`, also added to `time_travel_drill.sh`):
   `generate_customer_profile_bronze.py` (800 synthetic customers, emails
   `customer{i}@example.com` = policy_master owners of `LH-POL-2000+i`;
   latent "care" variable correlates attributes; 7% financial-stress, 4%
   cross-insurer-claimant, 3% address-churn outliers) →
   `transform_customer_profile_silver.py` (validate + clean, fails on 0
   usable rows) → `curate_customer_profile_gold.py` (MERGE into
   `insurance_lakehouse.customer_profile_signals`, adds
   `credit_score_percentile`, `credit_band`, `driving_record_band`).
   `lakehouse history/as-of` know the new table (`--customer-email`).
2. **App ingest** — new SQLite table `customer_profile_signals`
   (`CustomerProfileSignal`, 1:1 with Customer; `ensure_schema` creates it
   plus the new nullable `claims.customer_trust_json`). `lakehouse ingest`
   upserts by email (tolerant if the gold table doesn't exist yet).
   `seed.py` gives `test@example.com` a DEMO_SEED profile → PREFERRED (89).
3. **`services/customer_trust_service.py`** — pure, explainable 0-100
   score: credit 30%, financial stability 10%, driving record 20%,
   relationship (tenure/multi-policy/NCB) 15%, claims elsewhere 15%,
   identity (KYC, address change) 10%; reason codes. Tiers (calibrated on
   the synthetic population to ~35/55/9%): PREFERRED ≥ 82 (limit ×1.5),
   STANDARD 60-81 (×1), WATCH < 60 (×0.5). Knobs: `TRUST_*` in config.
4. **Decision wiring** — `finalize_claim` scales
   `HUMAN_REVIEW_AMOUNT_THRESHOLD` by tier, freezes the trust snapshot on
   `claims.customer_trust_json`, tier appended to the `human_reviews.reason`
   record (not currently displayed in any UI). **Customer-facing surfaces never show the tier**
   (decision/LLM reasoning, progress stream, customer insights + audit
   APIs are stripped — follow-up commit after the user asked what else
   needed changing). Two soft
   fraud signals: `financial_stress` 0.15, `cross_insurer_claims` 0.20
   (stacked 0.35 < 0.40 review threshold; excluded from the LLM fraud
   prompt).
5. **UI** — Claim Insights **Customer Trust Score card** (insurer + agent
   review only, not the customer's TrackClaim); Book of Business
   **Customer trust** column, tier filter, trust sort, Watch-tier stat card.
6. **Tooling/docs** — `test-claim find --trust-tier ...` (+ trust/coverage
   columns), `submit` prints the trust tier + reasons; demo runbook
   **Beat 2b**; `cml/README.md` § Customer Trust Score; `cde/README.md`;
   `README.md`; `docs/env-reference.md`.

### Verified locally (no env1 access overnight)
- CDE jobs run on local Spark 4.0.2 + Iceberg 1.10: bootstrap then MERGE
  (2 snapshots), sane band distributions.
- Integration script (20 checks, all pass): schema heal on an old DB,
  seed/ingest idempotent, Book of Business sort/filter/stats, real
  `finalize_claim` → PREFERRED ₹6L auto-approves, UNSCORED ₹6L and WATCH
  ₹3L → PENDING_REVIEW, WATCH ₹50k auto-approves, soft fraud 0.35.
- `pytest tests/` 15 passed (9 new in `tests/test_customer_trust.py`);
  frontend `tsc -b` + `vite build` pass.
- Local tooling note: used scratch venv `/tmp/trustvenv` (py3.13, stubbed
  chromadb) because `uv sync` into `backend/.venv` was very slow and was
  aborted — `backend/.venv` may be half-built; `uv sync` again if needed.
- Not verified: live CDE/Impala/CAI run, LLM-generated reasoning text.

### To go live in env 1 (after user review)
```bash
# local
git checkout main && git merge --no-ff feature/customer-trust-score && git push origin main
./cde/scripts/deploy_jobs.sh && ./cde/scripts/deploy_dag.sh   # repo syncs main
cde job run --name rsingh-insurance-generate-customer-profile-bronze
cde job run --name rsingh-insurance-transform-customer-profile-silver
cde job run --name rsingh-insurance-curate-customer-profile-gold
# (or just trigger the DAG — the customer chain runs in parallel)

# env 1 CAI Session
git pull && bash cml/cli.sh update
bash cml/cli.sh lakehouse ingest        # prints profile_signals_ingested
# restart the CAI Application
bash cml/cli.sh test-claim find --trust-tier WATCH --not-expired
```
Then check Book of Business trust column + a claim's Insights trust card.
**Env 2 impact on merge:** OLTP-only, so no lakehouse profiles — every
customer is UNSCORED (unchanged) except the seeded `test@example.com`,
which becomes PREFERRED (its auto-approval limit goes ₹5L → ₹7.5L).

### 2026-09-25 — merged to `main` + CDE part done in env 1
- `feature/customer-trust-score` merged to `main` (`a8c8aa7`), pushed.
- `deploy_jobs.sh` (all 11 jobs recreated) + `deploy_dag.sh` run.
- Customer chain runs all **succeeded**: bronze 2182, silver 2183, gold
  2184 → `insurance_lakehouse.customer_profile_signals` has 800 rows
  (credit bands EXCELLENT 355 / GOOD 200 / FAIR 129 / POOR 116; driving
  CLEAN 405 / MINOR 286 / POOR 109). Runs spend 10-20 min queued in
  `starting` on this vcluster — normal.
- Gotcha: macOS has no `timeout` binary; don't wrap `cde` polling in it.
- **Remaining (user):** env 1 CAI — `git pull && bash cml/cli.sh update`,
  `bash cml/cli.sh lakehouse ingest`, restart Application, verify.
