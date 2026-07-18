"""route_to_department: mark the call as routed to a department."""
from __future__ import annotations

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


def _canonical(name: str) -> str | None:
    return DEPARTMENTS.get(name.strip().lower())


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
