import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config" / "platform.json").read_text())


def test_no_script_shadows_the_stdlib():
    stems = {p.stem for p in (ROOT / "scripts").glob("*.py")}
    assert not stems & set(sys.stdlib_module_names)


def test_orders_cover_the_same_layers():
    assert sorted(CFG["stop_order"]) == sorted(CFG["start_order"])
    assert CFG["stop_order"][0] == "cai" and CFG["start_order"][-1] == "cai"


def test_schedules_match_the_cai_job_definitions():
    sys.path.insert(0, str(ROOT))
    from ci.cai_jobs import JOBS

    crons = {j["name"]: j["schedule"] for j in JOBS if j.get("schedule")}
    assert CFG["project"]["cai_scheduled_jobs"] == crons
