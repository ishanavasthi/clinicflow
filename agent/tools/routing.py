"""route_to_department: mark the call as routed to a department."""
from __future__ import annotations

import unicodedata

from state import AgentStatePublisher, CallState
from server_client import ServerClient
from tools.intake import apply_intake

DEPARTMENTS = {
    "emergency": "Emergency",
    "general medicine": "General Medicine",
    "pediatrics": "Pediatrics",
    "orthopedics": "Orthopedics",
    "cardiology": "Cardiology",
}

# Hindi names the model may pass in a Hindi call. Kept apart from DEPARTMENTS so
# the English error message and lookups are unchanged; no key here is English.
HINDI_DEPARTMENTS = {
    "आपातकालीन": "Emergency", "आपातकाल": "Emergency", "इमरजेंसी": "Emergency",
    "इमर्जेंसी": "Emergency", "emergency ward": "Emergency",
    "सामान्य चिकित्सा": "General Medicine", "जनरल मेडिसिन": "General Medicine",
    "बाल रोग": "Pediatrics", "बाल चिकित्सा": "Pediatrics", "शिशु रोग": "Pediatrics",
    "हड्डी रोग": "Orthopedics", "ऑर्थोपेडिक्स": "Orthopedics", "अस्थि रोग": "Orthopedics",
    "हृदय रोग": "Cardiology", "कार्डियोलॉजी": "Cardiology", "दिल": "Cardiology",
}


def hindi_department(name: str) -> str | None:
    key = unicodedata.normalize("NFC", name.strip().lower())
    return HINDI_DEPARTMENTS.get(key)


def _canonical(name: str) -> str | None:
    return DEPARTMENTS.get(name.strip().lower()) or hindi_department(name)


async def route_to_department(
    state: CallState,
    server: ServerClient,
    publisher: AgentStatePublisher,
    department: str,
    reason: str,
) -> dict:
    canonical = _canonical(department)
    if canonical is None:
        return {
            "ok": False,
            "error": f"unknown department '{department}'; valid: {', '.join(DEPARTMENTS.values())}",
        }

    if canonical == "Emergency":
        state.emergency = True
        state.offered_slots = []
        state.selection_evidence = None
    elif state.emergency:
        return {"ok": False, "error": "Emergency escalation is active; routine routing is disabled"}
    elif state.offered_department != canonical:
        state.offered_slots = []
        state.selection_evidence = None

    # Backstop: the routing reason is the caller's symptom. If the model routed
    # without recording it, capture it in intake now so the panel is not left blank.
    if reason and not state.intake.get("symptoms"):
        await apply_intake(state, server, publisher, "symptoms", reason)

    state.routed_department = canonical
    state.status = "routing"
    emergency = canonical == "Emergency"
    await publisher.publish(
        "routing", {"department": canonical, "reason": reason, "emergency": emergency}
    )
    return {"ok": True, "data": {"department": canonical, "emergency": emergency}}
