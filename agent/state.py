"""Call state and the agent-state publisher.

The agent publishes a JSON message on the room data channel on every tool call
and phase change. That schema is the single dashboard contract and must stay
mirrored in web/lib/types.ts. Implemented in M2.

Event shape:
    {
      "type": "status" | "intake_update" | "faq" | "booking" | "routing" | "timeline",
      "call_id": str,
      "ts": int,
      "payload": dict,
    }
"""
from __future__ import annotations

DATA_TOPIC = "agent-state"
