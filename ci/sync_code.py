"""
Job mcc-00-sync-code, the head of the training chain. Adapted from O-G-Asset-Integrity-Lakehouse
ci/sync_code.py: the repository is private and the CAI project blank, so the code arrives through
ci/push_files.py (from the laptop or GitHub Actions), which also writes CODE_VERSION (the commit).

  1. EXPECTED_GIT_SHA (set by the trigger in the run's environment) must match CODE_VERSION,
     otherwise the push did not land (or a newer one did) and the chain stops
  2. pip installs requirements.txt when it differs from the last install (hash in
     outputs/.requirements.sha256), into /home/cdsw/.local, which every job, the model build
     and the application see
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except NameError:  # CAI job kernels run the script without __file__; cwd is the project
        return Path(os.getcwd())


ROOT = _repo_root()


def install_requirements(root: Path, pip=None) -> bool:
    """pip install -r requirements.txt unless this exact file was installed last time."""
    reqs = root / "requirements.txt"
    digest = hashlib.sha256(reqs.read_bytes()).hexdigest()
    marker = root / "outputs" / ".requirements.sha256"
    if marker.exists() and marker.read_text().strip() == digest:
        print(f"requirements.txt unchanged ({digest[:12]}): nothing to install")
        return False
    print(f"installing requirements.txt ({digest[:12]})", flush=True)
    (pip or (lambda: subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r", str(reqs)])))()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(digest)
    return True


def main() -> int:
    version = ROOT / "CODE_VERSION"
    sha = version.read_text().split()[0].strip() if version.exists() else ""
    print(f"project code at {sha or '(no CODE_VERSION: run ci/push_files.py --all)'}")
    expected = os.environ.get("EXPECTED_GIT_SHA")
    if expected and not sha.startswith(expected):
        print(f"Expected commit {expected} but the project holds {sha or 'nothing'}. Stopping chain.")
        return 1
    (ROOT / "outputs").mkdir(exist_ok=True)
    (ROOT / "outputs" / "git_sha.txt").write_text(sha or "unknown")
    install_requirements(ROOT)
    return 0


if __name__ == "__main__":
    rc = main()
    if rc:   # any SystemExit, even 0, reads as failure under the CAI job kernel
        sys.exit(rc)
