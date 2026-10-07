"""Bounded synthetic patient policies; unknown questions fail visibly."""
from __future__ import annotations

import re


class PatientPolicyError(RuntimeError):
    pass


class ScriptedPatient:
    def __init__(self, scenario: dict):
        self.policy = scenario.get("policy") or {}
        self.used: set[str] = set()

    def reply(self, assistant_text: str, offered_slots: list[dict]) -> str | None:
        stop = self.policy.get("stop_after")
        if stop and re.search(stop, assistant_text, re.IGNORECASE):
            return None
        for index, rule in enumerate(self.policy.get("rules", [])):
            rule_id = str(rule.get("id", index))
            if rule.get("once", True) and rule_id in self.used:
                continue
            pattern = rule.get("match") or rule.get("when")
            if not pattern or not re.search(pattern, assistant_text, re.IGNORECASE):
                continue
            self.used.add(rule_id)
            answer = rule.get("reply")
            if answer == "__FIRST_OFFERED_TIME__":
                if not offered_slots:
                    raise PatientPolicyError("asked to choose a slot before any actual slot was offered")
                return f"The first time, {offered_slots[0]['when']}, please. Please book it."
            if answer is None:
                return None
            return str(answer)
        fallback = self.policy.get("fallback")
        if fallback is not None:
            return str(fallback)
        raise PatientPolicyError(f"no patient rule matched assistant turn: {assistant_text!r}")
