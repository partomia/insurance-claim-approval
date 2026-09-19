#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Shared helpers sourced by every cml/*.sh script. Not meant to be run
# directly. Intentionally does NOT set -e/-u — callers opt into their own
# strictness (doctor.sh wants to keep checking after a failure; setup.sh/
# update.sh want to fail fast).
# ---------------------------------------------------------------------------

CML_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$CML_DIR/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
STATE_DIR="$CML_DIR/.state"
LOG_DIR="$CML_DIR/logs"
mkdir -p "$STATE_DIR" "$LOG_DIR"

# Auto-source nvm if it was installed (e.g. via `nvm install --lts`) but the
# current shell never sourced ~/.bashrc for it — true for CAI Application
# launches (which exec a script directly, not a login shell) and for any
# fresh Session terminal opened after `nvm install` if no profile file
# existed for the installer to append to. Without this, `command -v npm`
# would silently fail here even though Node is actually installed.
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [[ -s "$NVM_DIR/nvm.sh" ]]; then
  # shellcheck disable=SC1091
  \. "$NVM_DIR/nvm.sh" >/dev/null 2>&1 || true
fi

# Some hardened/FIPS-influenced CML runtimes ship an OpenSSL config that gets
# picked up even when $OPENSSL_CONF is unset/empty, and ends up activating
# zero cipher suites for the *uv-managed* Python's bundled OpenSSL — the
# system python3 on the same host is unaffected, only `uv run python` /
# `backend/.venv/bin/python` is. First symptom is always
# `ssl.SSLError: [SSL: LIBRARY_HAS_NO_CIPHERS]` on the very first
# ssl.create_default_context() call (Impala HTTPS transport, LLM API calls),
# even with zero LLM config. Confirmed fix: /dev/null (skip loading any
# external config, fall back to OpenSSL's compiled-in defaults) — verified
# on an affected cluster without regressing unaffected ones. Only applied
# when unset/empty so we never clobber an operator's deliberate override.
export OPENSSL_CONF="${OPENSSL_CONF:-/dev/null}"

log()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }

# ensure_uv — install `uv` if missing, exporting PATH so it's usable
# immediately in the calling script. Shared by setup.sh and update.sh so
# `update` never crashes with a bare "uv: command not found" on a session
# that hasn't run `setup` yet.
ensure_uv() {
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  if command -v uv >/dev/null 2>&1; then ok "uv present: $(uv --version)"; return 0; fi
  log "Installing uv..."
  if command -v pip >/dev/null 2>&1; then
    pip install --user -q uv || pip install -q uv
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    err "uv still not on PATH after install attempt."
    err "Run 'bash cml/cli.sh setup' once — it bootstraps uv + all deps from scratch."
    return 1
  fi
  ok "uv installed: $(uv --version)"
}

# ensure_net_tools — best-effort install of `ss` (iproute2) and `fuser`
# (psmisc), used to debug "address already in use" on CDSW_APP_PORT.
# Purely a convenience: requires root/apt, which many CAI runtimes don't
# grant to the session user — silently no-ops if it can't install them.
# `cml/portcheck.sh` diagnoses ports without these anyway, via /proc.
ensure_net_tools() {
  if command -v ss >/dev/null 2>&1 && command -v fuser >/dev/null 2>&1; then
    ok "ss/fuser already available"
    return 0
  fi
  if command -v apt-get >/dev/null 2>&1; then
    if apt-get update -qq >/dev/null 2>&1 && \
       apt-get install -y --no-install-recommends iproute2 psmisc >/dev/null 2>&1; then
      :
    elif command -v sudo >/dev/null 2>&1; then
      sudo -n apt-get update -qq >/dev/null 2>&1 || true
      sudo -n apt-get install -y --no-install-recommends iproute2 psmisc >/dev/null 2>&1 || true
    fi
  fi
  if command -v ss >/dev/null 2>&1 && command -v fuser >/dev/null 2>&1; then
    ok "ss/fuser installed"
  else
    warn "Could not install ss/fuser (no root/apt on this runtime) — use 'bash cml/portcheck.sh <port>' instead, it needs no extra packages"
  fi
}

# start_logging <name> — mirror all subsequent stdout/stderr to a timestamped
# file under cml/logs/, in addition to the terminal.
start_logging() {
  local name="$1"
  local file="$LOG_DIR/${name}-$(date +%Y%m%d-%H%M%S).log"
  exec > >(tee -a "$file") 2>&1
  echo "[log] $file"
}

# --- change detection (skip expensive steps when inputs are unchanged) -----
_hash_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    cat "$@" 2>/dev/null | sha256sum | awk '{print $1}'
  else
    cat "$@" 2>/dev/null | shasum -a 256 | awk '{print $1}'
  fi
}

# hash_changed <state-key> <file...>  → true (0) if changed or never recorded
hash_changed() {
  local key="$1"; shift
  local new old file
  new="$(_hash_of "$@")"
  file="$STATE_DIR/$key.sha256"
  old=""
  [[ -f "$file" ]] && old="$(cat "$file")"
  [[ "$new" != "$old" ]]
}

save_hash() {
  local key="$1"; shift
  _hash_of "$@" > "$STATE_DIR/$key.sha256"
}

# --- .env helpers ------------------------------------------------------------
env_get() {
  # env_get KEY [file] — last uncommented occurrence, empty if unset.
  local key="$1" file="${2:-$BACKEND/.env}"
  [[ -f "$file" ]] || return 0
  grep -E "^${key}=" "$file" | tail -1 | cut -d= -f2- || true
}

env_set() {
  # env_set KEY VALUE [file] — replace if present, else append. Idempotent.
  local key="$1" val="$2" file="${3:-$BACKEND/.env}"
  if grep -qE "^${key}=" "$file" 2>/dev/null; then
    sed -i.bak -E "s|^${key}=.*|${key}=${val}|" "$file" && rm -f "$file.bak"
  else
    printf '\n%s=%s\n' "$key" "$val" >> "$file"
  fi
}

# validate_env — best-effort sanity check of backend/.env; warns, never fails.
# Returns 1 only if .env is missing entirely.
validate_env() {
  local file="$BACKEND/.env"
  if [[ ! -f "$file" ]]; then
    warn "backend/.env missing — run 'cml/cli.sh setup' first"
    return 1
  fi

  local db_backend; db_backend="$(env_get DB_BACKEND "$file")"; db_backend="${db_backend:-sqlite}"
  ok "DB_BACKEND=$db_backend"
  if [[ "$db_backend" == "impala" ]]; then
    local host auth; host="$(env_get IMPALA_HOST "$file")"; auth="$(env_get IMPALA_AUTH_MECHANISM "$file")"
    [[ -n "$host" ]] && ok "IMPALA_HOST set" || warn "IMPALA_HOST is empty"
    if [[ "${auth:-GSSAPI}" == "GSSAPI" ]]; then
      warn "Impala auth=GSSAPI — run 'kinit' in this session before connecting"
    else
      [[ -n "$(env_get IMPALA_USER "$file")" ]] || warn "Impala auth=$auth but IMPALA_USER is empty"
    fi
  fi

  local endpoint api_key groq llm_ok=0
  endpoint="$(env_get ENDPOINT "$file")"; api_key="$(env_get API_KEY "$file")"; groq="$(env_get GROQ_API_KEY "$file")"
  if [[ -n "$endpoint" && -n "$api_key" ]]; then ok "Custom LLM endpoint configured"; llm_ok=1; fi
  if [[ -n "$groq" ]]; then ok "GROQ_API_KEY set"; llm_ok=1; fi
  [[ "$llm_ok" -eq 1 ]] || warn "No LLM configured (ENDPOINT+API_KEY or GROQ_API_KEY) — will fall back to templated responses"

  local jwt; jwt="$(env_get JWT_SECRET "$file")"
  if [[ -z "$jwt" || "$jwt" == "change-me-in-production" ]]; then
    warn "JWT_SECRET is still the placeholder — fine for a demo, rotate before real use"
  fi
  return 0
}

# check_env_drift — warn about keys present in .env.example but missing from
# .env (e.g. after `cml/cli.sh update` pulls a newer template).
check_env_drift() {
  local example="$BACKEND/.env.example" file="$BACKEND/.env"
  [[ -f "$example" && -f "$file" ]] || return 0
  local missing=()
  while IFS= read -r key; do
    [[ -n "$key" ]] || continue
    grep -qE "^${key}=" "$file" || missing+=("$key")
  done < <(grep -oE '^[A-Z_0-9]+=' "$example" | sed 's/=$//' | sort -u)
  if [[ "${#missing[@]}" -gt 0 ]]; then
    warn "New keys in .env.example not yet in your .env: ${missing[*]}"
  else
    ok ".env has all keys from .env.example"
  fi
}
