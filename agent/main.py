"""ClinicFlow agent worker entrypoint.

M0 scaffold: this wires the worker options and validates config, but the full
AgentSession pipeline (silero VAD, Deepgram STT, gpt-4o-mini, Rumik muga TTS)
and the function tools are implemented in M1 and M2. Kept runnable so the module
imports cleanly and `python main.py` reports what is still missing.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

REQUIRED_ENV = [
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "RUMIK_API_KEY",
    "DEEPGRAM_API_KEY",
    "OPENAI_API_KEY",
]


def check_env() -> list[str]:
    """Return the names of required env vars that are not set."""
    return [name for name in REQUIRED_ENV if not os.getenv(name)]


def main() -> None:
    missing = check_env()
    if missing:
        print("ClinicFlow agent: missing env vars ->", ", ".join(missing))
        print("Copy agent/.env.example to agent/.env and fill these in.")
    else:
        print("ClinicFlow agent: config OK. Pipeline wiring lands in M1.")


if __name__ == "__main__":
    main()
