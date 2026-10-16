import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dag_scheduled_dates_match_the_config():
    tree = ast.parse((ROOT / "cde" / "dags" / "mcc_dag.py").read_text())
    dates = next(ast.literal_eval(n.value) for n in ast.walk(tree)
                 if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "SCHEDULED_DATES")
    cfg = json.loads((ROOT / "config" / "lakehouse.json").read_text())
    assert list(dates) == cfg["scheduled_dates"]
