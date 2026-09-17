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
  start               Launch the app (python cml/run.py). Foreground.
  smoke [base-url]    Hit /health /api/health /api/version /api/llm/health.
  update [--no-pull]  git pull + reinstall only what changed + schema check.
  reset [--yes]       Delete local SQLite/Chroma/storage demo state.
  portcheck [port]    Who's listening on a port + HTTP probe (no ss/lsof needed).

Typical first run:
  bash cml/cli.sh doctor
  bash cml/cli.sh setup
  bash cml/cli.sh start          # or set this as the Application's Script
  bash cml/cli.sh smoke          # from another terminal, once it's up
EOF
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  doctor) exec bash "$SCRIPT_DIR/doctor.sh" "$@" ;;
  setup)  exec bash "$SCRIPT_DIR/setup.sh" "$@" ;;
  start)  exec python3 "$SCRIPT_DIR/run.py" ;;
  smoke)  exec bash "$SCRIPT_DIR/smoke.sh" "$@" ;;
  update) exec bash "$SCRIPT_DIR/update.sh" "$@" ;;
  reset)  exec bash "$SCRIPT_DIR/reset.sh" "$@" ;;
  portcheck) exec bash "$SCRIPT_DIR/portcheck.sh" "$@" ;;
  help|-h|--help) usage ;;
  *) echo "Unknown command: $cmd" >&2; echo; usage; exit 2 ;;
esac
