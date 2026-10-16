import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cde" / "jobs"))
os.environ.setdefault("MCC_CONFIG_OVERLAY", "config/ci.yaml")
