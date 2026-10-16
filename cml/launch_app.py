#!/usr/bin/env python3
"""
Cloudera AI Application "MCC Motor Claim Copilot" (ci/setup_cai.py --app) and job
mcc-09-app-setup (MCC_APP_SETUP_ONLY=1).

  1. If the app is not built yet (no backend/.venv uvicorn or no frontend/dist), runs
     cml/setup.sh (uv, backend deps, demo seed, RAG index, SPA build), then pulls the mcc gold
     tables into the app (cml/jobs/lakehouse_ingest_job.py). Run it as the job first: the
     application then starts in seconds.
  2. Hands over to cml/run.py (FastAPI + SPA on CDSW_APP_PORT), unchanged from go01.

Settings come from the project environment (ci/setup_cai.py app_env: LAKEHOUSE_DATABASE,
IMPALA_*, APPROVAL_MODEL_*), never from this file.
"""
import os
import subprocess
import sys
from pathlib import Path


def _resolve_root() -> Path:
    try:
        return Path(__file__).resolve().parent.parent
    except NameError:  # CAI runs application and job scripts in a Jupyter kernel: no __file__
        return Path.cwd() if (Path.cwd() / "cml" / "run.py").exists() else Path("/home/cdsw")


ROOT = _resolve_root()


def built() -> bool:
    return (ROOT / "backend" / ".venv" / "bin" / "uvicorn").exists() and (ROOT / "frontend" / "dist" / "index.html").exists()


def setup() -> int:
    print("[launch_app] building the app: cml/setup.sh", flush=True)
    rc = subprocess.run(["bash", str(ROOT / "cml" / "setup.sh")], cwd=ROOT).returncode
    if rc:
        return rc
    print("[launch_app] lakehouse ingest from", os.environ.get("LAKEHOUSE_DATABASE", "(LAKEHOUSE_DATABASE unset)"), flush=True)
    return subprocess.run([sys.executable, str(ROOT / "cml" / "jobs" / "lakehouse_ingest_job.py")], cwd=ROOT).returncode


def main() -> int:
    setup_only = os.environ.get("MCC_APP_SETUP_ONLY") == "1"
    if setup_only or not built():
        rc = setup()
        if rc or setup_only:
            return rc
    os.chdir(ROOT)
    os.execv(sys.executable, [sys.executable, str(ROOT / "cml" / "run.py")])
    return 0


if __name__ == "__main__":
    rc = main()
    if rc:
        sys.exit(rc)
