"""update_intake: record one patient detail and persist it live."""
from __future__ import annotations

from state import INTAKE_FIELDS, AgentStatePublisher, CallState
from server_client import ServerClient

VALID_FIELDS = set(INTAKE_FIELDS)


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

    state.intake[field] = value.strip()

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
