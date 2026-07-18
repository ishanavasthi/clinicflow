"""Call records and their timeline events.

M0 provides create/read so a caller session can register a room. Recording
upload and richer event streaming are fleshed out in later milestones.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from db import get_session
from models import Call, TimelineEvent

router = APIRouter(prefix="/calls", tags=["calls"])


class CallCreate(BaseModel):
    room: str


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


@router.get("/{call_id}/events", response_model=list[TimelineEvent])
def list_call_events(
    call_id: int, session: Session = Depends(get_session)
) -> list[TimelineEvent]:
    return session.exec(
        select(TimelineEvent)
        .where(TimelineEvent.call_id == call_id)
        .order_by(TimelineEvent.ts)
    ).all()
