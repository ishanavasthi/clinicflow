"""Deterministic, per-run SQLite fixtures for conversational evaluations."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path


FIXED_CLOCK = "2026-10-07T09:00:00+05:30"


def _server_imports():
    # The server is an application of loose modules, not an installed package.
    # The runner inserts its directory on sys.path before calling this function.
    from models import Appointment, Call, Department, Doctor, FAQ, Patient, Slot
    from sqlmodel import SQLModel

    return SQLModel, Department, Doctor, Slot, Patient, Appointment, Call, FAQ


def build_fixture(database: Path, scenario: dict, fixed_clock: str = FIXED_CLOCK):
    """Create an isolated database and seed only synthetic reference data.

    Scenario fixture overrides can name departments with no slots, seed patients,
    or prebook a slot. The demo database and server's global engine are untouched.
    """
    from sqlmodel import Session, create_engine

    from seed import DEPARTMENTS, DOCTORS, SLOT_TIMES

    SQLModel, Department, Doctor, Slot, Patient, Appointment, _, FAQ = _server_imports()
    database.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{database}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    fixture = scenario.get("fixture") or {}
    now = datetime.fromisoformat(fixed_clock)
    start_day = now.date() + timedelta(days=1)
    with Session(engine) as session:
        departments = {}
        for name, floor, description in DEPARTMENTS:
            row = Department(name=name, floor=floor, description=description)
            session.add(row)
            session.flush()
            departments[name] = row
        doctors = {}
        for name, specialty, department in DOCTORS:
            row = Doctor(name=name, specialty=specialty, department_id=departments[department].id)
            session.add(row)
            session.flush()
            doctors[name] = row
        empty = set(fixture.get("empty_departments", []))
        days = int(fixture.get("days", 3))
        for name, _, department in DOCTORS:
            if department in empty:
                continue
            for offset in range(days):
                for slot_time in SLOT_TIMES:
                    session.add(Slot(doctor_id=doctors[name].id, start=datetime.combine(start_day + timedelta(days=offset), slot_time), booked=False))
        for patient in fixture.get("patients", []):
            session.add(Patient(**patient))
        session.commit()
        for row in fixture.get("prebooked", []):
            slot = session.get(Slot, int(row["slot_id"]))
            if slot is None:
                raise ValueError(f"fixture prebooked slot {row['slot_id']} does not exist")
            slot.booked = True
            patient = Patient(name=row.get("name", "Fixture patient"))
            session.add(patient)
            session.flush()
            doctor = session.get(Doctor, slot.doctor_id)
            session.add(Appointment(patient_id=patient.id, slot_id=slot.id, department_id=doctor.department_id, reason="fixture"))
        session.commit()
    return engine


def read_final_state(engine, call_state) -> dict:
    """Read durable rows with a new database session, independent of agent state."""
    from sqlmodel import Session, select

    _, Department, Doctor, Slot, Patient, Appointment, Call, _ = _server_imports()
    with Session(engine) as session:
        depts = {d.id: d.name for d in session.exec(select(Department)).all()}
        doctors = {d.id: d for d in session.exec(select(Doctor)).all()}
        slots = session.exec(select(Slot).order_by(Slot.id)).all()
        slots_by_id = {s.id: s for s in slots}
        patients = [p.model_dump(mode="json") for p in session.exec(select(Patient).order_by(Patient.id)).all()]
        appointments = []
        for a in session.exec(select(Appointment).order_by(Appointment.id)).all():
            item = a.model_dump(mode="json")
            slot = slots_by_id[a.slot_id]
            item.update(doctor=doctors[slot.doctor_id].name, department=depts[a.department_id], start=slot.start.isoformat())
            appointments.append(item)
        slot_rows = []
        for s in slots:
            item = s.model_dump(mode="json")
            item.update(doctor=doctors[s.doctor_id].name, department=depts[doctors[s.doctor_id].department_id])
            slot_rows.append(item)
    return {
        "patients": patients,
        "appointments": appointments,
        "slots": slot_rows,
        "call_state": {
            "call_id": call_state.call_id,
            "patient_id": call_state.patient_id,
            "intake": dict(call_state.intake),
            "offered_slots": list(call_state.offered_slots),
            "status": call_state.status,
            "routed_department": call_state.routed_department,
            "booking": call_state.booking,
        },
    }
