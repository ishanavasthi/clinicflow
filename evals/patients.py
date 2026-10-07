"""Bounded synthetic patient policies.

A patient answers from three sources, in order:

1. Facts. When the agent asks for a detail the patient has (name, age, phone,
   symptoms, department), the patient gives it, or confirms it when the agent
   reads it back. Real callers repeat themselves; re-asking is the agent's
   cost, scored under clarity, not a simulator failure. A fact with an empty
   value is never volunteered, so withheld details stay withheld and are
   handled by scenario rules.
2. Scenario rules, checked in order against the latest assistant message.
3. The scenario fallback. Without one, the patient ends the call and the runner
   records the unmatched assistant turn. Ending never helps the agent: a
   booking scenario that ends early fails its outcome check.

Patient policies know only synthetic facts and intent. They never see the
evaluator's expectations.
"""
from __future__ import annotations

import re


class PatientPolicyError(RuntimeError):
    pass


SLOT_OFFER = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b|\b\d{1,2}:\d{2}\b",
    re.IGNORECASE,
)

FACT_QUESTIONS = {
    "name": re.compile(r"\bname\b", re.IGNORECASE),
    "age": re.compile(r"\bage\b|how old", re.IGNORECASE),
    "phone": re.compile(r"phone|mobile|contact number|\bnumber\b", re.IGNORECASE),
    "symptoms": re.compile(r"symptom|reason|what brings|concern|problem|complaint|describe|experienc|"
                           r"tell me (?:a bit |a little |more )?about|what.{0,20}(?:wrong|issue)", re.IGNORECASE),
    "department": re.compile(r"department|specialt", re.IGNORECASE),
    "timing": re.compile(r"\bdate\b|which day|what day|when would you|when do you|when are you|"
                         r"preferred time|what time|time of day|morning or", re.IGNORECASE),
}
# A patient with no stated timing preference is flexible and asks for real times.
DEFAULT_TIMING = "Any day works. Please tell me the available times."

REPEAT_REQUEST = re.compile(r"say that again|repeat that|didn.t catch|come again", re.IGNORECASE)
CONFIRMATION = re.compile(r"confirm|correct|right\?|is that", re.IGNORECASE)
# A patient repeats their slot choice if the agent re-offers, up to this many times.
MAX_SLOT_CHOICES = 3

FACT_ANSWERS = {
    "name": "My name is {}.",
    "age": "I am {}.",
    "phone": "My phone number is {}.",
    "symptoms": "It is for {}.",
    "department": "I need {}.",
    "timing": "{}",
}


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


class ScriptedPatient:
    def __init__(self, scenario: dict):
        self.policy = scenario.get("policy") or {}
        self.facts = {k: str(v) for k, v in (scenario.get("patient") or {}).items() if str(v or "").strip()}
        self.facts.setdefault("timing", DEFAULT_TIMING)
        self.used: set[str] = set()
        self.slot_choices = 0
        self.last_reply: str | None = None
        self.unmatched: str | None = None

    def _fact_reply(self, text: str) -> str | None:
        if SLOT_OFFER.search(text) or "?" not in text and not re.search(r"\b(?:please|share|provide|tell me)\b", text, re.IGNORECASE):
            return None
        asked = [field for field, pattern in FACT_QUESTIONS.items() if field in self.facts and pattern.search(text)]
        if not asked:
            return None
        if CONFIRMATION.search(text) and "timing" not in asked and all(self._read_back(text, field) for field in asked):
            return "Yes, that's right."
        return " ".join(FACT_ANSWERS[field].format(self.facts[field]) for field in asked)

    def _read_back(self, text: str, field: str) -> bool:
        value = self.facts[field]
        if field == "phone":
            return len(_digits(value)) >= 7 and _digits(value) in _digits(text)
        return value.casefold() in text.casefold()

    def reply(self, assistant_text: str, offered_slots: list[dict]) -> str | None:
        answer = self._reply(assistant_text, offered_slots)
        if answer is not None:
            self.last_reply = answer
        return answer

    def _reply(self, assistant_text: str, offered_slots: list[dict]) -> str | None:
        stop = self.policy.get("stop_after")
        if stop and re.search(stop, assistant_text, re.IGNORECASE):
            return None
        # A caller asked to repeat themselves does, once per request.
        if REPEAT_REQUEST.search(assistant_text) and self.last_reply:
            return self.last_reply
        fact = self._fact_reply(assistant_text)
        if fact is not None:
            return fact
        for index, rule in enumerate(self.policy.get("rules", [])):
            rule_id = str(rule.get("id", index))
            answer = rule.get("reply")
            choosing = answer == "__FIRST_OFFERED_TIME__"
            # Slot choices repeat when the agent re-offers; other rules answer once.
            if rule.get("once", True) and rule_id in self.used and not choosing:
                continue
            pattern = rule.get("match") or rule.get("when")
            if not pattern or not re.search(pattern, assistant_text, re.IGNORECASE):
                continue
            if choosing:
                # Times spoken without a real availability result cannot be
                # chosen; the judge and state checks see any fabricated slot.
                if not offered_slots or self.slot_choices >= MAX_SLOT_CHOICES:
                    continue
                self.used.add(rule_id)
                self.slot_choices += 1
                return f"The first time, {offered_slots[0]['when']}, please. Please book it."
            self.used.add(rule_id)
            if answer is None:
                return None
            return str(answer)
        fallback = self.policy.get("fallback")
        if fallback is not None:
            return str(fallback)
        self.unmatched = assistant_text
        return None
