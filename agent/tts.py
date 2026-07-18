"""Rumik TTS voice configuration.

Uses Rumik's mulberry model (description-driven, reliable for English) rather than
muga (Hinglish), because muga occasionally mis-speaks plain English as a
non-English-sounding voice. Kept in one place so the live agent and the cached
greeting use the exact same voice.
"""
from __future__ import annotations

from typing import Any

from livekit.plugins import rumik_ai

VOICE_DESCRIPTION = (
    "a clear, calm, professional female clinic receptionist speaking natural, "
    "neutral English at a steady, unhurried pace"
)
SPEAKER = "speaker_1"


def build_tts(http_session: Any = None) -> rumik_ai.TTS:
    return rumik_ai.TTS(
        model="mulberry",
        description=VOICE_DESCRIPTION,
        speaker=SPEAKER,
        http_session=http_session,
    )
