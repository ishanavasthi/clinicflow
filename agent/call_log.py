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


def build_record(
    state: CallState,
    chat_ctx: Any,
    started_at: datetime,
    ended_at: datetime,
) -> dict:
    """Build the full call record (patient details, outcome, transcript)."""
    return {
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
        },
        "routed_department": state.routed_department,
        "booking": state.booking,
        "transcript": _transcript(chat_ctx),
    }


def write_record(record: dict) -> str:
    """Write a call record to a JSON file under runs/calls/ and return its path."""
    os.makedirs(RUNS_CALLS_DIR, exist_ok=True)
    safe_room = (record.get("room") or "call").replace("/", "-")
    ended = record.get("ended_at", "")  # ISO, e.g. 2026-07-18T23:15:36.123
    stamp = f"{ended[:10].replace('-', '')}-{ended[11:19].replace(':', '')}" if ended else "record"
    filename = f"{safe_room}_{stamp}.json"
    path = os.path.join(RUNS_CALLS_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    return path


def summary_of(record: dict) -> dict:
    """A compact summary of a call record for the history list."""
    return {
        "name": record["patient"]["name"],
        "age": record["patient"]["age"],
        "phone": record["patient"]["phone"],
        "symptom": record["patient"]["symptoms"],
        "booking": record["booking"],
        "routed_department": record["routed_department"],
    }
