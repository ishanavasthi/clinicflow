"""Appointment reads. Booking writes are added in M2 (agent tools)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from db import get_session
from models import Appointment

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.get("", response_model=list[Appointment])
def list_appointments(session: Session = Depends(get_session)) -> list[Appointment]:
    return session.exec(select(Appointment)).all()
