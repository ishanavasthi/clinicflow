"""update_intake: record one patient detail and persist it live."""
from __future__ import annotations

import re

from state import INTAKE_FIELDS, AgentStatePublisher, CallState
from server_client import ServerClient

VALID_FIELDS = set(INTAKE_FIELDS)


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
    field = field.strip().lower()
    if field not in VALID_FIELDS:
        return {"ok": False, "error": f"'{field}' is not a valid intake field"}

    value = _normalize(field, value)
    state.intake[field] = value

    try:
        if state.patient_id is None:
            patient = await server.create_patient(**{field: value})
            state.patient_id = patient["id"]
        else:
            await server.update_patient(state.patient_id, **{field: value})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"could not save {field}: {exc}"}

    await publisher.publish(
        "intake_update",
        {"field": field, "value": value, "intake": state.intake},
    )
    return {
        "ok": True,
        "data": {"field": field, "collected": list(state.intake), "missing": state.missing_intake()},
    }
