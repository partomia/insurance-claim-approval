#!/usr/bin/env python3
"""
Cloudera AI (Workbench / CML) **Job** script — scheduled export of decided
app-filed claims into the lakehouse (closing the loop, see cde/README.md).

The mirror image of lakehouse_ingest_job.py: that one pulls lakehouse gold
data INTO the app; this one pushes real, app-filed claims (that finished the
AI decision pipeline) OUT to the lakehouse's app_claims_raw bronze table, so
the CDE claims-analytics pipeline's fraud/risk analytics
(cde/jobs/curate/curate_risk_signals_gold.py) are computed over real claims
too, not just the synthetic claims_history_raw population.

Set this as a CML **Job**'s Script (Project → Jobs → New Job), on a schedule
that runs *before* the CDE claims-analytics pipeline (generate-claims-bronze
et al.) — e.g. nightly. Job runs are independent of whether the Application
is currently running.

No paths are hardcoded — same repo-root resolution as cml/run.py, so it works
regardless of the cloned project name or whether CML executes this as a
subprocess or inside a notebook-kernel Job runtime.

Usage:
  • CML Job "Script" field: cml/jobs/lakehouse_export_claims_job.py
  • Terminal (manual test):  python cml/jobs/lakehouse_export_claims_job.py
"""
import os
import subprocess
import sys
from pathlib import Path


def _resolve_root() -> Path:
    """See cml/run.py for why this can't just be `Path(__file__).parent.parent.parent`
    unconditionally — CML Job runtimes can execute this inside a kernel where
    `__file__` isn't defined, same as the Application launcher."""
    try:
        return Path(__file__).resolve().parent.parent.parent
    except NameError:
        cwd = Path.cwd()
        if (cwd / "cml" / "run.py").exists():
            return cwd
        return Path("/home/cdsw")


ROOT = _resolve_root()
BACKEND = ROOT / "backend"


def _fix_openssl_ciphers_if_broken(py_cmd: list[str]) -> None:
    """See cml/run.py / cml/lib.sh for the full story: some hardened/
    FIPS-influenced CML runtimes make the uv-managed Python's SSL raise
    `ssl.SSLError: [SSL: LIBRARY_HAS_NO_CIPHERS]` on the first
    ssl.create_default_context() call — this job's Impala connection needs
    that to work. Probes the EXACT interpreter about to run before touching
    anything, so a runtime that already works is never affected. Always
    respects an operator's explicit OPENSSL_CONF."""
    if os.environ.get("OPENSSL_CONF"):
        return

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
        print("[lakehouse_export_claims_job] Detected LIBRARY_HAS_NO_CIPHERS — working around it with OPENSSL_CONF=/dev/null.")
    else:
        print(
            "[lakehouse_export_claims_job] WARNING: this Python's SSL looks broken and OPENSSL_CONF=/dev/null didn't fix it.",
            file=sys.stderr,
        )


def _locate_python() -> str:
    """Prefer the project's own venv; fall back to `uv run python`, then current interpreter."""
    venv_python = BACKEND / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)

    from shutil import which

    for extra in (Path.home() / ".local" / "bin", Path.home() / ".cargo" / "bin"):
        os.environ["PATH"] = f"{extra}:{os.environ.get('PATH', '')}"
    if which("uv"):
        return "uv"  # caller adds "run" "python"

    return sys.executable


python_bin = _locate_python()
py_cmd = [python_bin, "run", "python"] if python_bin == "uv" else [python_bin]
_fix_openssl_ciphers_if_broken(py_cmd)
cmd = py_cmd + ["scripts/export_claims_to_lakehouse.py"]

print(f"[lakehouse_export_claims_job] repo root : {ROOT}")
print(f"[lakehouse_export_claims_job] cwd       : {BACKEND}")
print(f"[lakehouse_export_claims_job] exec      : {' '.join(cmd)}")

result = subprocess.run(cmd, cwd=str(BACKEND))

# Only call sys.exit() on FAILURE — see lakehouse_ingest_job.py for the full
# story: CML Jobs on a JupyterLab-kernel runtime execute this script INSIDE
# a persistent IPython kernel, where sys.exit(0) raises SystemExit and gets
# reported as a Job failure even though the underlying script succeeded.
# Falling off the end of the script on success avoids that entirely. A real
# failure should still propagate.
if result.returncode != 0:
    sys.exit(result.returncode)
