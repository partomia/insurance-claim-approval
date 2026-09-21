"""Generate a small set of synthetic claim-evidence documents for manual/demo
testing of the claim submission wizard (Step 3: Evidence Upload) — e.g. to
exercise the Phase 4 "Claim Insights" risk card, which only renders on a
claim submitted against a lakehouse (LH-POL-*) policy (see
scripts/set_demo_password.py to get a login for one of those customers).

These are plain generated images with a clear "SYNTHETIC TEST DOCUMENT" /
"Not a real document" watermark — NOT real IDs or photos. Output files are
also committed under docs/demo-assets/claim-docs/ so they're usable
straight from a git checkout without needing Pillow/fonts; this script is
for regenerating them (e.g. to target a different policy/customer) rather
than a required build step.

Usage:
    cd backend
    uv run python scripts/generate_demo_claim_docs.py
    uv run python scripts/generate_demo_claim_docs.py --out /tmp/my-claim-docs
"""

import argparse
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_DEFAULT_OUT = Path(__file__).resolve().parent.parent.parent / "docs" / "demo-assets" / "claim-docs"

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Helvetica.ttc",  # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # common Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans.ttf",
)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def make_doc(out_dir: Path, filename: str, title: str, lines: list[str], bg, accent) -> Path:
    width, height = 1000, 700
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)
    font_title = _load_font(36)
    font_body = _load_font(22)
    font_small = _load_font(16)

    draw.rectangle([0, 0, width, 90], fill=accent)
    draw.text((30, 25), title, fill=(255, 255, 255), font=font_title)

    y = 130
    for line in lines:
        draw.text((40, y), line, fill=(30, 30, 30), font=font_body)
        y += 40

    draw.rectangle([0, height - 50, width, height], fill=(230, 230, 235))
    draw.text(
        (30, height - 40),
        "SYNTHETIC TEST DOCUMENT — generated for QA/demo purposes only. Not a real document.",
        fill=(120, 0, 0),
        font=font_small,
    )

    dest = out_dir / filename
    img.save(dest, quality=90)
    return dest


def generate(out_dir: Path, policy_number: str, customer_name: str, vehicle: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    written.append(
        make_doc(
            out_dir,
            "damage_photo_front.jpg",
            "DAMAGE PHOTO — FRONT BUMPER",
            [
                f"Policy: {policy_number}",
                f"Vehicle: {vehicle}",
                "Location: Front bumper / left headlamp",
                "Description: Dent + cracked headlamp housing",
            ],
            bg=(235, 240, 245),
            accent=(180, 30, 30),
        )
    )
    written.append(
        make_doc(
            out_dir,
            "damage_photo_side.jpg",
            "DAMAGE PHOTO — LEFT SIDE PANEL",
            [
                f"Policy: {policy_number}",
                f"Vehicle: {vehicle}",
                "Location: Left front door panel",
                "Description: Scratch + paint chip, ~30cm",
            ],
            bg=(235, 240, 245),
            accent=(180, 30, 30),
        )
    )
    written.append(
        make_doc(
            out_dir,
            "driver_license.jpg",
            "DRIVER'S LICENCE (SAMPLE)",
            [
                f"Name: {customer_name}",
                f"DL No: DEMO-DL-{policy_number[-4:]}-XXXX",
                "DOB: 1990-04-12",
                "Class: LMV",
                "Issuing Authority: DEMO RTO — NOT REAL",
            ],
            bg=(250, 248, 235),
            accent=(30, 90, 160),
        )
    )
    written.append(
        make_doc(
            out_dir,
            "repair_estimate.jpg",
            "REPAIR ESTIMATE",
            [
                "Garage: Comfort Motors, Surat",
                f"Policy: {policy_number}",
                "Front bumper replacement: Rs 18,500",
                "Headlamp assembly: Rs 6,200",
                "Paint + labour: Rs 4,800",
                "Total estimate: Rs 29,500",
            ],
            bg=(240, 245, 238),
            accent=(30, 130, 70),
        )
    )
    written.append(
        make_doc(
            out_dir,
            "vehicle_registration.jpg",
            "VEHICLE REGISTRATION (RC) — SAMPLE",
            [
                f"Owner: {customer_name}",
                "Registration No: DEMO-GJ-05-XX-1234",
                f"Make/Model: {vehicle}",
                "Chassis No: DEMO-CHASSIS-0000000",
            ],
            bg=(245, 240, 250),
            accent=(90, 60, 160),
        )
    )
    written.append(
        make_doc(
            out_dir,
            "police_report.jpg",
            "POLICE / FIR REPORT (SAMPLE)",
            [
                f"Policy: {policy_number}",
                "FIR No: DEMO-FIR-0000-2026",
                "Station: Demo Traffic Police Station",
                "Third party / injuries: as reported by claimant",
            ],
            bg=(248, 240, 240),
            accent=(150, 60, 30),
        )
    )

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="Output directory")
    parser.add_argument("--policy-number", default="LH-POL-2050")
    parser.add_argument("--customer-name", default="Ananya Iyer")
    parser.add_argument("--vehicle", default="Volkswagen Taigun")
    args = parser.parse_args()

    written = generate(args.out, args.policy_number, args.customer_name, args.vehicle)
    for path in written:
        print(f"[ok] Wrote {path}")
    print(f"\n{len(written)} files in {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
