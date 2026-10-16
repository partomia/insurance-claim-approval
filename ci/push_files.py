#!/usr/bin/env python3
"""
Upload repository files to the (blank) CAI project through the API v2 files endpoint: the repo
is private, so this is how code reaches CAI. Copied from O-G-Asset-Integrity-Lakehouse
ci/push_files.py and adapted. Only tracked files are sent; data, models and outputs never leave
the laptop this way. Every push also writes CODE_VERSION (commit and branch), which
mcc-00-sync-code checks and the models record.

  set -a; source .env; set +a
  python ci/push_files.py --all                    # every tracked file of the CAI side (first push)
  python ci/push_files.py --since HEAD~1           # files changed in the last commit
  python ci/push_files.py serve/predict.py config/pipeline.yaml
  (cd frontend && VITE_API_URL="" npm run build) && python ci/push_files.py --dist
                                                   # the built SPA (federal cannot install Node)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ci.setup_cai import Workbench, find_project  # noqa: E402

# What the CAI side needs (jobs, endpoint, app); the CDE jobs, docs and tests stay out.
CAI_PATHS = ("common.py", "cdsw-build.sh", "requirements.txt", "requirements-model.txt", ".gitignore",
             "config/", "features/", "train/", "gate/", "serve/", "monitor/", "guardrails/", "lakehouse/",
             "ci/", "scripts/fetch_dataset.py", "backend/", "frontend/", "cml/", "docs/demo-assets/", "run.py", "start.sh")


def changed(since: str) -> list[str]:
    out = subprocess.check_output(["git", "diff", "--name-only", "--diff-filter=AM", since, "HEAD"], cwd=ROOT, text=True)
    return [p for p in out.split() if (ROOT / p).is_file()]


def cai_side(paths: list[str]) -> list[str]:
    return [p for p in paths if any(p == c or (c.endswith("/") and p.startswith(c)) for c in CAI_PATHS)]


def git(*args) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--since", default="")
    ap.add_argument("--all", action="store_true", help="every tracked file of the CAI side")
    ap.add_argument("--dist", action="store_true", help="also the built frontend/dist (git-ignored)")
    a = ap.parse_args()
    tracked = git("ls-files").split("\n")
    paths = list(a.paths) + (changed(a.since) if a.since else []) + (cai_side(tracked) if a.all else [])
    paths = sorted(set(paths))
    skipped = [p for p in paths if p not in set(tracked)]
    paths = [p for p in paths if p in set(tracked) and (ROOT / p).stat().st_size > 0]
    if a.dist:
        dist = ROOT / "frontend" / "dist"
        if not (dist / "index.html").exists():
            raise SystemExit("no frontend/dist/index.html: build it first (see above)")
        paths += sorted(str(p.relative_to(ROOT)) for p in dist.rglob("*") if p.is_file())
    if skipped:
        print(f"not tracked, not sent: {skipped}")
    if git("status", "--porcelain", "--untracked-files=no", "--", *paths) if paths else "":
        print("WARNING: uncommitted edits in the files sent; CODE_VERSION names HEAD", flush=True)
    wb = Workbench(os.environ["MCC_CAI_HOST"], os.environ["MCC_CAI_API_KEY"])
    pid = find_project(wb)["id"]
    url = f"{wb.base}/projects/{pid}/files"
    h = {"Authorization": wb.h["Authorization"]}
    version = f"{git('rev-parse', 'HEAD')} {git('rev-parse', '--abbrev-ref', 'HEAD')}\n"
    for p in paths:
        with open(ROOT / p, "rb") as f:
            r = requests.put(url, headers=h, files={p: (Path(p).name, f)}, timeout=120)
        print(f"{'ok ' if r.ok else 'ERR'} {p}" + ("" if r.ok else f" HTTP {r.status_code} {r.text[:150]}"), flush=True)
        if not r.ok:
            return 1
    r = requests.put(url, headers=h, files={"CODE_VERSION": ("CODE_VERSION", version.encode())}, timeout=60)
    if not r.ok:
        print(f"ERR CODE_VERSION HTTP {r.status_code} {r.text[:150]}")
        return 1
    print(f"{len(paths)} files uploaded to project {pid}; CODE_VERSION {version.split()[0][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
