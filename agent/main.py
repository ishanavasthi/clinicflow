"""ClinicFlow agent worker entrypoint.

Voice loop (M1) plus tools and persistence (M2): a LiveKit AgentSession wiring
silero VAD, Deepgram STT, gpt-oss-120b on Groq, and Rumik muga TTS. The
receptionist's five function tools persist to the FastAPI server and publish
agent-state events to the room data channel for the live dashboard.

Run:  python main.py dev     (or `console` to talk via the local mic)
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime

from dotenv import load_dotenv
from livekit.agents import (
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
)
from livekit.plugins import deepgram, rumik_ai, silero

from call_log import write_call_record
from llm import build_llm
from receptionist import Receptionist
from server_client import ServerClient
from state import AgentStatePublisher, CallState

load_dotenv()

logger = logging.getLogger("clinicflow-agent")

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

    # Persistence + realtime plumbing. A server outage here degrades to a call
    # with no dashboard/records, never a failed conversation.
    server = ServerClient()
    state = CallState(room_name=ctx.room.name)
    try:
        call = await server.create_call(ctx.room.name)
        state.call_id = call["id"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not create call record: %s", exc)

    publisher = AgentStatePublisher(ctx.room, state, server)
    started_at = datetime.now()

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(model="nova-3"),
        llm=build_llm(),
        tts=rumik_ai.TTS(model="muga", tone="neutral"),
        # Be more patient so the agent waits for the caller to finish instead of
        # jumping in during a natural pause, and ignore stray one-word noise so it
        # does not falsely interrupt itself. Use the mute button for longer pauses.
        min_endpointing_delay=0.8,
        min_interruption_words=2,
        # Allow a couple of tool calls per turn (e.g. record a symptom given
        # earlier plus the age just given) without the framework forcing an extra
        # response, but keep it low so the model cannot chain far ahead.
        max_tool_steps=4,
    )

    # A provider hiccup (most likely a Groq rate limit) must never leave the agent
    # silent. Speak a short fallback, debounced so retries do not stack.
    last_fallback = {"ts": 0.0}

    def on_error(_event: object) -> None:
        now = time.monotonic()
        if now - last_fallback["ts"] < 8.0:
            return
        last_fallback["ts"] = now
        try:
            session.say(
                "Sorry, I had a brief hiccup. Could you say that again?",
                add_to_chat_ctx=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("fallback speech failed: %s", exc)

    session.on("error", on_error)

    async def on_shutdown() -> None:
        if state.call_id is not None:
            try:
                await server.end_call(
                    state.call_id, routed_department=state.routed_department
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not end call record: %s", exc)
        # Save the full call (transcript + patient details) to runs/calls/.
        try:
            path = write_call_record(
                state, session.history, started_at, datetime.now()
            )
            logger.info("wrote call record %s", path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not write call record: %s", exc)
        await publisher.publish("status", {"status": "ended"})
        await server.aclose()

    ctx.add_shutdown_callback(on_shutdown)

    await session.start(room=ctx.room, agent=Receptionist(state, server, publisher))
    await publisher.publish("status", {"status": "active", "call_id": state.call_id})


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
