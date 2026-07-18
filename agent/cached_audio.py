"""Pre-generated audio cache for fixed phrases.

Playing a cached WAV for the always-same greeting removes the LLM + TTS round
trip on call start (an instant, smoother first impression) and saves Rumik
credits. The WAVs live in agent/audio/ and are committed; regenerate them with
scripts/generate_cached_audio.py.
"""
from __future__ import annotations

import os
import wave
from functools import lru_cache
from typing import AsyncIterator

from livekit import rtc

AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio")
_CHUNK_MS = 100


def has(name: str) -> bool:
    return os.path.exists(os.path.join(AUDIO_DIR, name))


@lru_cache(maxsize=8)
def _frames(name: str) -> tuple[rtc.AudioFrame, ...]:
    """Load a WAV into fixed-size audio frames, cached in memory after first use."""
    path = os.path.join(AUDIO_DIR, name)
    out: list[rtc.AudioFrame] = []
    with wave.open(path, "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        chunk = int(sample_rate * _CHUNK_MS / 1000)
        while True:
            data = wf.readframes(chunk)
            if not data:
                break
            out.append(
                rtc.AudioFrame(
                    data=data,
                    sample_rate=sample_rate,
                    num_channels=channels,
                    samples_per_channel=len(data) // (2 * channels),
                )
            )
    return tuple(out)


async def stream(name: str) -> AsyncIterator[rtc.AudioFrame]:
    """Yield the cached frames for `name`, suitable for AgentSession.say(audio=...)."""
    for frame in _frames(name):
        yield frame
