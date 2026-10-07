"""update_intake: record one patient detail and persist it live."""
from __future__ import annotations

import re

from state import INTAKE_FIELDS, AgentStatePublisher, CallState
from server_client import ServerClient

VALID_FIELDS = set(INTAKE_FIELDS)

# Map the wordings the model actually uses to the canonical intake fields, so a
# singular "symptom" or a "phone number" is never silently dropped (which, with the
# intake-complete gate on booking, would otherwise block the call).
_FIELD_ALIASES = {
    "name": "name", "full name": "name", "fullname": "name", "full_name": "name",
    "age": "age",
    "phone": "phone", "phone number": "phone", "phone_number": "phone",
    "mobile": "phone", "number": "phone", "contact": "phone",
    "symptom": "symptoms", "symptoms": "symptoms", "reason": "symptoms",
    "reason/symptoms": "symptoms", "complaint": "symptoms",
}


def _canonical_field(field: str) -> str:
    key = field.strip().lower()
    return _FIELD_ALIASES.get(key, key)


def _normalize(field: str, value: str) -> str:
    """Clean a value before storing. The LLM is asked to normalize too; this is a
    safety net so a phone always lands as a 10-digit Indian mobile number."""
    value = value.strip()
    if field == "phone":
        digits = re.sub(r"\D", "", value)
        if len(digits) > 10 and digits.startswith("91"):
            digits = digits[-10:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        return digits or value
    return value


async def apply_intake(
    state: CallState,
    server: ServerClient,
    publisher: AgentStatePublisher,
    field: str,
    value: str,
) -> dict:
    field = _canonical_field(field)
    if field not in VALID_FIELDS:
        return {"ok": False, "error": f"'{field}' is not a valid intake field"}

    value = _normalize(field, value)
    if not value:
        return {"ok": False, "error": "a supplied nonblank value is required"}
    if field == "phone" and not re.fullmatch(r"[6-9][0-9]{9}", value):
        return {"ok": False, "error": "ask for a valid 10-digit Indian mobile number"}
    if field == "age" and (not value.isdigit() or not 0 <= int(value) <= 120):
        return {"ok": False, "error": "ask for age in whole years between 0 and 120"}
    previous = state.intake.get(field)

    try:
        if state.patient_id is None:
            patient = await server.create_patient(**{field: value})
            state.patient_id = patient["id"]
        else:
            await server.update_patient(state.patient_id, **{field: value})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"could not save {field}: {exc}"}

    state.intake[field] = value
    if previous != value and state.status != "booking_uncertain":
        state.offered_slots = []
        state.offered_department = None
        state.selection_evidence = None

    await publisher.publish(
        "intake_update",
        {
            "field": field,
            "value": value,
            "intake": state.intake,
            "patient_id": state.patient_id,
        },
    )
    return {
        "ok": True,
        "data": {"field": field, "collected": list(state.intake), "missing": state.missing_intake()},
    }
