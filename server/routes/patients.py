"""Patient reads and live intake writes.

The agent creates a patient on the first intake field it collects and patches
the rest in as the conversation fills them out.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from db import get_session
from models import Patient

router = APIRouter(prefix="/patients", tags=["patients"])


class PatientCreate(BaseModel):
    name: Optional[str] = None
    age: Optional[str] = None
    phone: Optional[str] = None
    insurance: Optional[str] = None
    symptoms: Optional[str] = None


class PatientUpdate(PatientCreate):
    pass


@router.get("", response_model=list[Patient])
def list_patients(session: Session = Depends(get_session)) -> list[Patient]:
    return session.exec(select(Patient)).all()


@router.get("/{patient_id}", response_model=Patient)
def get_patient(patient_id: int, session: Session = Depends(get_session)) -> Patient:
    patient = session.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.post("", response_model=Patient)
def create_patient(
    body: PatientCreate, session: Session = Depends(get_session)
) -> Patient:
    patient = Patient(name=body.name or "Unknown caller", **body.model_dump(exclude={"name"}))
    session.add(patient)
    session.commit()
    session.refresh(patient)
    return patient


@router.patch("/{patient_id}", response_model=Patient)
def update_patient(
    patient_id: int,
    body: PatientUpdate,
    session: Session = Depends(get_session),
) -> Patient:
    patient = session.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(patient, field, value)
    session.add(patient)
    session.commit()
    session.refresh(patient)
    return patient
