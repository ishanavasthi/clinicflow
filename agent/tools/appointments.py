"""check_availability and book_appointment: read seeded slots and book one."""
from __future__ import annotations

from datetime import datetime

from state import AgentStatePublisher, CallState
from server_client import ServerClient


def format_slot_time(iso: str) -> str:
    """Turn an ISO timestamp into a natural spoken label like
    'Saturday, July 19 at 9:30 in the morning'.

    Uses 'in the morning/afternoon/evening' instead of AM/PM: it reads
    conversationally, and it avoids the TTS voicing the meridiem twice for a
    colon time like '9:30 AM'.
    """
    dt = datetime.fromisoformat(iso)
    hour12 = dt.hour % 12 or 12
    clock = f"{hour12}" if dt.minute == 0 else f"{hour12}:{dt.minute:02d}"
    if dt.hour < 12:
        period = "in the morning"
    elif dt.hour < 17:
        period = "in the afternoon"
    else:
        period = "in the evening"
    return f"{dt.strftime('%A, %B %-d')} at {clock} {period}"


async def check_availability(
    state: CallState,
    server: ServerClient,
    publisher: AgentStatePublisher,
    department: str,
) -> dict:
    try:
        slots = await server.availability(department, limit=3)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"could not check availability: {exc}"}

    if not slots:
        await publisher.publish(
            "booking", {"phase": "availability", "department": department, "slots": []}
        )
        return {"ok": True, "data": {"slots": [], "department": department}}

    state.offered_slots = {s["slot_id"]: s for s in slots}
    labelled = [
        {
            "slot_id": s["slot_id"],
            "doctor": s["doctor"],
            "when": format_slot_time(s["start"]),
            "start": s["start"],
        }
        for s in slots
    ]
    await publisher.publish(
        "booking",
        {"phase": "availability", "department": department, "slots": labelled},
    )
    return {"ok": True, "data": {"slots": labelled, "department": department}}


async def book_appointment(
    state: CallState,
    server: ServerClient,
    publisher: AgentStatePublisher,
    slot_id: int,
    reason: str = "",
) -> dict:
    if state.patient_id is None:
        return {"ok": False, "error": "collect the patient's name first"}

    reason = reason or state.intake.get("symptoms", "")
    try:
        appointment = await server.book(state.patient_id, slot_id, reason)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"booking failed: {exc}"}

    state.status = "booked"
    appointment["when"] = format_slot_time(appointment["start"])
    state.booking = appointment
    await publisher.publish("booking", {"phase": "confirmed", "appointment": appointment})
    return {"ok": True, "data": appointment}
