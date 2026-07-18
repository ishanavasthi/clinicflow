"""Seed the SQLite database with departments, doctors, slots, FAQs, and a couple
of sample patients. Idempotent: running it again clears and reseeds.

Slots are generated relative to the current date so the demo always has
near-future availability to offer.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlmodel import Session, delete, select

from db import engine, init_db
from models import (
    Appointment,
    Call,
    Department,
    Doctor,
    FAQ,
    Patient,
    Slot,
    TimelineEvent,
)

DEPARTMENTS = [
    ("Emergency", "Ground", "Urgent and life-threatening conditions"),
    ("General Medicine", "1", "Primary care and general consultations"),
    ("Pediatrics", "1", "Care for infants, children, and adolescents"),
    ("Orthopedics", "2", "Bones, joints, muscles, and sports injuries"),
    ("Cardiology", "3", "Heart and cardiovascular care"),
]

DOCTORS = [
    ("Dr. Anjali Rao", "Emergency Medicine", "Emergency"),
    ("Dr. Vikram Nair", "Internal Medicine", "General Medicine"),
    ("Dr. Meera Iyer", "Pediatrics", "Pediatrics"),
    ("Dr. Sameer Khan", "Orthopedic Surgery", "Orthopedics"),
    ("Dr. Priya Desai", "Cardiology", "Cardiology"),
]

# Times of day offered as bookable slots.
SLOT_TIMES = [time(9, 30), time(11, 0), time(14, 0), time(15, 30), time(16, 45)]

FAQS = [
    ("What are your hours?",
     "We are open Monday to Saturday, 8 AM to 8 PM. Emergency care is available 24/7.",
     "hours"),
    ("Where are you located?",
     "ClinicFlow Medical Center, 42 Wellness Avenue, near the central metro station. Parking is on level B1.",
     "location"),
    ("Do you have parking?",
     "Yes, free patient parking is available on basement level B1, with valet service at the main entrance.",
     "parking"),
    ("What insurance do you accept?",
     "We accept Star Health, HDFC ERGO, ICICI Lombard, Niva Bupa, Care Health, Aditya Birla Health, Tata AIG, and LIC. We also offer self-pay rates.",
     "insurance"),
    ("What is your visitor policy?",
     "Two visitors per patient are allowed between 10 AM and 7 PM. Pediatric patients may have a parent stay overnight.",
     "visiting"),
]

# (name, age, phone, insurance, symptoms)
PATIENTS = [
    ("Rohan Mehta", "38", "9820012345", "Star Health", None),
    ("Sara Williams", "31", "9930067890", "HDFC ERGO", None),
]


def reset(session: Session) -> None:
    """Delete all rows so a reseed is deterministic."""
    for model in (TimelineEvent, Appointment, Call, Slot, Doctor, Patient, Department, FAQ):
        session.exec(delete(model))
    session.commit()


def seed() -> None:
    init_db()
    with Session(engine) as session:
        reset(session)

        departments: dict[str, Department] = {}
        for name, floor, description in DEPARTMENTS:
            dept = Department(name=name, floor=floor, description=description)
            session.add(dept)
            departments[name] = dept
        session.commit()

        doctors: list[Doctor] = []
        for name, specialty, dept_name in DOCTORS:
            doctor = Doctor(
                name=name,
                specialty=specialty,
                department_id=departments[dept_name].id,
            )
            session.add(doctor)
            doctors.append(doctor)
        session.commit()

        # Generate slots for the next three days (skipping today) per doctor.
        today = datetime.now().date()
        for doctor in doctors:
            for day_offset in range(1, 4):
                day = today + timedelta(days=day_offset)
                for slot_time in SLOT_TIMES:
                    session.add(
                        Slot(
                            doctor_id=doctor.id,
                            start=datetime.combine(day, slot_time),
                            booked=False,
                        )
                    )
        session.commit()

        for question, answer, tag in FAQS:
            session.add(FAQ(question=question, answer=answer, tag=tag))
        session.commit()

        for name, age, phone, insurance, symptoms in PATIENTS:
            session.add(
                Patient(
                    name=name, age=age, phone=phone,
                    insurance=insurance, symptoms=symptoms,
                )
            )
        session.commit()

        dept_count = len(session.exec(select(Department)).all())
        slot_count = len(session.exec(select(Slot)).all())
        faq_count = len(session.exec(select(FAQ)).all())
        print(
            f"Seeded {dept_count} departments, {len(doctors)} doctors, "
            f"{slot_count} slots, {faq_count} FAQs, {len(PATIENTS)} patients."
        )


if __name__ == "__main__":
    seed()
