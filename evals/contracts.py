"""Small JSON contracts shared by execution, scoring and improvement tooling.

Artifacts are plain dictionaries so archived evidence can be inspected without
installing the voice stack. Runtime validation rejects incomplete evidence.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA_VERSION = 1
CATEGORIES = {"outcome": 30, "state": 25, "safety": 20, "recovery": 15, "conversation": 10}


def content_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_run(run: dict) -> None:
    for key in ("schema_version", "run_id", "scenario_id", "trial", "mode", "status", "manifest", "events", "final_state"):
        if key not in run:
            raise ValueError(f"run missing {key}")
    if run["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported run schema")
    if run["mode"] not in ("live", "scripted"):
        raise ValueError("mode must distinguish live model runs from scripted checks")
    if run["status"] not in ("completed", "agent_error", "patient_error", "blocked", "budget_stopped"):
        raise ValueError("invalid run status")
    ids = [event["id"] for event in run["events"]]
    if len(ids) != len(set(ids)):
        raise ValueError("event IDs must be unique")


def validate_scorecard(card: dict) -> None:
    for key in ("run_id", "scenario_id", "score", "passed", "criteria", "critical_failures", "evaluator_errors"):
        if key not in card:
            raise ValueError(f"scorecard missing {key}")
    if not isinstance(card["score"], (int, float)) or not 0 <= card["score"] <= 100:
        raise ValueError("score must be between 0 and 100")
    if card["passed"] and (card["critical_failures"] or card["evaluator_errors"]):
        raise ValueError("critical/evaluator failures cannot pass")
