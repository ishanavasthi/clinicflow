"""Call state and the agent-state publisher.

Every tool call and phase change publishes a JSON event to the room data channel
(topic "agent-state") for the live dashboard, and appends the same event to the
server timeline for durability. That event schema is the single dashboard
contract and must stay mirrored in web/lib/types.ts.

Event shape:
    {"type": "status" | "intake_update" | "faq" | "booking" | "routing",
     "call_id": str, "ts": int (ms), "payload": dict}
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from livekit import rtc

from server_client import ServerClient

logger = logging.getLogger("clinicflow-agent")

DATA_TOPIC = "agent-state"

# Intake fields the receptionist collects, in the order it should ask for them.
INTAKE_FIELDS = ["name", "dob", "phone", "symptoms", "insurance"]


@dataclass
class CallState:
    call_id: Optional[int] = None
    room_name: str = ""
    patient_id: Optional[int] = None
    intake: dict = field(default_factory=dict)
    offered_slots: dict = field(default_factory=dict)  # slot_id -> slot option
    status: str = "active"
    routed_department: Optional[str] = None
    booking: Optional[dict] = None

    def missing_intake(self) -> list[str]:
        return [f for f in INTAKE_FIELDS if f not in self.intake]


class AgentStatePublisher:
    """Publishes agent-state events to both the live data channel and the
    durable server timeline. Both sends are best-effort: a failure is logged but
    never propagates, so persistence problems cannot interrupt the conversation.
    """

    def __init__(
        self, room: rtc.Room, state: CallState, server: ServerClient
    ) -> None:
        self.room = room
        self.state = state
        self.server = server

    async def publish(self, type: str, payload: dict) -> None:
        event = {
            "type": type,
            "call_id": str(self.state.call_id) if self.state.call_id else None,
            "ts": int(time.time() * 1000),
            "payload": payload,
        }
        data = json.dumps(event).encode("utf-8")
        try:
            await self.room.local_participant.publish_data(data, topic=DATA_TOPIC)
        except Exception as exc:  # noqa: BLE001 (best-effort by design)
            logger.warning("data channel publish failed: %s", exc)

        if self.state.call_id is not None:
            try:
                await self.server.add_event(self.state.call_id, type, payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning("timeline persist failed: %s", exc)
