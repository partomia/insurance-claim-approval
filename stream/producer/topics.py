"""
Kafka topics and Schema Registry schemas for the mcc stream (only mcc.* topics and mcc.*
schemas are ever created or changed). Copied from O-G-Asset-Integrity-Lakehouse and adapted.

  python -m stream.producer.topics --create-topics --register-schemas [--check]

Connection from MCC_KAFKA_* (.env locally, CAI project environment in the job). The Avro
schemas in stream/schemas/ are registered as the message contract; messages are JSON-encoded
per that schema (readable in SMM's data explorer).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((ROOT / "config" / "streaming.json").read_text())
SCHEMAS = {"crash": "telematics_crash.avsc", "claim_event": "claim_event.avsc", "control": "control.avsc"}


def all_topics() -> dict:
    return dict(CFG["topics"])


def kafka_config() -> dict:
    """kafka-python connection settings from MCC_KAFKA_* (PLAINTEXT for a local broker)."""
    proto = os.environ.get("MCC_KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
    cfg = {"bootstrap_servers": os.environ.get("MCC_KAFKA_BOOTSTRAP", "localhost:9092").split(","),
           "security_protocol": proto, "client_id": "mcc-producer"}
    if proto.startswith("SASL"):
        cfg.update(sasl_mechanism=os.environ.get("MCC_KAFKA_SASL_MECHANISM", "PLAIN"),
                   sasl_plain_username=os.environ["MCC_KAFKA_USER"],
                   sasl_plain_password=os.environ["MCC_KAFKA_PASSWORD"])
    if "SSL" in proto:
        cfg["ssl_cafile"] = ca_file()
        cfg["ssl_check_hostname"] = True
    return cfg


def ca_file() -> str | None:
    """The environment's CA certificate: MCC_KAFKA_CA_PEM (a path, on a laptop) or
    MCC_KAFKA_CA_PEM_TEXT (the PEM itself, in the CAI project environment)."""
    path = os.path.expanduser(os.environ.get("MCC_KAFKA_CA_PEM", ""))
    if path and os.path.exists(path):
        return path
    text = os.environ.get("MCC_KAFKA_CA_PEM_TEXT")
    if text:
        out = Path("/tmp/mcc-ca.pem")
        out.write_text(text)
        return str(out)
    return None


def create_topics(check_only: bool = False) -> dict:
    from kafka.admin import KafkaAdminClient, NewTopic
    from kafka.errors import TopicAlreadyExistsError

    admin = KafkaAdminClient(**kafka_config())
    existing = set(admin.list_topics())
    out = {}
    for t in all_topics().values():
        if t["name"] in existing:
            out[t["name"]] = "EXISTS"
            continue
        if check_only:
            out[t["name"]] = "MISSING"
            continue
        try:
            replication = int(os.environ.get("MCC_TOPIC_REPLICATION", t["replication"]))  # 1 on a dev broker
            admin.create_topics([NewTopic(t["name"], t["partitions"], replication,
                                          topic_configs={"retention.ms": str(t["retention_hours"] * 3600_000)})])
            out[t["name"]] = "CREATED"
        except TopicAlreadyExistsError:
            out[t["name"]] = "EXISTS"
    admin.close()
    return out


def register_schemas() -> dict:
    """Register each Avro schema under the topic name (Cloudera Schema Registry REST v1 via Knox)."""
    import requests

    base = os.environ["MCC_SCHEMA_REGISTRY_URL"].rstrip("/")
    auth = (os.environ["MCC_WORKLOAD_USER"], os.environ["MCC_WORKLOAD_PASSWORD"])
    verify = True
    ca = ca_file()
    if ca:   # Knox may present a public chain or the environment's own CA: trust both
        import certifi

        bundle = Path("/tmp/mcc-ca-bundle.pem")
        bundle.write_text(Path(certifi.where()).read_text() + "\n" + Path(ca).read_text())
        verify = str(bundle)
    out = {}
    for key, fname in SCHEMAS.items():
        topic = all_topics()[key]["name"]
        text = (ROOT / "stream" / "schemas" / fname).read_text()
        meta = {"type": "avro", "schemaGroup": "Kafka", "name": topic, "description": f"MCC {key} message contract",
                "compatibility": "BACKWARD", "validationLevel": "ALL"}
        r = requests.post(f"{base}/schemaregistry/schemas", json=meta, auth=auth, verify=verify, timeout=30)
        if r.status_code not in (200, 201, 409):
            r.raise_for_status()
        r = requests.post(f"{base}/schemaregistry/schemas/{topic}/versions", auth=auth, verify=verify, timeout=30,
                          json={"schemaText": text, "description": "registered by stream/producer/topics.py"})
        if r.status_code in (200, 201):
            out[topic] = f"version id {r.text.strip()}"
        else:
            out[topic] = f"HTTP {r.status_code}: {r.text[:200]}"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--create-topics", action="store_true")
    ap.add_argument("--register-schemas", action="store_true")
    ap.add_argument("--check", action="store_true")
    args, _ = ap.parse_known_args(argv)
    if args.create_topics or args.check:
        print("topics:", create_topics(check_only=args.check), flush=True)
    if args.register_schemas:
        print("schemas:", register_schemas(), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
