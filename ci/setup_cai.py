#!/usr/bin/env python3
"""
One-off CAI setup over the API v2, from a laptop. Idempotent: each step finds by name first
and only creates what is missing. Copied from O-G-Asset-Integrity-Lakehouse (from CXR) and
adapted: the repository is private, so the project is created blank and the code is uploaded
with ci/push_files.py (no deploy key on the repo).

  1. Project rsingh-motor-claim-copilot (blank), if absent.
  2. Project environment: the workload user for CDW Impala and the Copilot's LLM key and model
     (GROQ_*), from the caller's environment (values never printed).
  3. The jobs of ci/cai_jobs.py with parents, schedule, timeout, size and environment.
  4. --app: the application MCC Motor Claim Copilot (Phase 10).

  set -a; source .env; set +a
  python ci/setup_cai.py --dry-run
  python ci/setup_cai.py                      # project, environment, jobs
  python ci/push_files.py --all               # the code
  python ci/setup_cai.py --run mcc-00-sync-code
  python ci/setup_cai.py --app
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ci.cai_jobs import JOBS, MODEL, RUNTIME, SCORE_JOB  # noqa: E402

CAI_PROJECT_NAME = "rsingh-motor-claim-copilot"
PROJECT_ENV = {"MCC_DB_PREFIX": "rsingh_mcc"}
PROJECT_ENV_FROM_CALLER = ("MCC_IMPALA_USER", "MCC_IMPALA_PASSWORD")
PROJECT_ENV_OPTIONAL = ("GROQ_API_KEY", "GROQ_MODEL")
APP = {"name": "MCC Motor Claim Copilot", "subdomain": "rsingh-mcc-copilot", "script": "cml/launch_app.py",
       "cpu": 2, "memory": 8, "description": "Motor claim copilot: FNOL to decision, with the lakehouse model's "
                                            "second opinion in shadow mode"}


class Workbench:
    def __init__(self, url: str, key: str):
        self.base = f"{url.rstrip('/')}/api/v2"
        self.h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def __call__(self, method: str, path: str, params=None, body=None) -> dict:
        r = requests.request(method, self.base + path, params=params, json=body, headers=self.h, timeout=120)
        if r.status_code >= 400:
            raise SystemExit(f"{method} {path}: HTTP {r.status_code} {r.text[:300]}")
        return r.json() if r.text else {}


def find_project(wb: Workbench, name: str = CAI_PROJECT_NAME) -> dict | None:
    found = wb("GET", "/projects", params={"search_filter": json.dumps({"name": name}), "page_size": 100})
    return next((p for p in found.get("projects", []) if p["name"] == name), None)


def ensure_project(wb: Workbench, dry_run: bool) -> dict | None:
    project = find_project(wb)
    if project:
        print(f"project {CAI_PROJECT_NAME}: exists ({project['id']})")
        return project
    if dry_run:
        print(f"project {CAI_PROJECT_NAME}: would create (blank; code via ci/push_files.py)")
        return None
    project = wb("POST", "/projects", body={
        "name": CAI_PROJECT_NAME, "template": "blank", "visibility": "private",
        "default_project_engine_type": "ml_runtime",
        "description": "Motor Claim Copilot on Cloudera: approval and fraud models on the claims lakehouse "
                       "(private repo partomia/insurance-claim-approval; code pushed by ci/push_files.py)"})
    print(f"project {CAI_PROJECT_NAME}: created ({project['id']})", end="", flush=True)
    for _ in range(60):
        status = str(wb("GET", f"/projects/{project['id']}").get("creation_status", "")).lower()
        if status in ("success", "succeeded", ""):
            break
        if "fail" in status or "error" in status:
            raise SystemExit(f"\nproject creation {status}")
        print(".", end="", flush=True)
        time.sleep(5)
    print(" done")
    return project


def wanted_env() -> dict:
    missing = [k for k in PROJECT_ENV_FROM_CALLER if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"set {missing} in the environment (source .env) first")
    return {**PROJECT_ENV, **{k: os.environ[k] for k in PROJECT_ENV_FROM_CALLER},
            **{k: os.environ[k] for k in PROJECT_ENV_OPTIONAL if os.environ.get(k)}}


def app_env(wb: Workbench, pid: str) -> dict:
    """The Copilot's own settings (backend/config.py names) for the application and the
    cml/jobs/lakehouse_* jobs: OLTP on SQLite, lakehouse = the mcc gold/bronze databases on
    CDW Impala, the model endpoint in shadow mode."""
    imp = json.loads((Path(__file__).resolve().parents[1] / "config" / "lakehouse.json").read_text())["impala"]
    prefix = PROJECT_ENV["MCC_DB_PREFIX"]
    env = {"DB_BACKEND": "sqlite", "LAKEHOUSE_DATABASE": f"{prefix}_gold",
           "LAKEHOUSE_BRONZE_DATABASE": f"{prefix}_bronze", "IMPALA_DATABASE": f"{prefix}_gold",
           "IMPALA_HOST": imp["host"], "IMPALA_PORT": str(imp["port"]), "IMPALA_HTTP_PATH": imp["http_path"],
           "IMPALA_AUTH_MECHANISM": imp["auth_mechanism"], "IMPALA_USE_SSL": "true",
           "IMPALA_USE_HTTP_TRANSPORT": "true", "IMPALA_USER": os.environ["MCC_IMPALA_USER"],
           "IMPALA_PASSWORD": os.environ["MCC_IMPALA_PASSWORD"], "APPROVAL_MODEL_MODE": "shadow"}
    model = next((m for m in wb("GET", f"/projects/{pid}/models").get("models", []) if m["name"] == MODEL), None)
    if model:
        host = os.environ["MCC_CAI_HOST"].rstrip("/").replace("://", "://modelservice.", 1)
        env.update({"APPROVAL_MODEL_URL": f"{host}/model", "APPROVAL_MODEL_ACCESS_KEY": model["access_key"]})
    else:
        print(f"model {MODEL} not deployed yet: the app starts with the model call skipped")
    return env


def ensure_env(wb: Workbench, project: dict, dry_run: bool, app: bool = False) -> None:
    current = json.loads(wb("GET", f"/projects/{project['id']}").get("environment") or "{}")
    wanted = {**wanted_env(), **(app_env(wb, project["id"]) if app else {})}
    changed = sorted(k for k, v in wanted.items() if current.get(k) != v)
    if not changed:
        print("project environment: up to date")
    elif dry_run:
        print(f"project environment: would set {changed}")
    else:
        wb("PATCH", f"/projects/{project['id']}", body={"environment": json.dumps({**current, **wanted})})
        print(f"project environment: set {changed}")


def job_ids(wb: Workbench, pid: str) -> dict:
    return {j["name"]: j for j in wb("GET", f"/projects/{pid}/jobs", params={"page_size": 200}).get("jobs", [])}


def job_env(job: dict) -> dict:
    env = job.get("environment") or {}
    return json.loads(env) if isinstance(env, str) else dict(env)


def ensure_jobs(wb: Workbench, project: dict, dry_run: bool) -> dict:
    pid = project["id"]
    existing = job_ids(wb, pid)
    ids = {n: j["id"] for n, j in existing.items()}
    for job in JOBS:     # parents come first in JOBS
        size = {"cpu": job["cpu"], "memory": job["memory"]}
        env = job.get("env", {})
        if job["name"] in existing:
            have = existing[job["name"]]
            have_env = job_env(have)
            patch = {**({} if {k: have.get(k) for k in size} == size else size),
                     **({} if all(have_env.get(k) == v for k, v in env.items()) else
                        {"environment": json.dumps({**have_env, **env})})}
            if not patch:
                print(f"job {job['name']}: exists ({have['id']})")
            elif dry_run:
                print(f"job {job['name']}: would update {sorted(patch)}")
            else:
                wb("PATCH", f"/projects/{pid}/jobs/{have['id']}", body=patch)
                print(f"job {job['name']}: updated {sorted(patch)}")
            continue
        if not (Path(__file__).resolve().parents[1] / job["script"]).exists():
            print(f"job {job['name']}: skipped ({job['script']} not in this checkout)")
            continue
        if dry_run:
            print(f"job {job['name']}: would create ({job['script']}, parent {job['parent']}, "
                  f"{job['cpu']} vCPU / {job['memory']} GB, env {env})")
            continue
        body = {"name": job["name"], "script": job["script"], **size, "runtime_identifier": RUNTIME,
                "timeout": job["timeout"], "kill_on_timeout": bool(job["timeout"]), "arguments": "",
                "environment": env}
        if job["parent"]:
            body["parent_job_id"] = ids[job["parent"]]
        if job["schedule"]:
            body["schedule"] = job["schedule"]
        created = wb("POST", f"/projects/{pid}/jobs", body=body)
        ids[job["name"]] = created["id"]
        print(f"job {job['name']}: created ({created['id']})")
    return ids


def ensure_app(wb: Workbench, project: dict, dry_run: bool) -> None:
    pid = project["id"]
    app = next((a for a in wb("GET", f"/projects/{pid}/applications", params={"page_size": 100})
                .get("applications", []) if a["name"] == APP["name"]), None)
    if app and (app.get("cpu"), app.get("memory")) != (APP["cpu"], APP["memory"]) and not dry_run:
        wb("PATCH", f"/projects/{pid}/applications/{app['id']}", body={"cpu": APP["cpu"], "memory": APP["memory"]})
        wb("POST", f"/projects/{pid}/applications/{app['id']}:restart")
        print(f"application {APP['name']}: resized to {APP['cpu']} vCPU / {APP['memory']} GB and restarted")
    elif app:
        print(f"application {APP['name']}: exists ({app['id']}, {app.get('status')})")
    elif dry_run:
        print(f"application {APP['name']}: would create ({APP['script']}, {APP['cpu']} vCPU / {APP['memory']} GB)")
    else:
        app = wb("POST", f"/projects/{pid}/applications", body={
            "project_id": pid, "name": APP["name"], "subdomain": APP["subdomain"], "script": APP["script"],
            "cpu": APP["cpu"], "memory": APP["memory"], "kernel": "python3", "runtime_identifier": RUNTIME,
            "description": APP["description"]})
        print(f"application {APP['name']}: created ({app['id']}), subdomain {APP['subdomain']}")


def run_job(wb: Workbench, pid: str, job_id: str, name: str, env: dict | None = None, poll: int = 30) -> str:
    run = wb("POST", f"/projects/{pid}/jobs/{job_id}/runs", body={"environment": env or {}})
    print(f"{name}: run {run['id']} started", flush=True)
    t0, last = time.time(), None
    while True:
        time.sleep(poll)
        st = str(wb("GET", f"/projects/{pid}/jobs/{job_id}/runs/{run['id']}").get("status", "")).lower()
        st = st.replace("engine_", "")
        if st != last:
            print(f"{name}: {st} after {time.time() - t0:.0f} s", flush=True)
            last = st
        if st in ("succeeded", "failed", "stopped", "timedout"):
            return st


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--app", action="store_true")
    p.add_argument("--run", default="", help="start this job by name and follow it to the end")
    p.add_argument("--env", default="", help="with --run: KEY=VALUE,... for the job run's environment")
    p.add_argument("--poll", type=int, default=30)
    args, _ = p.parse_known_args()
    wb = Workbench(os.environ["MCC_CAI_HOST"], os.environ["MCC_CAI_API_KEY"])
    project = ensure_project(wb, args.dry_run)
    if project is None:
        return 0
    if args.run:
        job = job_ids(wb, project["id"]).get(args.run)
        if not job:
            raise SystemExit(f"no job {args.run}")
        env = dict(kv.split("=", 1) for kv in args.env.split(",") if kv)
        return 0 if run_job(wb, project["id"], job["id"], args.run, env, args.poll) == "succeeded" else 1
    ensure_env(wb, project, args.dry_run, app=args.app)
    ids = ensure_jobs(wb, project, args.dry_run)
    if args.app:
        ensure_app(wb, project, args.dry_run)
    print(f"\nGitHub secrets: CAI_URL = {os.environ['MCC_CAI_HOST'].rstrip('/')}, CAI_PROJECT_ID = {project['id']}")
    print(f"Airflow Variables: MCC_CAI_PROJECT_ID = {project['id']}, "
          f"MCC_CAI_SCORE_JOB_ID = {ids.get(SCORE_JOB, '(not created)')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
