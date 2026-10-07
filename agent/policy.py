"""Versioned response policy shared by live calls and evaluation candidates."""
from __future__ import annotations

import json
import os
from pathlib import Path
from string import Formatter

POLICY_FIELDS = {
    "system_addendum": set(),
    "emergency_response": set(),
    "availability_error": {"error"},
    "no_slots": {"department"},
    "booking_error": {"error"},
}
DEFAULT_POLICY = Path(__file__).parent / "policies" / "baseline.json"


def load_policy(path: str | Path | None = None) -> dict[str, str]:
    source = Path(path or os.getenv("CLINICFLOW_POLICY_PATH") or DEFAULT_POLICY)
    policy = json.loads(source.read_text())
    if not isinstance(policy, dict) or set(policy) != set(POLICY_FIELDS):
        raise ValueError("policy must contain exactly the supported response fields")
    for key, value in policy.items():
        if not isinstance(value, str) or len(value) > 12000:
            raise ValueError(f"invalid policy text for {key}")
        placeholders = {name for _, name, _, _ in Formatter().parse(value) if name is not None}
        if not placeholders <= POLICY_FIELDS[key]:
            raise ValueError(f"unsupported template placeholder in {key}")
    return policy
