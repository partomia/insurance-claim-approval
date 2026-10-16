"""
The insurer's event stream onto Kafka: telematics crash events (mcc.telematics.crash) and claim
events (mcc.claim.events: FNOL and every status change), from the same seeded universe the batch
sources come from, so a crash event on the stream matches the claim that cites it. Every
event-time minute gets a control message on mcc.control with the count sent per topic: the
stream reconciliation's control total. Copied from O-G-Asset-Integrity-Lakehouse
stream/producer/sensor_producer.py and adapted.

Planted stream faults (config/streaming.json producer.*):
  late          ~1 % of events sent 2-15 minutes late (inside the 30-minute watermark)
  out of order  ~2 % swapped with the next event

Modes:
  backfill  the business dates' events, as fast as the sink takes them
  live      real time: crash events on in-force vehicles at live_rate_msgs_s, and an FNOL now and
            then, for --duration seconds (0 = until stopped)

Sinks: kafka (MCC_KAFKA_*; SASL_SSL on the cluster) or files (JSON lines per topic, the CI and
laptop path the streaming job reads with a file source).

  python -m stream.producer.claim_producer --sink files --out data/stream --mode backfill
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def _repo_root() -> Path:
    try:
        return Path(__file__).resolve().parents[2]
    except NameError:  # CAI job kernels run the script without __file__; cwd is the project
        return Path(os.getcwd())


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))

from generators.universe import CFG as LCFG, World  # noqa: E402

CFG = json.loads((ROOT / "config" / "streaming.json").read_text())
P = CFG["producer"]
TOPIC = {k: v["name"] for k, v in CFG["topics"].items()}
MAX_DELAY_S = max(P["late_seconds"])


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _naive(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _key(topic: str, msg: dict) -> str:
    return msg.get("vin") or msg.get("claim_number") or msg.get("topic")


def crash_message(e: dict, run_id: str) -> dict:
    return {"event_id": e["event_id"], "vin": e["vin"], "event_ts": iso(_naive(e["event_ts"])),
            "g_force": e["g_force"], "speed_kmph": e["speed_kmph"], "lat": e["lat"], "lon": e["lon"],
            "device_id": e["device_id"], "producer_run": run_id}


def claim_messages(world: World, start: datetime, end: datetime, run_id: str) -> list[tuple[datetime, dict]]:
    out = []
    for cl in world.claims:
        fnol = cl.fnol.replace(tzinfo=timezone.utc)
        if start <= fnol < end:
            out.append((fnol, {"event_id": f"CE-{cl.claim_id}-0", "claim_number": cl.claim_id,
                               "policy_number": cl.policy.policy_number, "event_type": "FNOL", "status": "FILED",
                               "amount": cl.amount, "event_ts": iso(fnol), "source": "claims_portal",
                               "producer_run": run_id}))
        for n, (t, ev) in enumerate(world.status_events(cl), 1):
            t = t.replace(tzinfo=timezone.utc)
            if start <= t < end:
                out.append((t, {"event_id": f"CE-{cl.claim_id}-{n}", "claim_number": cl.claim_id,
                                "policy_number": cl.policy.policy_number, "event_type": "STATUS",
                                "status": ev["to_status"], "amount": ev["amount_approved"], "event_ts": iso(t),
                                "source": "claims_core", "producer_run": run_id}))
    return out


def schedule(events: list[tuple[datetime, str, dict]], rng: random.Random) -> list[tuple[float, str, dict]]:
    """(send time, topic, message): on time, a few late, a few swapped with their neighbour."""
    out = []
    for t, topic, msg in events:
        delay = rng.uniform(0.05, 2.0)
        if rng.random() < P["late_fraction"]:
            delay = rng.uniform(*P["late_seconds"])
        out.append([t.timestamp() + delay, topic, msg])
    out.sort(key=lambda x: x[0])
    for i in range(len(out) - 1):
        if rng.random() < P["out_of_order_fraction"]:
            out[i][0], out[i + 1][0] = out[i + 1][0], out[i][0]
    return [tuple(x) for x in out]


# ---------------------------------------------------------------- sinks


class FileSink:
    """JSON lines per topic per hour of send time: <out>/<topic>/part-<yyyymmddHH>.jsonl, one Kafka
    record per line ({"key", "timestamp" (send time, ms), "value" (the message as a JSON string)}),
    so the streaming job reads files and Kafka through the same parsing."""

    def __init__(self, out: str):
        self.out = Path(out)
        self.handles = {}
        self.sent = 0

    def send(self, topic: str, msg: dict, send_ts: float) -> None:
        hour = datetime.fromtimestamp(send_ts, timezone.utc).strftime("%Y%m%d%H")
        key = (topic, hour)
        if key not in self.handles:
            d = self.out / topic
            d.mkdir(parents=True, exist_ok=True)
            self.handles[key] = open(d / f"part-{hour}.jsonl", "a")
        rec = {"key": _key(topic, msg), "timestamp": int(send_ts * 1000),
               "value": json.dumps(msg, separators=(",", ":"))}
        self.handles[key].write(json.dumps(rec, separators=(",", ":")) + "\n")
        self.sent += 1

    def close(self) -> None:
        for h in self.handles.values():
            h.close()


class KafkaSink:
    def __init__(self):
        from kafka import KafkaProducer

        from stream.producer.topics import kafka_config

        self.p = KafkaProducer(**kafka_config(), acks="all", linger_ms=50, retries=10,
                               value_serializer=lambda v: json.dumps(v, separators=(",", ":")).encode(),
                               key_serializer=lambda k: k.encode() if k else None)
        self.sent = 0

    def send(self, topic: str, msg: dict, send_ts: float) -> None:
        self.p.send(topic, key=_key(topic, msg), value=msg)
        self.sent += 1

    def close(self) -> None:
        self.p.flush()
        self.p.close()


# ---------------------------------------------------------------- control counts


class Control:
    """Counts per (event minute, topic); a minute's control message goes out once no more of its
    events can still be sent (after the producer's maximum delay)."""

    def __init__(self, sink, run_id: str, hold_s: float):
        self.sink, self.run_id, self.hold_s = sink, run_id, hold_s
        self.counts = defaultdict(int)

    def count(self, topic: str, msg: dict) -> None:
        if topic != TOPIC["control"]:
            self.counts[(msg["event_ts"][:16] + ":00.000Z", topic)] += 1

    def flush(self, now_ts: float, final: bool = False) -> int:
        n = 0
        for key in sorted(self.counts):
            minute, topic = key
            mts = datetime.strptime(minute, "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=timezone.utc).timestamp()
            if final or mts + 60 + self.hold_s <= now_ts:
                total = self.counts.pop(key)
                self.sink.send(TOPIC["control"], {"minute": minute, "topic": topic, "counts": json.dumps({topic: total}),
                                                  "total": total, "producer_run": self.run_id},
                               mts + 60 + self.hold_s)
                n += 1
        return n


def _send_all(sink, ctl: Control, sched) -> None:
    for send_ts, topic, msg in sched:
        sink.send(topic, msg, send_ts)
        ctl.count(topic, msg)
        ctl.flush(send_ts)
    ctl.flush(0, final=True)


# ---------------------------------------------------------------- modes


def backfill(sink, start: date, days: int, run_id: str, world: World | None = None) -> None:
    world = world or World()
    rng = random.Random(f"{LCFG['seed']}:stream:{start}:{days}")
    t0 = datetime.combine(start, datetime.min.time(), timezone.utc)
    t1 = t0 + timedelta(days=days)
    events = [(_naive(e["event_ts"]), TOPIC["crash"], crash_message(e, run_id)) for e in world.crash_events
              if t0 <= _naive(e["event_ts"]) < t1]
    events += [(t, TOPIC["claim_event"], m) for t, m in claim_messages(world, t0, t1, run_id)]
    _send_all(sink, Control(sink, run_id, MAX_DELAY_S + 5), schedule(events, rng))


def live(sink, duration: int, run_id: str, world: World | None = None) -> None:
    world = world or World()
    rng = random.Random(int(time.time()))
    book = [p for p in world.policies.values() if p.status == "ACTIVE"]
    ctl = Control(sink, run_id, 5)
    started, n = time.time(), 0
    rate = P["live_rate_msgs_s"]
    while duration == 0 or time.time() - started < duration:
        time.sleep(rng.expovariate(rate))
        now = datetime.now(timezone.utc)
        p = rng.choice(book)
        n += 1
        if rng.random() < 0.05:
            msg = {"event_id": f"CE-L{run_id[-8:]}-{n}", "claim_number": f"CLM-L{n:06d}",
                   "policy_number": p.policy_number, "event_type": "FNOL", "status": "FILED",
                   "amount": round(rng.uniform(20_000, 300_000), 2), "event_ts": iso(now), "source": "claims_portal",
                   "producer_run": run_id}
            topic = TOPIC["claim_event"]
        else:
            msg = {"event_id": f"TM-L{run_id[-8:]}-{n}", "vin": p.vin, "event_ts": iso(now),
                   "g_force": round(rng.uniform(0.3, 2.5), 2), "speed_kmph": round(rng.uniform(0, 90), 1),
                   "lat": round(rng.uniform(8, 32), 5), "lon": round(rng.uniform(70, 88), 5),
                   "device_id": f"DEV-{rng.randint(1000, 9999)}", "producer_run": run_id}
            topic = TOPIC["crash"]
        sink.send(topic, msg, time.time())
        ctl.count(topic, msg)
        ctl.flush(time.time())
        if n % 1000 == 0:
            print(f"  {now.isoformat(timespec='seconds')} sent {sink.sent:,}", flush=True)
    ctl.flush(0, final=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sink", choices=["kafka", "files"], default=os.environ.get("MCC_PRODUCER_SINK", "kafka"))
    ap.add_argument("--out", default=str(ROOT / "data" / "stream"))
    ap.add_argument("--mode", choices=["backfill", "live"], default=os.environ.get("MCC_PRODUCER_MODE", "backfill"))
    ap.add_argument("--start-date", default=os.environ.get("MCC_PRODUCER_START", LCFG["business_dates"][0]))
    ap.add_argument("--days", type=int, default=int(os.environ.get("MCC_PRODUCER_DAYS", len(LCFG["business_dates"]))))
    ap.add_argument("--duration", type=int, default=int(os.environ.get("MCC_PRODUCER_DURATION", 0)))
    args, unknown = ap.parse_known_args(argv)
    if unknown:
        print(f"(ignoring arguments: {unknown})", flush=True)
    run_id = f"{args.mode}-{uuid.uuid4().hex[:8]}"
    sink = FileSink(args.out) if args.sink == "files" else KafkaSink()
    t0 = time.time()
    try:
        if args.mode == "backfill":
            print(f"backfill {args.start_date} + {args.days} days, run {run_id}, sink {args.sink}", flush=True)
            backfill(sink, date.fromisoformat(args.start_date), args.days, run_id)
        else:
            print(f"live at ~{P['live_rate_msgs_s']} msg/s, run {run_id}", flush=True)
            live(sink, args.duration, run_id)
    finally:
        sink.close()
    print(f"sent {sink.sent:,} messages in {time.time() - t0:.0f} s (run {run_id})", flush=True)
    return 0


if __name__ == "__main__":
    rc = main()
    if rc:
        sys.exit(rc)
