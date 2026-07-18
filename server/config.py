"""Environment-backed configuration with actionable startup validation."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Reads config from the environment. Values that are required only for a
    specific feature are validated at the point of use, not at import time, so
    the API can still boot for local UI work without live LiveKit keys."""

    def __init__(self) -> None:
        self.livekit_url = os.getenv("LIVEKIT_URL", "")
        self.livekit_api_key = os.getenv("LIVEKIT_API_KEY", "")
        self.livekit_api_secret = os.getenv("LIVEKIT_API_SECRET", "")
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./clinicflow.db")
        self.cors_origins = [
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
            if origin.strip()
        ]

    def require_livekit(self) -> tuple[str, str, str]:
        """Return LiveKit credentials or raise a clear error naming what is missing."""
        missing = [
            name
            for name, value in (
                ("LIVEKIT_URL", self.livekit_url),
                ("LIVEKIT_API_KEY", self.livekit_api_key),
                ("LIVEKIT_API_SECRET", self.livekit_api_secret),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Missing LiveKit config: "
                + ", ".join(missing)
                + ". Copy server/.env.example to server/.env and fill these in."
            )
        return self.livekit_url, self.livekit_api_key, self.livekit_api_secret


@lru_cache
def get_settings() -> Settings:
    return Settings()
