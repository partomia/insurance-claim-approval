#!/usr/bin/env bash
# Manage the app process from a CAI Session terminal: start (fg/bg), stop,
# status, logs, restart. For the REAL Cloudera AI Application deployment,
# point the Application "Script" directly at cml/run.py — appctl.sh is only
# for testing inside a Session terminal (CML manages the Application's
# process lifecycle itself; this script has no effect on that).
#
# Usage (normally via the dispatcher):
#   bash cml/cli.sh start [--bg]
#   bash cml/cli.sh stop
#   bash cml/cli.sh status
#   bash cml/cli.sh logs [-f]
#   bash cml/cli.sh restart
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

PID_FILE="$STATE_DIR/app.pid"
PORT_FILE="$STATE_DIR/app.port"

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid; pid="$(cat "$PID_FILE" 2>/dev/null)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

do_start() {
  local bg=0
  for a in "$@"; do [[ "$a" == "--bg" || "$a" == "-d" ]] && bg=1; done

  if is_running; then
    warn "Already running (pid $(cat "$PID_FILE")). Use 'stop' first, or check 'status'/'logs'."
    return 0
  fi
  rm -f "$PID_FILE" "$PORT_FILE"

  local port="${CDSW_APP_PORT:-8090}"

  if [[ "$bg" -eq 0 ]]; then
    log "Starting in foreground on port $port (Ctrl+C to stop)"
    exec python3 "$ROOT/cml/run.py"
  fi

  local logfile="$LOG_DIR/app-$(date +%Y%m%d-%H%M%S).log"
  log "Starting in background on port $port"
  nohup python3 "$ROOT/cml/run.py" > "$logfile" 2>&1 &
  local pid=$!
  disown "$pid" 2>/dev/null || true
  echo "$pid" > "$PID_FILE"
  echo "$port" > "$PORT_FILE"

  # Poll /health instead of a flat sleep — cold imports (crewai/langchain/
  # chromadb) can take well over a second, and a bare "process is alive"
  # check reports success before the server has actually bound the port,
  # producing a confusing false-positive followed by failing smoke tests.
  log "Waiting for it to become healthy (up to 60s — first cold start is slowest)"
  local waited=0
  while [[ "$waited" -lt 60 ]]; do
    if curl -fsS --max-time 2 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
      ok "Started (pid $pid) — healthy after ${waited}s"
      echo "  Logs:    $logfile"
      echo "  Check:   bash cml/cli.sh status"
      echo "  Tail:    bash cml/cli.sh logs -f"
      echo "  Stop:    bash cml/cli.sh stop"
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      err "Process exited while starting up — check $logfile"
      tail -n 30 "$logfile" 2>/dev/null
      rm -f "$PID_FILE" "$PORT_FILE"
      return 1
    fi
    sleep 2
    waited=$((waited + 2))
  done
  warn "Still not responding to /health after 60s (pid $pid still alive)."
  warn "Not necessarily broken — check: bash cml/cli.sh logs -f"
}

do_stop() {
  if ! is_running; then
    warn "Not running (no live pid tracked)"
    rm -f "$PID_FILE" "$PORT_FILE"
    return 0
  fi
  local pid; pid="$(cat "$PID_FILE")"
  log "Stopping pid $pid"
  kill "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    warn "Still alive after 10s — sending SIGKILL"
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE" "$PORT_FILE"
  ok "Stopped"
}

do_status() {
  if is_running; then
    local pid port
    pid="$(cat "$PID_FILE")"
    port="$(cat "$PORT_FILE" 2>/dev/null || echo "${CDSW_APP_PORT:-8090}")"
    ok "Running — pid=$pid port=$port"
    if body="$(curl -fsS --max-time 5 "http://127.0.0.1:$port/health" 2>&1)"; then
      ok "Health: $body"
    else
      warn "Process alive but /health didn't respond (still starting up, or crashed after bind)"
    fi
  else
    warn "Not running"
    rm -f "$PID_FILE" "$PORT_FILE"
  fi
}

do_logs() {
  local follow=0
  for a in "$@"; do [[ "$a" == "-f" || "$a" == "--follow" ]] && follow=1; done
  local latest
  latest="$(ls -t "$LOG_DIR"/app-*.log 2>/dev/null | head -1)"
  if [[ -z "$latest" ]]; then
    warn "No background app log found — start with: bash cml/cli.sh start --bg"
    return 1
  fi
  echo "==> $latest"
  if [[ "$follow" -eq 1 ]]; then tail -f "$latest"; else tail -n 100 "$latest"; fi
}

cmd="${1:-status}"; shift || true
case "$cmd" in
  start)   do_start "$@" ;;
  stop)    do_stop ;;
  status)  do_status ;;
  logs)    do_logs "$@" ;;
  restart) do_stop; do_start --bg ;;
  *) err "Unknown appctl command: $cmd"; exit 2 ;;
esac
