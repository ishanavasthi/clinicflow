"""Low-cost live provider smoke test for the ClinicFlow voice pipeline.

Exercises each external provider exactly once with tiny budgets, then prints a
coverage matrix. This proves the real keys work end to end without running a
full voiced call.

Checks:
  1. LiveKit  - authenticate and list rooms (no media).
  2. Groq LLM - a tiny chat completion.
  3. Groq LLM - a tiny tool-calling turn (emergency -> route_to_department).
  4. Rumik    - synthesize one short muga phrase to audio.
  5. Deepgram - transcribe that audio back to text (TTS -> STT interop).

Run:  agent/.venv/bin/python scripts/pipeline_smoke_test.py
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")

results: list[dict] = []


def record(provider: str, check: str, ok: bool, detail: str, ms: float) -> None:
    results.append(
        {"provider": provider, "check": check, "ok": ok, "detail": detail, "ms": ms}
    )
    icon = "PASS" if ok else "FAIL"
    print(f"[{icon}] {provider:9} {check:28} {ms:6.0f}ms  {detail}")


async def check_livekit() -> None:
    from livekit import api

    t = time.time()
    try:
        lk = api.LiveKitAPI()
        rooms = await lk.room.list_rooms(api.ListRoomsRequest())
        await lk.aclose()
        record("LiveKit", "auth + list_rooms", True, f"{len(rooms.rooms)} active room(s)", (time.time() - t) * 1000)
    except Exception as exc:  # noqa: BLE001
        record("LiveKit", "auth + list_rooms", False, str(exc)[:60], (time.time() - t) * 1000)


def check_groq_completion() -> None:
    from openai import OpenAI

    t = time.time()
    try:
        client = OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url=GROQ_BASE_URL)
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            # gpt-oss is a reasoning model, so leave room for reasoning + answer.
            max_completion_tokens=256,
            reasoning_effort="low",
        )
        text = (resp.choices[0].message.content or "").strip()
        record("Groq", "chat completion", bool(text), repr(text[:40]), (time.time() - t) * 1000)
    except Exception as exc:  # noqa: BLE001
        record("Groq", "chat completion", False, str(exc)[:60], (time.time() - t) * 1000)


def check_groq_tool_calling() -> None:
    from openai import OpenAI

    tool = {
        "type": "function",
        "function": {
            "name": "route_to_department",
            "description": "Route the caller to a department.",
            "parameters": {
                "type": "object",
                "properties": {
                    "department": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["department", "reason"],
            },
        },
    }
    t = time.time()
    try:
        client = OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url=GROQ_BASE_URL)
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a clinic receptionist. Use tools when appropriate."},
                {"role": "user", "content": "I have severe chest pain and I cannot breathe."},
            ],
            tools=[tool],
            tool_choice="auto",
            max_completion_tokens=200,
            reasoning_effort="low",
        )
        calls = resp.choices[0].message.tool_calls or []
        if calls:
            args = json.loads(calls[0].function.arguments or "{}")
            dept = str(args.get("department", "")).lower()
            ok = "emergency" in dept
            record("Groq", "tool calling (emergency)", ok, f"{calls[0].function.name}({args.get('department')})", (time.time() - t) * 1000)
        else:
            record("Groq", "tool calling (emergency)", False, "no tool_call returned", (time.time() - t) * 1000)
    except Exception as exc:  # noqa: BLE001
        record("Groq", "tool calling (emergency)", False, str(exc)[:60], (time.time() - t) * 1000)


async def synth_rumik(session) -> bytes | None:
    """Synthesize one short phrase with Rumik muga; return WAV bytes.

    An explicit aiohttp session is passed because, outside the LiveKit worker
    runtime, the plugin's shared HTTP context is not initialized. Inside the real
    agent that context exists, so production needs no explicit session.
    """
    from livekit.plugins import rumik_ai

    t = time.time()
    try:
        tts = rumik_ai.TTS(model="muga", tone="neutral", http_session=session)
        stream = tts.synthesize("[neutral] Hello, I would like to book an appointment.")
        pcm = bytearray()
        sample_rate = 24000
        async for ev in stream:
            frame = ev.frame
            sample_rate = frame.sample_rate
            pcm += bytes(frame.data)
        await stream.aclose()

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(bytes(pcm))
        wav = buf.getvalue()
        record("Rumik", "muga synthesize", len(wav) > 1000, f"{len(wav)} WAV bytes @ {sample_rate}Hz", (time.time() - t) * 1000)
        return wav
    except Exception as exc:  # noqa: BLE001
        record("Rumik", "muga synthesize", False, str(exc)[:60], (time.time() - t) * 1000)
        return None


async def check_deepgram(wav: bytes | None) -> None:
    import httpx

    if not wav:
        record("Deepgram", "transcribe (TTS->STT)", False, "no audio to transcribe", 0)
        return
    t = time.time()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true",
                headers={
                    "Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}",
                    "Content-Type": "audio/wav",
                },
                content=wav,
            )
            resp.raise_for_status()
            data = resp.json()
            transcript = data["results"]["channels"][0]["alternatives"][0]["transcript"]
            record("Deepgram", "transcribe (TTS->STT)", bool(transcript.strip()), repr(transcript[:50]), (time.time() - t) * 1000)
    except Exception as exc:  # noqa: BLE001
        record("Deepgram", "transcribe (TTS->STT)", False, str(exc)[:60], (time.time() - t) * 1000)


async def main() -> None:
    import aiohttp

    print("ClinicFlow pipeline smoke test (low cost)\n")
    await check_livekit()
    check_groq_completion()
    check_groq_tool_calling()
    async with aiohttp.ClientSession() as session:
        wav = await synth_rumik(session)
    await check_deepgram(wav)

    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    print(f"\nCoverage: {passed}/{total} checks passed.")
    if passed < total:
        print("Some providers failed; see FAIL rows above.")
        sys.exit(1)
    print("All providers reachable and working.")


if __name__ == "__main__":
    asyncio.run(main())
