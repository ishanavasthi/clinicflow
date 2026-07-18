"""SQLModel tables for ClinicFlow.

This mirrors the data model in PLAN.md section 8. The seeded EHR (patients,
departments, doctors, slots) stands in for a real hospital system behind a real
integration seam. Calls, appointments, and timeline events are written live by
the agent during a conversation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class Department(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    floor: str
    description: str = ""


class Doctor(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    specialty: str = ""
    department_id: int = Field(foreign_key="department.id", index=True)


class Slot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    doctor_id: int = Field(foreign_key="doctor.id", index=True)
    start: datetime = Field(index=True)
    booked: bool = Field(default=False, index=True)


class Patient(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    age: Optional[str] = None
    phone: Optional[str] = None
    insurance: Optional[str] = None
    symptoms: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Appointment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    slot_id: int = Field(foreign_key="slot.id", index=True)
    department_id: int = Field(foreign_key="department.id")
    reason: str = ""
    status: str = Field(default="confirmed")  # confirmed | cancelled
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Call(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    room: str = Field(index=True)
    patient_id: Optional[int] = Field(default=None, foreign_key="patient.id")
    status: str = Field(default="active")  # active | ended
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    recording_url: Optional[str] = None
    routed_department: Optional[str] = None
    # Immutable snapshot of the call for the history view (written at end).
    summary: dict = Field(default_factory=dict, sa_column=Column(JSON))
    transcript: list = Field(default_factory=list, sa_column=Column(JSON))


class TimelineEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    call_id: int = Field(foreign_key="call.id", index=True)
    ts: datetime = Field(default_factory=datetime.utcnow)
    type: str  # status | intake_update | faq | booking | routing | timeline
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))


class FAQ(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    question: str
    answer: str
    tag: str = Field(index=True)
