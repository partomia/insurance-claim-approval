"""The stream producer's files sink: every message is counted once in a control message, and the
messages satisfy their stream contracts."""
import json
from collections import Counter
from datetime import date

import mcc_common as C
from stream.producer import claim_producer as SP


def test_backfill_control_totals_match(tmp_path):
    sink = SP.FileSink(str(tmp_path))
    SP.backfill(sink, date(2026, 10, 13), 1, "test-run")
    sink.close()
    sent, control = Counter(), Counter()
    contracts = {c["topic"]: c for c in C.stream_contracts().values()}
    for topic_dir in tmp_path.iterdir():
        for f in topic_dir.glob("*.jsonl"):
            for line in f.read_text().splitlines():
                msg = json.loads(json.loads(line)["value"])
                required = [x["name"] for x in contracts[topic_dir.name]["fields"] if x.get("required")]
                assert all(msg.get(k) not in (None, "") for k in required)
                if topic_dir.name == SP.TOPIC["control"]:
                    control[msg["topic"]] += msg["total"]
                else:
                    sent[topic_dir.name] += 1
    assert sent and sent == control
    assert set(sent) == {SP.TOPIC["crash"], SP.TOPIC["claim_event"]}
