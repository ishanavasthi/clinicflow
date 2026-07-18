"""Call records and their timeline events.

The agent creates a call when it joins a room, appends timeline events as tools
fire (a durable copy of what it also streams to the dashboard over the data
channel), and marks the call ended on hang-up.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from db import get_session
from models import Call, TimelineEvent

router = APIRouter(prefix="/calls", tags=["calls"])


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
