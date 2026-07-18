"""LLM provider wiring.

Uses openai/gpt-oss-120b served on Groq's OpenAI-compatible endpoint. Groq gives
very low time-to-first-token, which matters for speech-to-speech latency. The
provider is swappable via env (LLM_MODEL, LLM_BASE_URL) without touching code.
"""
from __future__ import annotations

import os

from livekit.plugins import openai

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"


def build_llm() -> openai.LLM:
    api_key = os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Copy agent/.env.example to agent/.env and "
            "add your Groq key."
        )
    return openai.LLM(
        model=os.getenv("LLM_MODEL", DEFAULT_MODEL),
        base_url=os.getenv("LLM_BASE_URL", GROQ_BASE_URL),
        api_key=api_key,
        # Low temperature keeps the model deterministic and stops it from
        # role-playing the caller's side of the conversation.
        temperature=0.2,
        # One tool at a time makes the intake flow controllable and prevents the
        # model from firing several fabricated update_intake calls at once.
        parallel_tool_calls=False,
        # gpt-oss is a reasoning model; keep the effort low so the agent stays
        # snappy on a live call.
        reasoning_effort="low",
    )
