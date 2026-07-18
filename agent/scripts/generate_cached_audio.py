"""Generate cached audio for fixed phrases with Rumik muga.

Run once (this costs a little Rumik credit); the resulting WAVs are committed to
agent/audio/ so every call plays them for free, with no LLM or TTS round trip.

Run: agent/.venv/bin/python scripts/generate_cached_audio.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp
from dotenv import load_dotenv

_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_AGENT_DIR, ".env"))

from livekit.plugins import rumik_ai  # noqa: E402

from prompts import GREETING_TEXT  # noqa: E402

AUDIO_DIR = os.path.join(_AGENT_DIR, "audio")

# name -> exact text. The text must match what the agent forwards as transcript.
PHRASES = {
    "greeting.wav": GREETING_TEXT,
}


async def synth(session: aiohttp.ClientSession, text: str) -> tuple[bytes, int]:
    tts = rumik_ai.TTS(model="muga", tone="neutral", http_session=session)
    stream = tts.synthesize(text)
    pcm = bytearray()
    sample_rate = 24000
    async for ev in stream:
        pcm += bytes(ev.frame.data)
        sample_rate = ev.frame.sample_rate
    await stream.aclose()
    return bytes(pcm), sample_rate


async def main() -> None:
    os.makedirs(AUDIO_DIR, exist_ok=True)
    async with aiohttp.ClientSession() as session:
        for name, text in PHRASES.items():
            pcm, sample_rate = await synth(session, text)
            path = os.path.join(AUDIO_DIR, name)
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm)
            print(f"wrote {name}: {len(pcm)} bytes @ {sample_rate}Hz -> {path}")


if __name__ == "__main__":
    asyncio.run(main())
