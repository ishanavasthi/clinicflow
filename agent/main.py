"""ClinicFlow agent worker entrypoint.

Voice loop (M1) plus tools and persistence (M2). One LiveKit AgentSession, in
either of two modes chosen by VOICE_MODE in agent/.env:

    cascaded (default)  silero VAD -> Deepgram STT -> an OpenAI-protocol LLM
                        (Groq or OpenAI, see llm.py) -> Rumik TTS.
    realtime            one OpenAI speech-to-speech model in place of all three
                        (see realtime.py).

The receptionist's five function tools, its guardrails, persistence to the
FastAPI server, and the agent-state events driving the live dashboard are the
same either way: they sit above the model, not inside it. Every call is archived
with the config that produced it and its per-turn latency, so the modes can be
compared rather than argued about (see turn_latency.py and `make latency`).

Run:  python main.py dev     (or `console` to talk via the local mic)
"""
from __future__ import annotations

import asyncio
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
from livekit.plugins import deepgram, silero

import llm as llm_provider
import realtime
import turn_clock
import turn_latency
from call_log import build_record, summary_of, write_record
from receptionist import Receptionist
from server_client import ServerClient
from state import AgentStatePublisher, CallState
from tts import build_tts

load_dotenv()

logger = logging.getLogger("clinicflow-agent")

VOICE_MODES = ("cascaded", "realtime")
DEFAULT_VOICE_MODE = "cascaded"

# Needed only by the cascaded pipeline; the realtime model replaces both.
CASCADED_ENV = {
    "DEEPGRAM_API_KEY": "Deepgram STT",
    "RUMIK_API_KEY": "Rumik TTS",
}

STT_MODEL = "nova-3"


def _voice_mode() -> str:
    mode = (os.getenv("VOICE_MODE") or DEFAULT_VOICE_MODE).strip().lower()
    if mode not in VOICE_MODES:
        raise RuntimeError(
            f"VOICE_MODE={mode!r} is not one of: " + ", ".join(VOICE_MODES)
        )
    return mode


def _validate_pipeline_env(mode: str) -> None:
    """Fail at startup with the variable name, not mid-call with a 401."""
    if mode == "realtime":
        realtime.api_key()
        return
    missing = [
        f"{name} ({label})"
        for name, label in CASCADED_ENV.items()
        if not os.getenv(name)
    ]
    if missing:
        raise RuntimeError(
            "Missing voice pipeline env vars: "
            + ", ".join(missing)
            + ". Copy agent/.env.example to agent/.env and fill them in."
        )
    # Raises naming the provider's own key variable, so a Groq key is never
    # quietly sent to OpenAI.
    llm_provider.api_key_for(llm_provider.resolve_config())


def _build_session(mode: str, vad: object) -> AgentSession:
    if mode == "realtime":
        return AgentSession(
            # The realtime model does its own server-side turn detection; the VAD
            # is kept as a fallback and for local speech timing.
            vad=vad,
            llm=realtime.build_realtime(),
            max_tool_steps=4,
        )
    return AgentSession(
        vad=vad,
        stt=deepgram.STT(model=STT_MODEL),
        llm=llm_provider.build_llm(),
        tts=build_tts(),
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


def _pipeline_config(mode: str) -> dict:
    """What produced this call, stored on its record so `make latency` can group
    by configuration instead of pooling two different pipelines into one p95."""
    if mode == "realtime":
        return {"voice_mode": mode, "llm": realtime.resolve_config().as_dict()}
    return {
        "voice_mode": mode,
        "llm": llm_provider.resolve_config().as_dict(),
        "stt": {"provider": "deepgram", "model": STT_MODEL},
        "tts": {"provider": "rumik", "model": "mulberry"},
        "min_endpointing_delay": 0.8,
    }


def prewarm(proc: JobProcess) -> None:
    """Load the VAD once per worker process, not once per call."""
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    mode = _voice_mode()
    _validate_pipeline_env(mode)
    await ctx.connect()
    logger.info(
        "agent joined room %s in %s mode | %s",
        ctx.room.name,
        mode,
        realtime.describe() if mode == "realtime" else llm_provider.describe(),
    )

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

    session = _build_session(mode, ctx.proc.userdata["vad"])

    # Times the caller's wait from session events. In cascaded mode this is a
    # cross-check on the framework's own numbers; in realtime mode, where the
    # framework records none, it is the only measurement there is.
    clock = turn_clock.SessionTurnClock()
    clock.attach(session)

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

    # Persist the call record exactly once. Runs the moment the caller hangs up
    # (see below), not only on worker shutdown, so the history view has the
    # transcript, summary, and routing right away. The shutdown callback is a
    # fallback for a disconnect we never saw (e.g. a dropped connection).
    finalized = {"done": False}

    async def finalize() -> None:
        if finalized["done"]:
            return
        finalized["done"] = True
        # Build the call record once, then archive it to runs/calls/ and store it
        # on the call in SQLite so the history view is self-describing.
        record = build_record(
            state,
            session.history,
            started_at,
            datetime.now(),
            config=_pipeline_config(mode),
            clock_rows=clock.rows(),
        )
        # Print what the caller waited on this call. `make latency` aggregates the
        # same numbers across every archived call.
        summary = record["latency"]["summary"]
        if summary.get("turns_measured"):
            logger.info("call latency\n%s", turn_latency.format_table(summary))
        try:
            path = write_record(record)
            logger.info("wrote call record %s", path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not write call record: %s", exc)
        if state.call_id is not None:
            try:
                await server.end_call(
                    state.call_id,
                    routed_department=state.routed_department,
                    patient_id=state.patient_id,
                    summary=summary_of(record),
                    transcript=record["transcript"],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not end call record: %s", exc)
        try:
            await publisher.publish("status", {"status": "ended"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not publish ended status: %s", exc)
        await server.aclose()

    def _on_participant_disconnected(_participant: object) -> None:
        # The caller left; persist now instead of waiting for the job to be
        # reclaimed (which can be 20s+ later).
        asyncio.create_task(finalize())

    ctx.room.on("participant_disconnected", _on_participant_disconnected)
    ctx.add_shutdown_callback(finalize)

    await session.start(room=ctx.room, agent=Receptionist(state, server, publisher))
    await publisher.publish("status", {"status": "active", "call_id": state.call_id})


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
