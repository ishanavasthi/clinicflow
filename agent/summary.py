"""English translations and the doctor summary for Hindi calls.

Both use the configured LLM provider (llm.py) with one JSON request each, and
neither is ever on the caller's path:

- translate_exchange runs in the background after each exchange; a failure (a
  429, a timeout, bad JSON) just leaves that line untranslated.
- build_doctor_summary runs once at hang-up under a hard timeout (see
  main.finalize). Name, age, phone, booking, routing and red flags come from the
  call state, never from the model. The patient's own words are kept only if
  they appear verbatim in what the caller said.

English-only clinics never call either.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Awaitable, Callable

import httpx

import llm as llm_provider
from language import classify
from state import CallState

logger = logging.getLogger("clinicflow-agent")

ChatFn = Callable[[list[dict]], Awaitable[str]]

TRANSLATE_PROMPT = (
    "Translate one exchange from a clinic phone call into English for the clinic "
    "staff. The caller may speak Hindi, Hinglish or English. Translate faithfully: "
    "add nothing, drop nothing, keep names, numbers and times exactly. If a line is "
    "already English, return it unchanged. Answer only with JSON: "
    '{"user": "<caller line in English>", "assistant": "<receptionist line in English>"}'
)

SUMMARY_PROMPT = (
    "You write a short English note for the doctor from a clinic phone call "
    "transcript. The caller may have spoken Hindi, Hinglish or English. Report only "
    "what the caller said; never diagnose or advise. Answer only with JSON: "
    '{"chief_complaint": "<short English phrase or null>", '
    '"duration": "<how long, in English, or null>", '
    '"key_answers": ["<other facts the caller gave, in English>"], '
    '"patient_words": "<the caller\'s own words for the complaint, copied exactly '
    'from one caller line, in the original language, or null>"}'
)


def make_chat(timeout: float) -> ChatFn:
    """A JSON chat request to the configured provider (Groq, OpenAI, OpenRouter)."""
    config = llm_provider.resolve_config()
    key = llm_provider.api_key_for(config)

    async def chat(messages: list[dict]) -> str:
        body: dict = {
            "model": config.model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        if config.reasoning_effort:
            body["reasoning_effort"] = config.reasoning_effort
        body.update(config.extra_body() or {})
        async with httpx.AsyncClient(base_url=config.base_url, timeout=timeout) as client:
            response = await client.post(
                "/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"}
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"] or ""

    return chat


def _json(text: str) -> dict:
    """The JSON object in a reply, tolerating a code fence around it."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    value = json.loads(match.group(0) if match else text)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


async def translate_exchange(user_text: str, agent_text: str, chat: ChatFn) -> dict | None:
    """English for one caller line and the reply to it, or None."""
    if classify(user_text) == "en" and classify(agent_text) == "en":
        return None
    try:
        reply = await chat([
            {"role": "system", "content": TRANSLATE_PROMPT},
            {"role": "user", "content": json.dumps({"user": user_text, "assistant": agent_text},
                                                   ensure_ascii=False)},
        ])
        data = _json(reply)
        user_en, agent_en = data.get("user"), data.get("assistant")
        if not isinstance(user_en, str) or not isinstance(agent_en, str):
            return None
        return {"user": user_en.strip(), "assistant": agent_en.strip()}
    except Exception as exc:  # noqa: BLE001 (a missing translation never breaks a call)
        logger.warning("translation dropped: %s", exc)
        return None


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# Negations that flip a complaint ("सीने में दर्द नहीं है" = no chest pain).
_NEGATIONS = {"नहीं", "नही", "न", "ना", "मत", "nahi", "nahin", "nhi", "na", "mat",
              "no", "not", "never", "don't", "dont", "doesn't", "without"}
_CLAUSE_END_RE = re.compile(r"[।॥.,;!?]")
MIN_QUOTE_WORDS = 2


def _clause_around(line: str, start: int, end: int) -> tuple[str, str]:
    """The text before and after [start, end) within the same clause."""
    before = _CLAUSE_END_RE.split(line[:start])[-1]
    after = _CLAUSE_END_RE.split(line[end:])[0]
    return before, after


def verbatim_quote(quote: str | None, caller_lines: list[str]) -> str | None:
    """The quote, only if the caller really said it (whitespace aside), it is at
    least two words, and no negation in the same clause flips its meaning."""
    if not isinstance(quote, str):
        return None
    quote = _squash(quote).strip(" \"'“”")
    if len(quote.split()) < MIN_QUOTE_WORDS:
        return None
    for line in caller_lines:
        line = _squash(line)
        start = line.find(quote)
        if start < 0:
            continue
        before, after = _clause_around(line, start, start + len(quote))
        nearby = {w.strip(".,!?\"'").lower() for w in (before + " " + after).split()}
        if not nearby & _NEGATIONS:
            return quote
    return None


def structured_fields(state: CallState) -> dict:
    """Facts the clinic system recorded during the call; never model output."""
    booking = state.booking
    return {
        "name": state.intake.get("name"),
        "age": state.intake.get("age"),
        "phone": state.intake.get("phone"),
        "symptoms": state.intake.get("symptoms"),
        "booking": {k: booking.get(k) for k in ("doctor", "department", "when")} if booking else None,
        "routed_department": state.routed_department,
        "red_flag": state.emergency,
        "language": state.language,
    }


def unavailable_summary(state: CallState) -> dict:
    return {"status": "unavailable", "chief_complaint": None, "duration": None,
            "key_answers": [], "patient_words": None, "structured": structured_fields(state)}


async def build_doctor_summary(transcript: list[dict], state: CallState, chat: ChatFn) -> dict:
    """The English doctor note for a call, from its transcript and recorded state."""
    caller_lines = [line["text"] for line in transcript if line.get("role") == "user"]
    try:
        reply = await chat([
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": "\n".join(
                f"{'Caller' if line.get('role') == 'user' else 'Receptionist'}: {line.get('text', '')}"
                for line in transcript)},
        ])
        data = _json(reply)
    except Exception as exc:  # noqa: BLE001
        logger.warning("doctor summary unavailable: %s", exc)
        return unavailable_summary(state)

    def text(key: str) -> str | None:
        value = data.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    answers = data.get("key_answers")
    return {
        "status": "ok",
        "chief_complaint": text("chief_complaint"),
        "duration": text("duration"),
        "key_answers": [a.strip() for a in answers if isinstance(a, str) and a.strip()]
        if isinstance(answers, list) else [],
        "patient_words": verbatim_quote(data.get("patient_words"), caller_lines),
        "structured": structured_fields(state),
    }


SUMMARY_TIMEOUT_S = 8.0


async def summary_for_record(transcript: list[dict], state: CallState, chat: ChatFn,
                             timeout: float = SUMMARY_TIMEOUT_S) -> dict:
    """The doctor summary under a hard time limit, so hang-up never waits on it."""
    try:
        return await asyncio.wait_for(build_doctor_summary(transcript, state, chat), timeout)
    except Exception as exc:  # noqa: BLE001 (incl. TimeoutError)
        logger.warning("doctor summary timed out or failed: %r", exc)
        return unavailable_summary(state)
