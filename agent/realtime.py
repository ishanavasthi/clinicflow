"""Speech-to-speech mode: OpenAI Realtime instead of the cascaded pipeline.

Set `VOICE_MODE=realtime` in agent/.env and the session drops STT, LLM, and TTS
for a single model that hears audio and speaks audio. The five function tools,
the guardrails around them, and the dashboard are unchanged, because they sit
above the model either way.

The trade, which is the point of being able to run both:

    cascaded   four stages you can each swap, price, and time separately, and a
               transcript you can post-process before it is spoken (the reply
               cleaning in receptionist.py lives there).
    realtime   far less to go wrong between hearing and speaking, native
               interruption handling, and noise reduction on the input, but the
               stage breakdown collapses to one number and audio tokens cost
               materially more per minute than text.

Knobs, all optional: REALTIME_MODEL, REALTIME_VOICE, REALTIME_TURN_DETECTION
(semantic_vad | server_vad | none), REALTIME_EAGERNESS, REALTIME_NOISE_REDUCTION
(near_field | far_field | none).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from livekit.agents import NOT_GIVEN
from livekit.plugins import openai

DEFAULT_MODEL = "gpt-realtime"
DEFAULT_VOICE = "marin"
# Semantic VAD asks a model whether the caller has finished a thought, which is
# the same intent as min_endpointing_delay in the cascaded path: do not cut a
# patient off mid-sentence. `low` eagerness waits longest.
DEFAULT_TURN_DETECTION = "semantic_vad"
DEFAULT_EAGERNESS = "low"
# Callers are on a phone or a laptop mic, not a studio.
DEFAULT_NOISE_REDUCTION = "near_field"

TURN_DETECTION_CHOICES = ("semantic_vad", "server_vad", "none")
NOISE_REDUCTION_CHOICES = ("near_field", "far_field", "none")


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    value = value.strip() if value else ""
    return value or default


@dataclass(frozen=True)
class RealtimeConfig:
    model: str
    voice: str
    turn_detection: str
    eagerness: str
    noise_reduction: str

    @property
    def label(self) -> str:
        return f"openai-realtime/{self.model}"

    def as_dict(self) -> dict:
        return {
            "provider": "openai-realtime",
            "model": self.model,
            "voice": self.voice,
            "turn_detection": self.turn_detection,
            "eagerness": self.eagerness if self.turn_detection == "semantic_vad" else None,
            "noise_reduction": self.noise_reduction,
        }


def resolve_config() -> RealtimeConfig:
    config = RealtimeConfig(
        model=_env("REALTIME_MODEL", DEFAULT_MODEL),
        voice=_env("REALTIME_VOICE", DEFAULT_VOICE),
        turn_detection=_env("REALTIME_TURN_DETECTION", DEFAULT_TURN_DETECTION).lower(),
        eagerness=_env("REALTIME_EAGERNESS", DEFAULT_EAGERNESS).lower(),
        noise_reduction=_env("REALTIME_NOISE_REDUCTION", DEFAULT_NOISE_REDUCTION).lower(),
    )
    if config.turn_detection not in TURN_DETECTION_CHOICES:
        raise RuntimeError(
            f"REALTIME_TURN_DETECTION={config.turn_detection!r} is not one of: "
            + ", ".join(TURN_DETECTION_CHOICES)
        )
    if config.noise_reduction not in NOISE_REDUCTION_CHOICES:
        raise RuntimeError(
            f"REALTIME_NOISE_REDUCTION={config.noise_reduction!r} is not one of: "
            + ", ".join(NOISE_REDUCTION_CHOICES)
        )
    return config


def api_key() -> str:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "VOICE_MODE is 'realtime' but OPENAI_API_KEY is not set. Add it to "
            "agent/.env, or set VOICE_MODE=cascaded to use the STT/LLM/TTS pipeline."
        )
    return key


def _turn_detection(config: RealtimeConfig):
    if config.turn_detection == "none":
        # The caller's turn is then ours to end; only useful for push-to-talk.
        return None
    if config.turn_detection == "server_vad":
        return {"type": "server_vad", "interrupt_response": True}
    return {
        "type": "semantic_vad",
        "eagerness": config.eagerness,
        "interrupt_response": True,
    }


def build_realtime() -> openai.realtime.RealtimeModel:
    config = resolve_config()
    return openai.realtime.RealtimeModel(
        model=config.model,
        voice=config.voice,
        api_key=api_key(),
        turn_detection=_turn_detection(config),
        input_audio_noise_reduction=(
            None if config.noise_reduction == "none" else config.noise_reduction
        ),
        # Ask for the caller's words in text too, so the dashboard transcript and
        # the archived call record stay as complete as in cascaded mode.
        input_audio_transcription={"model": "gpt-4o-mini-transcribe"},
    )


def describe() -> str:
    config = resolve_config()
    turn = config.turn_detection
    if turn == "semantic_vad":
        turn += f" (eagerness={config.eagerness})"
    return (
        f"Realtime: {config.model}, voice={config.voice}, turn_detection={turn}, "
        f"noise_reduction={config.noise_reduction}"
    )
