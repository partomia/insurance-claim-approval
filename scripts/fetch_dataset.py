#!/usr/bin/env python3
"""
Fetch the public benchmark fraud_oracle.csv ("carclaims", Angoss) from Kaggle dataset
shivamb/vehicle-claim-fraud-detection, CC0 public domain, pinned to dataset version 1 and checked
by sha256. It evaluates the fraud head's method out of domain and is never mixed into training.

  set -a; source .env; set +a                 # MCC_KAGGLE_API_TOKEN (a KGAT_ token; never printed)
  python scripts/fetch_dataset.py             # -> data/public/fraud_oracle.csv
  python scripts/fetch_dataset.py --check     # verify the local copy only (no network)

Standard library only. An existing file with the right hash is not downloaded again.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = "shivamb/vehicle-claim-fraud-detection"
VERSION = 1
FILE = "fraud_oracle.csv"
SHA256 = "8b6aa59764ef4f8b058598d3e8f325ef3623f52f4b1cd4ef946baebb5ccfa9a6"
ROWS, FRAUD = 15420, 923
URL = f"https://www.kaggle.com/api/v1/datasets/download/{DATASET}?datasetVersionNumber={VERSION}"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def profile(data: bytes) -> tuple[int, int]:
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    return len(rows), sum(r["FraudFound_P"] == "1" for r in rows)


def verify(data: bytes) -> None:
    if sha256(data) != SHA256:
        raise SystemExit(f"{FILE}: sha256 {sha256(data)[:12]}... is not the pinned {SHA256[:12]}...")
    if profile(data) != (ROWS, FRAUD):
        raise SystemExit(f"{FILE}: {profile(data)} rows/fraud, expected {(ROWS, FRAUD)}")


def download() -> bytes:
    token = os.environ.get("MCC_KAGGLE_API_TOKEN")
    if not token:
        raise SystemExit("set MCC_KAGGLE_API_TOKEN (Kaggle -> Settings -> API -> Create New Token)")
    req = urllib.request.Request(URL, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return zipfile.ZipFile(io.BytesIO(r.read())).read(FILE)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=str(ROOT / "data" / "public" / FILE))
    p.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    out = Path(args.out)
    if out.is_file() and sha256(out.read_bytes()) == SHA256:
        verify(out.read_bytes())
        print(f"{out}: up to date ({ROWS} claims, {FRAUD} fraud)")
        return 0
    if args.check:
        raise SystemExit(f"{out}: missing or not the pinned version")
    data = download()
    verify(data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"{out}: {DATASET} v{VERSION}, {ROWS} claims, {FRAUD} fraud, sha256 {SHA256[:12]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
