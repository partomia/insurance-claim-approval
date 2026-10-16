"""Run one project script on CAI with its output saved to outputs/logs/<name>.log.

CAI job logs are only served over the UI websocket; this file can be fetched with the v2 files
API instead (ci/run_logged.py --fetch <name> from a laptop).

    on CAI:  python ci/run_logged.py features/build_feature_table.py [args...]
    laptop:  python ci/run_logged.py --fetch build_feature_table
"""
import os
import subprocess
import sys
from pathlib import Path

try:
    ROOT = Path(__file__).resolve().parents[1]
except NameError:  # CAI runs job scripts in a Jupyter kernel: no __file__, cwd is /home/cdsw
    ROOT = Path(os.getcwd())


def run(script: str, args: list[str]) -> int:
    logs = ROOT / "outputs" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{Path(script).stem}.log"
    with open(log, "w") as f:
        p = subprocess.run([sys.executable, str(ROOT / script), *args], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT)
    print(log.read_text()[-20000:])
    return p.returncode


def fetch(name: str) -> int:
    import requests

    sys.path.insert(0, str(ROOT))
    from ci.setup_cai import Workbench, find_project

    wb = Workbench(os.environ["MCC_CAI_HOST"], os.environ["MCC_CAI_API_KEY"])
    slug = find_project(wb)["owner"]["username"] + "/" + find_project(wb)["name"]
    host = os.environ["MCC_CAI_HOST"].rstrip("/")
    # v2 has no file download; v1 takes the API key as the basic-auth user
    r = requests.get(f"{host}/api/v1/projects/{slug}/files/outputs/logs/{name}.log",
                     auth=(os.environ["MCC_CAI_API_KEY"], ""), timeout=60)
    if not r.ok:
        print(f"HTTP {r.status_code}: {r.text[:200]}")
        return 1
    print(r.text[-20000:])
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:] or os.environ.get("MCC_RUN_SCRIPT", "").split()
    if argv and argv[0] == "-f":  # ipykernel's own argv, not the job arguments
        argv = os.environ.get("MCC_RUN_SCRIPT", "").split()
    if len(argv) > 1 and argv[0] == "--fetch":
        sys.exit(fetch(argv[1]))
    if not argv:
        sys.exit(__doc__)
    rc = run(argv[0], argv[1:])
    if rc:
        sys.exit(rc)
