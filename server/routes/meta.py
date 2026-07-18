"""Read-only reference data for the dashboard: departments and FAQs."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from db import get_session
from models import Department, Doctor, FAQ

router = APIRouter(tags=["meta"])


@router.get("/departments")
def list_departments(session: Session = Depends(get_session)) -> list[dict]:
    departments = session.exec(select(Department)).all()
    result: list[dict] = []
    for dept in departments:
        doctors = session.exec(
            select(Doctor).where(Doctor.department_id == dept.id)
        ).all()
        result.append(
            {
                "id": dept.id,
                "name": dept.name,
                "floor": dept.floor,
                "description": dept.description,
                "doctors": [
                    {"id": d.id, "name": d.name, "specialty": d.specialty}
                    for d in doctors
                ],
            }
        )
    return result


@router.get("/faqs")
def list_faqs(session: Session = Depends(get_session)) -> list[FAQ]:
    return session.exec(select(FAQ)).all()
