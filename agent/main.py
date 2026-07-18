"""ClinicFlow agent worker entrypoint.

M1 voice loop: a LiveKit AgentSession wiring silero VAD, Deepgram STT,
gpt-oss-120b on Groq, and Rumik muga TTS. The worker auto-joins each call room,
greets the caller, and holds a real two-way conversation with barge-in.

Function tools and dashboard state publishing are added in M2.

Run:  python main.py dev
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from livekit.agents import (
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
)
from livekit.plugins import deepgram, rumik_ai, silero

from llm import build_llm
from prompts import GREETING_INSTRUCTION
from receptionist import Receptionist

load_dotenv()

logger = logging.getLogger("clinicflow-agent")

# Keys the voice pipeline needs beyond the LiveKit ones that cli.run_app checks.
PIPELINE_ENV = {
    "DEEPGRAM_API_KEY": "Deepgram STT",
    "RUMIK_API_KEY": "Rumik TTS",
    "GROQ_API_KEY": "Groq LLM",
}


def _validate_pipeline_env() -> None:
    missing = [
        f"{name} ({label})"
        for name, label in PIPELINE_ENV.items()
        if not os.getenv(name)
    ]
    # GROQ_API_KEY may be substituted by OPENAI_API_KEY for the LLM.
    if "GROQ_API_KEY (Groq LLM)" in missing and os.getenv("OPENAI_API_KEY"):
        missing.remove("GROQ_API_KEY (Groq LLM)")
    if missing:
        raise RuntimeError(
            "Missing voice pipeline env vars: "
            + ", ".join(missing)
            + ". Copy agent/.env.example to agent/.env and fill them in."
        )


def prewarm(proc: JobProcess) -> None:
    """Load the VAD once per worker process, not once per call."""
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    _validate_pipeline_env()
    await ctx.connect()
    logger.info("agent joined room %s", ctx.room.name)

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(model="nova-3"),
        llm=build_llm(),
        # Muga speaks Roman Hinglish from tone tags the LLM emits; tone is the
        # fallback if a turn is missing its tag.
        tts=rumik_ai.TTS(model="muga", tone="neutral"),
    )

    await session.start(room=ctx.room, agent=Receptionist())
    await session.generate_reply(instructions=GREETING_INSTRUCTION)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
