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

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND_DIST = ROOT / "frontend" / "dist"

PORT = os.environ.get("CDSW_APP_PORT", "8090")
WORKERS = os.environ.get("UVICORN_WORKERS", "1")

# CML-friendly defaults (do not clobber anything the operator set explicitly).
os.environ.setdefault("SERVE_FRONTEND", "true")
os.environ.setdefault("CLAIM_PROCESSING_MODE", "sync")

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
