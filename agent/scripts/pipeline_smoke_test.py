"""Low-cost live provider smoke test for the ClinicFlow voice pipeline.

Exercises each external provider exactly once with tiny budgets, then prints a
coverage matrix. This proves the real keys work end to end without running a
full voiced call.

Checks:
  1. LiveKit  - authenticate and list rooms (no media).
  2. LLM      - a tiny chat completion on the configured provider (llm.py).
  3. LLM      - a tiny tool-calling turn (emergency -> route_to_department).
  4. Rumik    - synthesize one short muga phrase to audio.
  5. Deepgram - transcribe that audio back to text (TTS -> STT interop).
  6. Realtime - a text round trip on gpt-realtime, when a key is available.

The LLM checks follow LLM_PROVIDER, so running this after flipping the provider
is how you confirm the flip before spending a call on it. The realtime check runs
when VOICE_MODE=realtime or OPENAI_API_KEY is set; pass --no-realtime to skip it.

Run:  agent/.venv/bin/python scripts/pipeline_smoke_test.py [--no-realtime]
"""
from __future__ import annotations

import argparse
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

import llm as llm_provider  # noqa: E402  (must follow load_dotenv)
import realtime as realtime_provider  # noqa: E402

LLM_CONFIG = llm_provider.resolve_config()
MODEL = LLM_CONFIG.model

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


def _client():
    from openai import OpenAI

    return OpenAI(
        api_key=llm_provider.api_key_for(LLM_CONFIG), base_url=LLM_CONFIG.base_url
    )


def _effort_kwargs() -> dict:
    """Only reasoning models accept reasoning_effort; sending it elsewhere 400s."""
    return (
        {"reasoning_effort": LLM_CONFIG.reasoning_effort}
        if LLM_CONFIG.reasoning_effort
        else {}
    )


def check_llm_completion() -> None:
    t = time.time()
    try:
        resp = _client().chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            # Reasoning models spend tokens before the answer, so leave room.
            max_completion_tokens=256,
            **_effort_kwargs(),
        )
        text = (resp.choices[0].message.content or "").strip()
        record(LLM_CONFIG.provider, "chat completion", bool(text), repr(text[:40]), (time.time() - t) * 1000)
    except Exception as exc:  # noqa: BLE001
        record(LLM_CONFIG.provider, "chat completion", False, str(exc)[:60], (time.time() - t) * 1000)


def check_llm_tool_calling() -> None:
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
        resp = _client().chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a clinic receptionist. Use tools when appropriate."},
                {"role": "user", "content": "I have severe chest pain and I cannot breathe."},
            ],
            tools=[tool],
            tool_choice="auto",
            max_completion_tokens=200,
            **_effort_kwargs(),
        )
        calls = resp.choices[0].message.tool_calls or []
        if calls:
            args = json.loads(calls[0].function.arguments or "{}")
            dept = str(args.get("department", "")).lower()
            ok = "emergency" in dept
            record(LLM_CONFIG.provider, "tool calling (emergency)", ok, f"{calls[0].function.name}({args.get('department')})", (time.time() - t) * 1000)
        else:
            record(LLM_CONFIG.provider, "tool calling (emergency)", False, "no tool_call returned", (time.time() - t) * 1000)
    except Exception as exc:  # noqa: BLE001
        record(LLM_CONFIG.provider, "tool calling (emergency)", False, str(exc)[:60], (time.time() - t) * 1000)


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


async def check_realtime() -> None:
    """One text round trip on the speech-to-speech model.

    Text only, so it costs a handful of tokens instead of audio minutes, but it
    still proves the key, the model name, and the websocket path that a realtime
    call depends on.
    """
    from openai import AsyncOpenAI

    config = realtime_provider.resolve_config()
    t = time.time()
    try:
        client = AsyncOpenAI(api_key=realtime_provider.api_key())
        async with client.realtime.connect(model=config.model) as conn:
            await conn.session.update(
                session={
                    "type": "realtime",
                    "output_modalities": ["text"],
                    "instructions": "Answer in one word.",
                }
            )
            await conn.conversation.item.create(
                item={
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Say the word: ready"}],
                }
            )
            await conn.response.create()
            text = ""
            async for event in conn:
                if event.type == "response.output_text.delta":
                    text += event.delta
                elif event.type == "error":
                    raise RuntimeError(getattr(event.error, "message", "realtime error"))
                elif event.type == "response.done":
                    break
        record("Realtime", f"{config.model} text turn", bool(text.strip()), repr(text.strip()[:40]), (time.time() - t) * 1000)
    except Exception as exc:  # noqa: BLE001
        record("Realtime", f"{config.model} text turn", False, str(exc)[:70], (time.time() - t) * 1000)


def _realtime_wanted(args: argparse.Namespace) -> bool:
    if args.no_realtime:
        return False
    return bool(
        (os.getenv("VOICE_MODE") or "").strip().lower() == "realtime"
        or (os.getenv("OPENAI_API_KEY") or "").strip()
    )


async def main() -> None:
    import aiohttp

    parser = argparse.ArgumentParser(description="ClinicFlow provider smoke test")
    parser.add_argument("--no-realtime", action="store_true", help="skip the realtime check")
    args = parser.parse_args()

    print("ClinicFlow pipeline smoke test (low cost)")
    print(f"  {llm_provider.describe()}")
    print(f"  VOICE_MODE={os.getenv('VOICE_MODE', 'cascaded')}\n")
    await check_livekit()
    check_llm_completion()
    check_llm_tool_calling()
    async with aiohttp.ClientSession() as session:
        wav = await synth_rumik(session)
    await check_deepgram(wav)
    if _realtime_wanted(args):
        await check_realtime()
    else:
        print("[SKIP] Realtime  no OPENAI_API_KEY set (or --no-realtime)")

    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    print(f"\nCoverage: {passed}/{total} checks passed.")
    if passed < total:
        print("Some providers failed; see FAIL rows above.")
        sys.exit(1)
    print("All providers reachable and working.")


if __name__ == "__main__":
    asyncio.run(main())
