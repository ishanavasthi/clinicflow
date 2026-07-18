"""Call records and their timeline events.

The agent creates a call when it joins a room, appends timeline events as tools
fire (a durable copy of what it also streams to the dashboard over the data
channel), and marks the call ended on hang-up.
"""
from __future__ import annotations

import glob
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from db import get_session
from models import Call, TimelineEvent

router = APIRouter(prefix="/calls", tags=["calls"])

# Recordings are run artifacts, kept under the gitignored runs/ directory.
_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDINGS_DIR = os.path.normpath(
    os.path.join(_SERVER_DIR, "..", "runs", "recordings")
)
_EXT_BY_TYPE = {
    "audio/webm": "webm",
    "audio/mp4": "mp4",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
}
_TYPE_BY_EXT = {v: k for k, v in _EXT_BY_TYPE.items()}


class CallCreate(BaseModel):
    room: str


class EventCreate(BaseModel):
    type: str
    payload: dict = {}


class CallEnd(BaseModel):
    routed_department: Optional[str] = None
    recording_url: Optional[str] = None


@router.post("", response_model=Call)
def create_call(body: CallCreate, session: Session = Depends(get_session)) -> Call:
    call = Call(room=body.room)
    session.add(call)
    session.commit()
    session.refresh(call)
    return call


@router.get("", response_model=list[Call])
def list_calls(session: Session = Depends(get_session)) -> list[Call]:
    return session.exec(select(Call).order_by(Call.started_at.desc())).all()


@router.get("/{call_id}", response_model=Call)
def get_call(call_id: int, session: Session = Depends(get_session)) -> Call:
    call = session.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return call


@router.post("/{call_id}/events", response_model=TimelineEvent)
def add_event(
    call_id: int,
    body: EventCreate,
    session: Session = Depends(get_session),
) -> TimelineEvent:
    if session.get(Call, call_id) is None:
        raise HTTPException(status_code=404, detail="Call not found")
    event = TimelineEvent(call_id=call_id, type=body.type, payload=body.payload)
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.get("/{call_id}/events", response_model=list[TimelineEvent])
def list_call_events(
    call_id: int, session: Session = Depends(get_session)
) -> list[TimelineEvent]:
    return session.exec(
        select(TimelineEvent)
        .where(TimelineEvent.call_id == call_id)
        .order_by(TimelineEvent.ts)
    ).all()


@router.post("/{call_id}/recording")
async def upload_recording(
    call_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """Store the call recording (raw audio blob in the request body)."""
    call = session.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")

    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Empty recording")

    content_type = (request.headers.get("content-type") or "audio/webm").split(";")[0].strip()
    ext = _EXT_BY_TYPE.get(content_type, "webm")
    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    # Replace any earlier take for this call.
    for old in glob.glob(os.path.join(RECORDINGS_DIR, f"call-{call_id}.*")):
        os.remove(old)
    path = os.path.join(RECORDINGS_DIR, f"call-{call_id}.{ext}")
    with open(path, "wb") as f:
        f.write(data)

    call.recording_url = f"/calls/{call_id}/recording"
    session.add(call)
    session.commit()
    return {"recording_url": call.recording_url, "bytes": len(data)}


@router.get("/{call_id}/recording")
def get_recording(call_id: int):
    matches = glob.glob(os.path.join(RECORDINGS_DIR, f"call-{call_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="No recording for this call")
    path = matches[0]
    ext = path.rsplit(".", 1)[-1].lower()
    media_type = _TYPE_BY_EXT.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@router.post("/{call_id}/end", response_model=Call)
def end_call(
    call_id: int,
    body: CallEnd,
    session: Session = Depends(get_session),
) -> Call:
    call = session.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")
    call.status = "ended"
    call.ended_at = datetime.utcnow()
    if body.routed_department is not None:
        call.routed_department = body.routed_department
    if body.recording_url is not None:
        call.recording_url = body.recording_url
    session.add(call)
    session.commit()
    session.refresh(call)
    return call
