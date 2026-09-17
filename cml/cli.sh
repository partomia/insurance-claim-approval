#!/usr/bin/env bash
# Single entrypoint for all Cloudera AI automation in this repo.
#
#   bash cml/cli.sh <command> [flags]
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Cloudera AI (Workbench / CML) automation

Usage: cml/cli.sh <command> [flags]

Commands:
  doctor              Preflight checks (tools, .env sanity). Read-only.
  setup [flags]       One-shot bootstrap: uv/deps, .env, DB check, seed +
                       RAG index, frontend build.
                       flags: --skip-frontend --skip-seed --reset-db --run
  start [--bg]        Launch the app (python cml/run.py). Foreground by
                       default; --bg runs it detached (nohup) so this
                       terminal stays free — use for Session testing.
                       (The real CAI Application should point its Script
                       directly at cml/run.py, not go through this.)
  stop                Stop a --bg instance started from this session.
  status              Is it running? pid, port, /health check.
  logs [-f]           Tail the background instance's log (-f to follow).
  restart             stop + start --bg.
  smoke [base-url]    Hit /health /api/health /api/version /api/llm/health.
  update [--no-pull]  git pull + reinstall only what changed + schema check.
  reset [--yes]       Delete local SQLite/Chroma/storage demo state.
  portcheck [port]    Who's listening on a port + HTTP probe (no ss/lsof needed).
  diagnose [port]     Bundle doctor+status+portcheck+logs into one file to share.

Typical first run:
  bash cml/cli.sh doctor
  bash cml/cli.sh setup
  bash cml/cli.sh start --bg     # or set the Application's Script to cml/run.py
  bash cml/cli.sh smoke          # once it's up
  bash cml/cli.sh logs -f        # watch it
  bash cml/cli.sh stop           # when done testing
EOF
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  doctor)   exec bash "$SCRIPT_DIR/doctor.sh" "$@" ;;
  setup)    exec bash "$SCRIPT_DIR/setup.sh" "$@" ;;
  start)    exec bash "$SCRIPT_DIR/appctl.sh" start "$@" ;;
  stop)     exec bash "$SCRIPT_DIR/appctl.sh" stop ;;
  status)   exec bash "$SCRIPT_DIR/appctl.sh" status ;;
  logs)     exec bash "$SCRIPT_DIR/appctl.sh" logs "$@" ;;
  restart)  exec bash "$SCRIPT_DIR/appctl.sh" restart ;;
  smoke)    exec bash "$SCRIPT_DIR/smoke.sh" "$@" ;;
  update)   exec bash "$SCRIPT_DIR/update.sh" "$@" ;;
  reset)    exec bash "$SCRIPT_DIR/reset.sh" "$@" ;;
  portcheck) exec bash "$SCRIPT_DIR/portcheck.sh" "$@" ;;
  diagnose) exec bash "$SCRIPT_DIR/diagnose.sh" "$@" ;;
  help|-h|--help) usage ;;
  *) echo "Unknown command: $cmd" >&2; echo; usage; exit 2 ;;
esac
