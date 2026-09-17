# Cloudera AI (Workbench / CML) automation

Everything is driven through one dispatcher, `cml/cli.sh`. All scripts
auto-detect the repo root, so the clone name doesn't matter.

```
cml/
├── cli.sh       ← single entrypoint — run this
├── lib.sh       ← shared helpers (logging, .env validation, change detection)
├── doctor.sh    ← preflight checks, read-only
├── setup.sh     ← one-shot bootstrap (idempotent, incremental)
├── appctl.sh    ← start/stop/status/logs for Session-terminal testing
├── update.sh    ← git pull + reinstall only what changed
├── reset.sh     ← wipe local demo state (SQLite/Chroma/storage)
├── smoke.sh     ← post-deploy endpoint checks
├── portcheck.sh ← what's listening on a port (no ss/lsof/fuser needed)
├── diagnose.sh  ← bundles doctor+status+portcheck+logs into one shareable file
├── run.py       ← Application launcher (serves UI + API)
├── .state/      ← cached lockfile hashes + app pid/port (gitignored)
└── logs/        ← timestamped run/app logs (gitignored)
```

## Commands

```bash
bash cml/cli.sh doctor              # check tools + .env sanity, no changes
bash cml/cli.sh setup [flags]       # bootstrap: deps, .env, DB, seed, RAG, SPA build
bash cml/cli.sh start [--bg]        # launch — foreground, or detached (--bg)
bash cml/cli.sh stop                # stop a --bg instance
bash cml/cli.sh status              # pid/port + /health check
bash cml/cli.sh logs [-f]           # tail the --bg instance's log
bash cml/cli.sh restart             # stop + start --bg
bash cml/cli.sh smoke [base-url]    # hit /health, /api/health, /api/version, /api/llm/health
bash cml/cli.sh update [--no-pull]  # git pull + reinstall only changed deps + schema check
bash cml/cli.sh reset [--yes]       # delete local demo DB/Chroma/storage
bash cml/cli.sh portcheck [port]    # who's bound to a port + HTTP probe
bash cml/cli.sh diagnose [port]     # one file with doctor+status+portcheck+logs, for sharing
```

`setup` flags: `--skip-frontend` `--skip-seed` `--reset-db` `--run`

### First run in a Session terminal

```bash
bash cml/cli.sh doctor      # see what's missing before you start
bash cml/cli.sh setup       # one-shot bootstrap
bash cml/cli.sh start --bg  # detached — terminal stays free
bash cml/cli.sh smoke       # verify it's up
bash cml/cli.sh logs -f     # watch it live (Ctrl+C just stops watching, not the app)
bash cml/cli.sh stop        # when done testing
```

Hit an error and want to ask for help? `bash cml/cli.sh diagnose` — one file
with everything needed to debug, instead of five separate pastes.

### As a Cloudera AI Application

Set the Application **Script** to `cml/run.py` directly (not `cli.sh`/`appctl.sh`
— those are for Session-terminal testing; CML's Application launcher manages
the real process lifecycle itself). Run `cml/cli.sh setup` once in a Session
first so `.venv` / `frontend/dist` exist before the Application starts.

### Ongoing maintenance

- Pulled new commits? Run `bash cml/cli.sh update` — it only reinstalls backend
  or frontend deps if their lockfiles actually changed (hash-cached in
  `cml/.state/`), always rebuilds the SPA and re-checks the DB schema, and
  warns about any new `.env.example` keys your `.env` is missing.
- Want a clean demo? `bash cml/cli.sh reset --yes && bash cml/cli.sh setup --reset-db`
  (SQLite/Chroma/storage only — never touches remote Impala/CDP data).
- Every `setup`/`update` run is logged to `cml/logs/<cmd>-<timestamp>.log` for
  debugging failed runs later.
- `setup` generates a random `JWT_SECRET` the first time it creates `backend/.env`
  (no longer the shared demo placeholder).

## Before you start — edit `backend/.env`

`setup` creates it with safe demo defaults (SQLite, `CLAIM_PROCESSING_MODE=sync`,
`SERVE_FRONTEND=true`). `doctor`/`setup` will keep reminding you if these are
missing. Set at least one LLM provider:

- **Cloudera AI Inference** (recommended on CML — `api.groq.com` is often blocked):
  ```env
  ENDPOINT=https://<host>/namespaces/serving-default/endpoints/<model>/openai/v1
  API_KEY=<cai-inference-key>
  LLM_MODEL=<served-model-id>
  ```
- **Groq**: `GROQ_API_KEY=...`

For the real CDP database instead of SQLite:
```env
DB_BACKEND=impala
IMPALA_HOST=...        # + IMPALA_HTTP_PATH, etc.
# Kerberos: run `kinit` in the session, or use LDAP:
# IMPALA_AUTH_MECHANISM=LDAP / IMPALA_USER / IMPALA_PASSWORD
```

## Notes / gotchas

- **Deploy as an Application** (clean subdomain) → leave `ROOT_PATH` empty. Only
  set `ROOT_PATH=/proxy/<port>` if you expose it via a Session **PORTS** proxy
  (absolute `/assets` paths don't survive a path-prefix proxy).
- Keep `UVICORN_WORKERS=1` with SQLite and for SSE claim streaming.
- `CDSW_APP_PORT` (e.g. `8090`) may already be bound by the CAI **Session**
  container's own placeholder before you run anything. `setup` tries to
  install `ss`/`fuser` for diagnostics (best-effort, needs root/apt — often
  unavailable) but `bash cml/cli.sh portcheck [port]` works either way. For
  ad-hoc testing in a Session, just use a different port:
  `CDSW_APP_PORT=8099 bash cml/cli.sh start`. The real CAI **Application**
  resource owns `CDSW_APP_PORT` correctly — that's the one that should bind it.
- Requires a runtime with **Node/npm** for the SPA build; otherwise run
  `setup --skip-frontend` and host the frontend elsewhere (e.g. Vercel).
- Python is pinned to **3.13** via `uv`; `setup` tries `uv python install 3.13`
  (needs egress). If offline, relax `requires-python` and re-lock, or use a
  runtime/custom-runtime that already has 3.13.

## Ideas not yet automated (tell me if you want these next)

- **Programmatic Application provisioning** via Cloudera's `cmlapi` Python
  client — create/update the Application (script, env vars, subdomain) from
  code instead of the UI. Needs a CML API key + project ID.
- **Alembic-based migrations** instead of the current additive
  create-table/column-heal approach in `db_init.py`.
- **CI smoke test** — run `doctor` + a headless `setup --skip-frontend` in
  GitHub Actions against SQLite to catch breakage before it reaches CML.
