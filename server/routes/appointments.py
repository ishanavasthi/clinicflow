"""Appointment reads, slot availability, and booking.

Availability and booking read/write the seeded slot table, which stands in for
real doctor calendars behind a real integration seam.
"""
from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from db import get_session
from models import Appointment, Department, Doctor, Patient, Slot

router = APIRouter(prefix="/appointments", tags=["appointments"])


class SlotOption(BaseModel):
    slot_id: int
    doctor: str
    department: str
    start: str  # ISO 8601


class BookingCreate(BaseModel):
    patient_id: int
    slot_id: int
    reason: str = ""


class BookingResult(BaseModel):
    appointment_id: int
    patient: str
    doctor: str
    department: str
    start: str
    reason: str


def _resolve_department(session: Session, name: str) -> Department:
    department = session.exec(
        select(Department).where(Department.name == name)
    ).first()
    if department is None:
        # Fall back to a case-insensitive match so the LLM can pass "cardiology".
        for candidate in session.exec(select(Department)).all():
            if candidate.name.lower() == name.lower():
                department = candidate
                break
    if department is None:
        raise HTTPException(status_code=404, detail=f"Unknown department: {name}")
    return department


@router.get("", response_model=list[Appointment])
def list_appointments(session: Session = Depends(get_session)) -> list[Appointment]:
    return session.exec(
        select(Appointment).order_by(Appointment.created_at.desc())
    ).all()


@router.get("/availability", response_model=list[SlotOption])
def availability(
    department: str,
    limit: int = 3,
    date: str | None = None,
    session: Session = Depends(get_session),
) -> list[SlotOption]:
    dept = _resolve_department(session, department)
    doctors = session.exec(
        select(Doctor).where(Doctor.department_id == dept.id)
    ).all()
    doctor_by_id = {d.id: d for d in doctors}
    if not doctor_by_id:
        return []

    query = (
        select(Slot)
        .where(Slot.doctor_id.in_(list(doctor_by_id)))
        .where(Slot.booked == False)  # noqa: E712 (SQLModel needs ==, not `is`)
        .order_by(Slot.start)
    )
    if date:
        try:
            wanted = date_cls.fromisoformat(date)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="date must be YYYY-MM-DD"
            ) from exc
        day_start = datetime.combine(wanted, datetime.min.time())
        day_end = datetime.combine(wanted, datetime.max.time())
        query = query.where(Slot.start >= day_start).where(Slot.start <= day_end)

    slots = session.exec(query.limit(limit)).all()
    return [
        SlotOption(
            slot_id=s.id,
            doctor=doctor_by_id[s.doctor_id].name,
            department=dept.name,
            start=s.start.isoformat(),
        )
        for s in slots
    ]


@router.post("", response_model=BookingResult)
def book(body: BookingCreate, session: Session = Depends(get_session)) -> BookingResult:
    slot = session.get(Slot, body.slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Slot not found")
    if slot.booked:
        raise HTTPException(status_code=409, detail="That slot was just taken")

    patient = session.get(Patient, body.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    doctor = session.get(Doctor, slot.doctor_id)
    department = session.get(Department, doctor.department_id)

    appointment = Appointment(
        patient_id=patient.id,
        slot_id=slot.id,
        department_id=department.id,
        reason=body.reason,
        status="confirmed",
    )
    slot.booked = True
    session.add(appointment)
    session.add(slot)
    session.commit()
    session.refresh(appointment)

    return BookingResult(
        appointment_id=appointment.id,
        patient=patient.name,
        doctor=doctor.name,
        department=department.name,
        start=slot.start.isoformat(),
        reason=appointment.reason,
    )
