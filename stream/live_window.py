"""
How long a manually started live stream may run (config/streaming.json live_window): until the
next stop_utc, or guard_minutes before the next nightly batch (batch_utc), whichever comes first,
optionally capped at --minutes. Prints the seconds for the stream and for the producer (which stops
producer_lead_seconds earlier), or 0 0 when less than min_seconds is left or the batch started
less than batch_minutes ago (it replays the stream itself).

  python3 -m stream.live_window [--minutes N]      # -> "<stream_seconds> <producer_seconds>"
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

CFG = json.loads((Path(__file__).resolve().parents[1] / "config" / "streaming.json").read_text())["live_window"]


def next_at(now: datetime, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return at if at > now else at + timedelta(days=1)


def seconds_left(now: datetime, minutes: int = 0, cfg: dict = CFG) -> tuple[int, int]:
    batch = next_at(now, cfg["batch_utc"])
    if now < batch - timedelta(days=1) + timedelta(minutes=cfg["batch_minutes"]):
        return 0, 0
    cutoff = min(next_at(now, cfg["stop_utc"]), batch - timedelta(minutes=cfg["guard_minutes"]))
    seconds = int((cutoff - now).total_seconds())
    if minutes:
        seconds = min(seconds, minutes * 60)
    if seconds < cfg["min_seconds"]:
        return 0, 0
    return seconds, max(seconds - cfg["producer_lead_seconds"], 60)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--minutes", type=int, default=0, help="run at most this long (0: until the cutoff)")
    args = p.parse_args(argv)
    print(*seconds_left(datetime.now(timezone.utc), args.minutes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
