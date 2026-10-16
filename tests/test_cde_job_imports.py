import subprocess
import sys
from pathlib import Path

import pytest

JOBS = Path(__file__).resolve().parents[1] / "cde" / "jobs"
CODE = """
import importlib.util, sys
sys.path.insert(0, {jobs!r})
spec = importlib.util.spec_from_file_location("job", {path!r})
spec.loader.exec_module(importlib.util.module_from_spec(spec))
"""


@pytest.mark.parametrize("path", sorted(JOBS.glob("*.py")), ids=lambda p: p.name)
def test_job_imports_before_spark_starts(path):
    """CDE runs each job file as __main__ with no SparkContext yet: building a Column at import fails."""
    out = subprocess.run([sys.executable, "-c", CODE.format(jobs=str(JOBS), path=str(path))],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
