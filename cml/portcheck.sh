#!/usr/bin/env bash
# Diagnose what's listening on a TCP port — works even without ss/lsof/fuser
# (common on stripped-down CAI runtimes). Falls back to reading /proc
# directly via python3, which is always present.
#
# Usage: bash cml/portcheck.sh [port]   (default: $CDSW_APP_PORT or 8090)
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

PORT="${1:-${CDSW_APP_PORT:-8090}}"
log "Inspecting port $PORT"

if command -v ss >/dev/null 2>&1; then
  echo "--- ss -ltnp ---"
  ss -ltnp 2>/dev/null | awk -v p=":$PORT" 'NR==1 || $4 ~ p'
elif command -v fuser >/dev/null 2>&1; then
  echo "--- fuser -v $PORT/tcp ---"
  fuser -v "$PORT"/tcp 2>&1 || true
fi

echo "--- /proc lookup (no extra tools needed) ---"
python3 - "$PORT" <<'PYEOF'
import os, sys

port = int(sys.argv[1])
port_hex = format(port, '04X')

try:
    lines = open('/proc/net/tcp').readlines()[1:]
except FileNotFoundError:
    print("  /proc/net/tcp not available (non-Linux runtime?)")
    sys.exit(0)

inodes = set()
for line in lines:
    local = line.split()[1]
    if local.split(':')[1].upper() == port_hex:
        inodes.add(line.split()[9])

if not inodes:
    print(f"  nothing listening on {port} (per /proc/net/tcp)")
    sys.exit(0)

found = False
for pid in os.listdir('/proc'):
    if not pid.isdigit():
        continue
    try:
        for fd in os.listdir(f'/proc/{pid}/fd'):
            link = os.readlink(f'/proc/{pid}/fd/{fd}')
            inode = link.split('[')[-1].rstrip(']') if 'socket:[' in link else None
            if inode in inodes:
                cmd = open(f'/proc/{pid}/cmdline').read().replace('\x00', ' ').strip()
                print(f"  pid={pid}  cmd={cmd or '(empty cmdline — kernel thread or no permission)'}")
                found = True
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue

if not found:
    print("  matching socket found but owning PID not visible from this user (permissions)")
PYEOF

echo "--- HTTP probe ---"
if body="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/" 2>&1)"; then
  echo "  ${body:0:300}"
else
  warn "No HTTP response from 127.0.0.1:$PORT — not bound, or not speaking HTTP"
fi
