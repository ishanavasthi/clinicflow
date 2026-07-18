"""ClinicFlow persistence API.

Stateless REST over a seeded SQLite database. Never sits in the audio path, so a
REST hiccup can never interrupt a live call. Mints LiveKit tokens, serves seeded
reference data, and (in later milestones) records the agent's tool-call writes.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from config import get_settings
from db import engine, init_db
from models import Department
from routes import appointments, calls, meta, patients, tokens


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Seed on first boot if the database is empty, so a fresh clone is demoable
    # without a manual step. Reseeding is explicit via `python seed.py`.
    with Session(engine) as session:
        if not session.exec(select(Department)).first():
            from seed import seed

            seed()
    yield


app = FastAPI(title="ClinicFlow API", version="0.1.0", lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tokens.router)
app.include_router(meta.router)
app.include_router(patients.router)
app.include_router(appointments.router)
app.include_router(calls.router)


@app.get("/health", tags=["health"])
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "livekit_configured": bool(
            settings.livekit_url
            and settings.livekit_api_key
            and settings.livekit_api_secret
        ),
    }
