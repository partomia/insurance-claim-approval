# Session Handoff / Memory Dump

> Read this first when resuming work on this project. Update it at the end of
> each significant session — append new dated entries, don't delete history
> unless it's fully superseded.

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
