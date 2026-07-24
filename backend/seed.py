import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scripts.seed import seed_db

if __name__ == "__main__":
    reset = "--reset" in sys.argv
    seed_db(reset=reset)
