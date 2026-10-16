"""Run one project script on CAI with its output saved to outputs/logs/<name>.log.

CAI job logs are only served over the UI websocket; this file can be fetched with the v2 files
API instead (ci/run_logged.py --fetch <name> from a laptop).

    on CAI:  python ci/run_logged.py features/build_feature_table.py [args...]
    laptop:  python ci/run_logged.py --fetch build_feature_table
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
    pid = find_project(wb)["id"]
    path = f"outputs/logs/{name}.log".replace("/", "%2F")
    r = requests.get(f"{wb.base}/projects/{pid}/files/{path}:download", headers=wb.h, timeout=60)
    if not r.ok:
        print(f"HTTP {r.status_code}: {r.text[:200]}")
        return 1
    print(r.text[-20000:])
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--fetch":
        sys.exit(fetch(sys.argv[2]))
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    rc = run(sys.argv[1], sys.argv[2:])
    if rc:
        sys.exit(rc)
