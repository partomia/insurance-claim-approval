"""
Job mcc-07-promote-champion (manual): a named person moves the Copilot's model mode, with
evidence, and the decision is recorded. Process guardrail "named approver".

Modes (models/champion/serving_mode.json, read by the app's approval_model_service.py):
  off      the model is not called
  shadow   scored and shown to the adjuster/insurer next to the rules decision (the default)
  assist   also ranks the review queue (fraud score first); still never approves or rejects

Run environment: MCC_APPROVER (required, a name or e-mail), MCC_TARGET_MODE (off | shadow | assist),
MCC_REASON (free text). Moving to assist needs, from gold.fact_model_score (mcc-06):
  at least promotion.min_scored shadow scores of the serving champion, and
  agreement with the decisions made >= promotion.min_agreement (config/guardrails.yaml)
and the champion's own gate result. Otherwise PROMOTION_REFUSED with the evidence found;
PROMOTED otherwise. Going back to shadow or off needs only the name.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except NameError:  # CAI job kernels run the script without __file__; cwd is the project
        return Path(os.getcwd())


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))

from common import finish, load_config  # noqa: E402

MODES = ("off", "shadow", "assist")


def mode_file(cfg: dict) -> Path:
    return ROOT / cfg["serving"]["champion_dir"] / "serving_mode.json"


def evidence(version: str) -> dict:
    if not os.environ.get("MCC_IMPALA_USER"):
        return {"scored": 0, "compared": 0, "agreement": None, "source": "no lakehouse connection"}
    from lakehouse.store import ImpalaStore

    s = ImpalaStore()
    t = s.t("gold.fact_model_score")
    r = s.query(f"SELECT COUNT(*) AS scored, SUM(CASE WHEN agrees_with_rules IS NOT NULL THEN 1 ELSE 0 END) AS compared, "
                f"SUM(CASE WHEN agrees_with_rules THEN 1 ELSE 0 END) AS agreed FROM {t} "
                f"WHERE approval_version = '{version}'")[0]
    compared = int(r["compared"] or 0)
    return {"scored": int(r["scored"] or 0), "compared": compared,
            "agreement": round(int(r["agreed"] or 0) / compared, 4) if compared else None, "source": t}


def decide(target: str, approver: str, gate: dict, ev: dict, rules: dict) -> list[str]:
    """Reasons to refuse; empty means promote."""
    why = []
    if not approver:
        why.append("no MCC_APPROVER: a named person must approve")
    if target not in MODES:
        why.append(f"unknown mode {target!r}: one of {MODES}")
    if target == "assist":
        if not gate.get("passed"):
            why.append("champion has no passing gate result")
        if ev["scored"] < rules["min_scored"]:
            why.append(f"{ev['scored']} shadow scores < {rules['min_scored']}")
        if ev["agreement"] is None or ev["agreement"] < rules["min_agreement"]:
            why.append(f"agreement {ev['agreement']} < {rules['min_agreement']} on {ev['compared']} decided claims")
    return why


def main() -> int:
    from guardrails.input_checks import config as guard_config
    from lakehouse.publish import publish_model_event

    cfg = load_config(model="approval")
    champ = ROOT / cfg["serving"]["champion_dir"]
    meta = json.loads((champ / "model_meta.json").read_text())
    gate = json.loads((champ / "gate_result.json").read_text()) if (champ / "gate_result.json").exists() else {}
    approver, target = os.environ.get("MCC_APPROVER", "").strip(), os.environ.get("MCC_TARGET_MODE", "shadow").strip()
    current = json.loads(mode_file(cfg).read_text())["mode"] if mode_file(cfg).exists() else "shadow"
    ev = evidence(meta["model_version"]) if target == "assist" else {"scored": None, "compared": None,
                                                                     "agreement": None, "source": "not needed"}
    why = decide(target, approver, gate, ev, guard_config()["promotion"])
    detail = json.dumps({"from": current, "to": target, "evidence": ev, "reason": os.environ.get("MCC_REASON", "")})
    if why:
        print("PROMOTION_REFUSED: " + "; ".join(why), flush=True)
        publish_model_event("PROMOTION_REFUSED", meta, gate, stage="champion", approved_by=approver or None,
                            detail="; ".join(why) + " | " + detail)
        return 1
    mode_file(cfg).write_text(json.dumps({"mode": target, "approved_by": approver,
                                          "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                          "model_version": meta["model_version"], "evidence": ev}, indent=2))
    print(f"PROMOTED: {current} -> {target} by {approver}", flush=True)
    publish_model_event("PROMOTED", meta, gate, stage="champion", approved_by=approver, detail=detail)
    return 0


if __name__ == "__main__":
    finish(main())
