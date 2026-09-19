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


def _fix_openssl_ciphers_if_broken(uvicorn_cmd: list[str]) -> None:
    """See cml/lib.sh's fix_openssl_ciphers_if_broken() for the full story:
    some hardened/FIPS-influenced CML runtimes make the uv-managed Python's
    SSL raise `ssl.SSLError: [SSL: LIBRARY_HAS_NO_CIPHERS]` on the first
    ssl.create_default_context() call (Impala, LLM API calls) — the
    runtime's own system python3 is unaffected. Probes the EXACT
    interpreter this process is about to exec into before touching
    anything, so a runtime that already works is never affected. Always
    respects an operator's explicit OPENSSL_CONF.
    """
    if os.environ.get("OPENSSL_CONF"):
        return

    venv_python = BACKEND / ".venv" / "bin" / "python"
    if venv_python.exists():
        py_cmd = [str(venv_python)]
    elif uvicorn_cmd[0] == "uv":
        py_cmd = ["uv", "run", "python"]
    else:
        return  # sys.executable fallback — same interpreter running this file, already known-good

    import subprocess

    probe = ["-c", "import ssl; ssl.create_default_context()"]

    def _probe_ok(env=None) -> bool:
        try:
            return subprocess.run(py_cmd + probe, cwd=str(BACKEND), capture_output=True, timeout=15, env=env).returncode == 0
        except Exception:
            return False

    if _probe_ok():
        return

    fixed_env = os.environ.copy()
    fixed_env["OPENSSL_CONF"] = "/dev/null"
    if _probe_ok(fixed_env):
        os.environ["OPENSSL_CONF"] = "/dev/null"
        print("[cml/run] Detected ssl.SSLError: LIBRARY_HAS_NO_CIPHERS — working around it with OPENSSL_CONF=/dev/null (see cml/README.md).")
    else:
        print(
            "[cml/run] WARNING: this Python's SSL looks broken and OPENSSL_CONF=/dev/null didn't fix it — outbound HTTPS (Impala/LLM calls) may fail.",
            file=sys.stderr,
        )


cmd = _locate_uvicorn() + [
    "main:app",
    "--host", "127.0.0.1",
    "--port", str(PORT),
    "--workers", str(WORKERS),
]
_fix_openssl_ciphers_if_broken(cmd)

print(f"[cml/run] exec: {' '.join(cmd)}  (cwd={BACKEND})")
os.chdir(BACKEND)
os.execvp(cmd[0], cmd)
