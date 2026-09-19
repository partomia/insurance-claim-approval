#!/usr/bin/env python3
"""
Cloudera AI (Workbench / CML) application launcher.

Serves the FastAPI backend AND the built React SPA from a SINGLE process on
CDSW_APP_PORT (one Cloudera AI Application hosts UI + API on the same origin).

Use it two ways:
  • Terminal:      python cml/run.py
  • Application:    set the Application "Script" to  cml/run.py

No paths are hardcoded — the repo root is derived from this file's location,
so it works regardless of the cloned project name.

Relevant env (all optional; sensible defaults applied):
  CDSW_APP_PORT     port Cloudera AI proxies the Application on (default 8090)
  UVICORN_WORKERS   worker processes (default 1 — keep 1 for SQLite / SSE)
  ROOT_PATH         set to /proxy/<port> ONLY if running behind a Session PORTS
                    proxy; leave empty for a real Application (clean subdomain).
  SERVE_FRONTEND    default "true" here so the SPA is served
  CLAIM_PROCESSING_MODE  default "sync" here (no Redis/Celery needed on CML)
"""
import os
import sys
from pathlib import Path


def _resolve_root() -> Path:
    """Resolve the repo root, robust to how Cloudera AI executes this script.

    Run as a subprocess (`python3 cml/run.py` — a Session terminal, or
    cml/appctl.sh), `__file__` is defined normally. But a Cloudera AI
    **Application** configured with a JupyterLab-kernel runtime executes the
    script INSIDE an IPython kernel (visible in the Application's error log
    as `Cell In[N]` — the same mechanism as a notebook `%run`), where
    `__file__` is never injected into globals, raising NameError. Fall back
    to the current working directory, which Cloudera AI always sets to the
    project root for both Sessions and Applications, with `/home/cdsw` (the
    standard CDSW/CML project mount) as a last resort.
    """
    try:
        return Path(__file__).resolve().parent.parent
    except NameError:
        cwd = Path.cwd()
        if (cwd / "cml" / "run.py").exists():
            return cwd
        return Path("/home/cdsw")


ROOT = _resolve_root()
BACKEND = ROOT / "backend"
FRONTEND_DIST = ROOT / "frontend" / "dist"

PORT = os.environ.get("CDSW_APP_PORT", "8090")
WORKERS = os.environ.get("UVICORN_WORKERS", "1")

# CML-friendly defaults (do not clobber anything the operator set explicitly).
os.environ.setdefault("SERVE_FRONTEND", "true")
os.environ.setdefault("CLAIM_PROCESSING_MODE", "sync")
# Some hardened/FIPS-influenced CML runtimes ship an OpenSSL config that gets
# picked up even when OPENSSL_CONF is unset/empty, activating zero cipher
# suites for the uv-managed Python this process execs into (uvicorn under
# backend/.venv) — surfaces as `ssl.SSLError: [SSL: LIBRARY_HAS_NO_CIPHERS]`
# on the first outbound TLS call (Impala, LLM API), even with no LLM
# configured. /dev/null (skip external config, use OpenSSL's compiled-in
# defaults) is a verified fix that doesn't regress unaffected runtimes; only
# set here if not already set, so an operator's deliberate override wins.
# See cml/README.md § Notes/gotchas.
os.environ.setdefault("OPENSSL_CONF", "/dev/null")

print(f"[cml/run] repo root : {ROOT}")
print(f"[cml/run] backend   : {BACKEND}")
print(f"[cml/run] app port  : {PORT}  (CDSW_APP_PORT)")
print(f"[cml/run] workers   : {WORKERS}")
print(f"[cml/run] root_path : {os.environ.get('ROOT_PATH', '') or '(none)'}")

if not (FRONTEND_DIST / "index.html").exists():
    print(
        "[cml/run] WARNING: frontend/dist not found — the UI will not be served.\n"
        "          Run 'bash cml/setup.sh' first (or start API-only).",
        file=sys.stderr,
    )


def _locate_uvicorn() -> list[str]:
    """Prefer the project's own venv; fall back to `uv run`, then module."""
    venv_uvicorn = BACKEND / ".venv" / "bin" / "uvicorn"
    if venv_uvicorn.exists():
        return [str(venv_uvicorn)]

    for extra in (Path.home() / ".local" / "bin", Path.home() / ".cargo" / "bin"):
        os.environ["PATH"] = f"{extra}:{os.environ.get('PATH', '')}"

    from shutil import which

    if which("uv"):
        return ["uv", "run", "uvicorn"]

    # Last resort: current interpreter's uvicorn module.
    return [sys.executable, "-m", "uvicorn"]


cmd = _locate_uvicorn() + [
    "main:app",
    "--host", "127.0.0.1",
    "--port", str(PORT),
    "--workers", str(WORKERS),
]

print(f"[cml/run] exec: {' '.join(cmd)}  (cwd={BACKEND})")
os.chdir(BACKEND)
os.execvp(cmd[0], cmd)
