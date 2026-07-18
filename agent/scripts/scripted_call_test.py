"""Scripted-call verification for M2.

Drives the real tool helpers (intake -> availability -> booking) against a
running ClinicFlow server, bypassing the LLM and voice pipeline, and asserts a
real appointment row lands in SQLite with the slot flipped to booked and the
agent-state events recorded on the call timeline.

Run against a server started with CLINICFLOW_API_URL pointing at it.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server_client import ServerClient
from state import AgentStatePublisher, CallState
from tools.appointments import book_appointment, check_availability
from tools.intake import apply_intake


class _FakeLocalParticipant:
    def __init__(self, sink: list) -> None:
        self._sink = sink

    async def publish_data(self, payload: bytes, topic: str = "", **_: object) -> None:
        self._sink.append((topic, payload))


class _FakeRoom:
    def __init__(self, sink: list) -> None:
        self.local_participant = _FakeLocalParticipant(sink)


async def main() -> None:
    server = ServerClient()
    published: list = []

    call = await server.create_call("call-scripted")
    state = CallState(call_id=call["id"], room_name="call-scripted")
    publisher = AgentStatePublisher(_FakeRoom(published), state, server)

    # 1. Intake, one detail at a time (name, age, phone, symptoms).
    for field, value in [
        ("name", "Priya Sharma"),
        ("age", "34"),
        ("phone", "+91 98200 12345"),
        ("symptoms", "knee pain for two weeks"),
    ]:
        r = await apply_intake(state, server, publisher, field, value)
        assert r["ok"], r
    assert state.patient_id is not None, "patient was not created"
    print(f"intake OK  -> patient_id={state.patient_id}, collected={list(state.intake)}")

    # 2. Availability.
    r = await check_availability(state, server, publisher, "Orthopedics")
    assert r["ok"] and r["data"]["slots"], r
    chosen = r["data"]["slots"][0]
    print(f"availability OK -> {len(r['data']['slots'])} slots, choosing slot {chosen['slot_id']} ({chosen['when']})")

    # 3. Book.
    r = await book_appointment(state, server, publisher, chosen["slot_id"], "knee pain")
    assert r["ok"], r
    appt = r["data"]
    print(f"booking OK -> appointment_id={appt['appointment_id']}, {appt['doctor']}, {appt['department']}, {appt['when']}")

    # 4. Independent verification via the server (durable SQLite state).
    appts = await server._json("GET", "/appointments")
    assert any(a["id"] == appt["appointment_id"] for a in appts), "appointment not persisted"

    remaining = await server.availability("Orthopedics", limit=5)
    assert chosen["slot_id"] not in [s["slot_id"] for s in remaining], "slot not marked booked"

    events = await server._json("GET", f"/calls/{state.call_id}/events")
    types = [e["type"] for e in events]
    print(f"persistence OK -> appointment in SQLite, slot booked, timeline events={types}")

    # 5. Confirm live events were emitted on the (fake) data channel too.
    assert len(published) == len(events), (len(published), len(events))
    print(f"data channel OK -> {len(published)} events published live")

    await server.aclose()
    print("\nSCRIPTED CALL PASSED: a real appointment row was booked end to end.")


if __name__ == "__main__":
    asyncio.run(main())
