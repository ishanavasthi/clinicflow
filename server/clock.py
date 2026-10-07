"""Clinic-local calendar time; injectable in deterministic scheduling tests."""
from datetime import datetime
from zoneinfo import ZoneInfo

CLINIC_TIMEZONE = "Asia/Kolkata"


def clinic_now() -> datetime:
    # SQLite stores the demo's calendar as naive clinic-local wall-clock values.
    return datetime.now(ZoneInfo(CLINIC_TIMEZONE)).replace(tzinfo=None)
