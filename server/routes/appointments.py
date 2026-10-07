"""Appointment reads, slot availability, and booking.

Availability and booking read/write the seeded slot table, which stands in for
real doctor calendars behind a real integration seam.
"""
from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import update, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from db import get_session
from models import Appointment, BookingRequest, Department, Doctor, Patient, Slot
from clock import clinic_now

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
    request_id: str | None = Field(default=None, min_length=8, max_length=128)


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
    limit: int = Query(default=3, ge=1, le=20),
    date: str | None = None,
    not_before: str | None = None,
    not_after: str | None = None,
    now: datetime = Depends(clinic_now),
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
        .where(Slot.start > now)
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

    for value, lower in ((not_before, True), (not_after, False)):
        if value:
            try:
                parsed = datetime.strptime(value, "%H:%M").time().isoformat()
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="time must be HH:MM in Asia/Kolkata") from exc
            query = query.where(func.time(Slot.start) >= parsed if lower else func.time(Slot.start) <= parsed)

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


def _result(appointment: Appointment, session: Session) -> BookingResult:
    slot = session.get(Slot, appointment.slot_id)
    patient = session.get(Patient, appointment.patient_id)
    doctor = session.get(Doctor, slot.doctor_id)
    department = session.get(Department, doctor.department_id)
    return BookingResult(
        appointment_id=appointment.id, patient=patient.name, doctor=doctor.name,
        department=department.name, start=slot.start.isoformat(), reason=appointment.reason,
    )


def _receipt(body: BookingCreate, session: Session) -> BookingResult | None:
    receipt = session.get(BookingRequest, body.request_id) if body.request_id else None
    if receipt is None:
        return None
    appointment = session.get(Appointment, receipt.appointment_id)
    if (appointment.patient_id, appointment.slot_id, appointment.reason) != (body.patient_id, body.slot_id, body.reason):
        raise HTTPException(status_code=409, detail="Request ID already used for a different booking")
    return _result(appointment, session)


@router.get("/requests/{request_id}", response_model=BookingResult)
def booking_receipt(request_id: str, patient_id: int, session: Session = Depends(get_session)) -> BookingResult:
    receipt = session.get(BookingRequest, request_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Booking request not found")
    appointment = session.get(Appointment, receipt.appointment_id)
    if appointment.patient_id != patient_id:
        raise HTTPException(status_code=404, detail="Booking request not found")
    return _result(appointment, session)


@router.post("", response_model=BookingResult)
def book(body: BookingCreate, session: Session = Depends(get_session), now: datetime = Depends(clinic_now)) -> BookingResult:
    previous = _receipt(body, session)
    if previous:
        return previous
    slot = session.get(Slot, body.slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Slot not found")
    if slot.start <= now:
        raise HTTPException(status_code=422, detail="Cannot book an appointment in the past")

    patient = session.get(Patient, body.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    doctor = session.get(Doctor, slot.doctor_id)
    department = session.get(Department, doctor.department_id)

    # Claim in the database, not with a read-then-write boolean check. The receipt
    # and appointment share this transaction, so a dropped HTTP response is safe
    # to retry with the same request ID.
    claimed = session.execute(update(Slot).where(Slot.id == slot.id, Slot.booked == False).values(booked=True))
    if claimed.rowcount != 1:
        session.rollback()
        previous = _receipt(body, session)
        if previous:
            return previous
        raise HTTPException(status_code=409, detail="That slot was just taken")

    appointment = Appointment(
        patient_id=patient.id,
        slot_id=slot.id,
        department_id=department.id,
        reason=body.reason,
        status="confirmed",
    )
    try:
        session.add(appointment)
        session.flush()
        if body.request_id:
            session.add(BookingRequest(request_id=body.request_id, appointment_id=appointment.id))
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        previous = _receipt(body, session)
        if previous:
            return previous
        raise HTTPException(status_code=409, detail="Booking conflicted with another request") from exc
    session.refresh(appointment)
    return _result(appointment, session)
