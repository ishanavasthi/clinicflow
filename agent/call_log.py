"""Persist a JSON record of each call to runs/calls/.

Written at call end: the collected patient details, booking, routing, and the
full chat transcript, so a session can be reviewed later.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from state import CallState

RUNS_CALLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs", "calls"
)


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    # content is a list of parts; keep the string (text) parts.
    return " ".join(part for part in content if isinstance(part, str)).strip()


def _transcript(chat_ctx: Any) -> list[dict]:
    transcript: list[dict] = []
    for item in getattr(chat_ctx, "items", []):
        role = getattr(item, "role", None)
        if role not in ("user", "assistant"):
            continue
        text = _content_to_text(getattr(item, "content", None))
        if text:
            transcript.append({"role": role, "text": text})
    return transcript


def write_call_record(
    state: CallState,
    chat_ctx: Any,
    started_at: datetime,
    ended_at: datetime,
) -> str:
    """Write the call as a JSON file under runs/calls/ and return its path."""
    os.makedirs(RUNS_CALLS_DIR, exist_ok=True)
    record = {
        "call_id": state.call_id,
        "room": state.room_name,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "patient": {
            "id": state.patient_id,
            "name": state.intake.get("name"),
            "age": state.intake.get("age"),
            "phone": state.intake.get("phone"),
            "symptoms": state.intake.get("symptoms"),
            "insurance": state.intake.get("insurance"),
        },
        "routed_department": state.routed_department,
        "booking": state.booking,
        "transcript": _transcript(chat_ctx),
    }
    safe_room = (state.room_name or "call").replace("/", "-")
    filename = f"{safe_room}_{ended_at.strftime('%Y%m%d-%H%M%S')}.json"
    path = os.path.join(RUNS_CALLS_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    return path
