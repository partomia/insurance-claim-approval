import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stream.live_window import seconds_left

ROOT = Path(__file__).resolve().parents[1]
LAKEHOUSE = json.loads((ROOT / "config" / "lakehouse.json").read_text())
LIVE = json.loads((ROOT / "config" / "streaming.json").read_text())["live_window"]


def constants(dag_file: str) -> dict:
    tree = ast.parse((ROOT / "cde" / "dags" / dag_file).read_text())
    return {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
            and isinstance(n.value, (ast.Constant, ast.Tuple))}


def test_dag_scheduled_dates_match_the_config():
    assert list(constants("mcc_dag.py")["SCHEDULED_DATES"]) == LAKEHOUSE["scheduled_dates"]


def test_live_dag_matches_the_config():
    c = constants("mcc_live_dag.py")
    assert list(c["LIVE_DATES"]) == LAKEHOUSE["scheduled_dates"]
    assert (c["LIVE_START_UTC"], c["LIVE_STOP_UTC"]) == (LIVE["start_utc"], LIVE["stop_utc"])
    assert (c["MIN_SECONDS"], c["PRODUCER_LEAD_S"]) == (LIVE["min_seconds"], LIVE["producer_lead_seconds"])
    assert c["CHECKPOINTS"] == constants("mcc_dag.py")["CHECKPOINTS"]


def test_live_window_ends_before_the_batch():
    assert LIVE["start_utc"] < LIVE["stop_utc"] < LIVE["batch_utc"]


def at(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 10, 19, h, m, tzinfo=timezone.utc)


@pytest.mark.parametrize("now, minutes, expected", [
    ("09:00", 0, 4.5 * 3600),            # inside the window: until stop_utc
    ("09:00", 30, 30 * 60),              # capped by --minutes
    ("15:00", 0, 5.25 * 3600),           # after the window: until 15 min before the batch
    ("20:12", 0, 0),                     # inside the guard
    ("21:00", 0, 0),                     # the batch is running
    ("23:00", 0, 14.5 * 3600),           # after the batch: until the next stop_utc
])
def test_manual_stream_never_overlaps_the_batch(now, minutes, expected):
    stream_s, producer_s = seconds_left(at(now), minutes, LIVE)
    assert stream_s == expected
    assert producer_s == (max(expected - LIVE["producer_lead_seconds"], 60) if expected else 0)
