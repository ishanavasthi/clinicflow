"""Offline check of the latency extraction (no keys, no network, no audio).

Builds chat contexts shaped exactly like finished calls, with the timings the
framework writes onto each message, and asserts the report reads them correctly:
the greeting is not a turn, an interrupted reply is excluded from the stats,
`pipeline` is `e2e` minus the endpointing wait, and a speech-to-speech call (no
`e2e_latency` field, only the two speech timestamps) still gets measured.

Run:  agent/.venv/bin/python scripts/latency_selftest.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from livekit.agents.llm import ChatContext, ChatMessage

import turn_latency


def _add(ctx: ChatContext, role: str, text: str, metrics: dict | None = None,
         interrupted: bool = False) -> None:
    message = ChatMessage(role=role, content=[text], interrupted=interrupted)
    if metrics:
        message.metrics.update(metrics)
    ctx.items.append(message)


def build_call() -> ChatContext:
    ctx = ChatContext.empty()
    # Cached greeting: the agent speaks first, so there is no caller turn to time.
    _add(ctx, "assistant", "Thanks for calling City Clinic.")
    _add(ctx, "user", "I need an appointment",
         {"end_of_turn_delay": 0.92, "transcription_delay": 0.18})
    _add(ctx, "assistant", "Sure, may I take your name?",
         {"e2e_latency": 1.55, "llm_node_ttft": 0.31, "tts_node_ttfb": 0.22})
    _add(ctx, "user", "Priya Sharma",
         {"end_of_turn_delay": 0.85, "transcription_delay": 0.14})
    _add(ctx, "assistant", "Thanks Priya. How old are you?",
         {"e2e_latency": 1.28, "llm_node_ttft": 0.24, "tts_node_ttfb": 0.19})
    # The caller barges in: real barge-in, but not a measurement of the pipeline.
    _add(ctx, "user", "thirty four",
         {"end_of_turn_delay": 0.81, "transcription_delay": 0.11})
    _add(ctx, "assistant", "And your phone num-",
         {"e2e_latency": 3.90, "llm_node_ttft": 0.90, "tts_node_ttfb": 0.40},
         interrupted=True)
    return ctx


def build_realtime_call() -> ChatContext:
    """A speech-to-speech call: the session records when each side started and
    stopped speaking, but never the gap, so the gap has to be derived."""
    ctx = ChatContext.empty()
    _add(ctx, "user", "hi, are you open on Sunday", {"stopped_speaking_at": 100.0})
    _add(ctx, "assistant", "We are open Sunday mornings.",
         {"started_speaking_at": 100.62})
    _add(ctx, "user", "great, thanks", {"stopped_speaking_at": 110.0})
    _add(ctx, "assistant", "Happy to help.", {"started_speaking_at": 110.48})
    return ctx


def check_realtime() -> None:
    rows = turn_latency.turn_rows(build_realtime_call())
    assert len(rows) == 2, f"expected 2 derived turns, got {len(rows)}"
    assert rows[0]["e2e"] == 620.0, rows[0]
    assert rows[0]["e2e_source"] == "derived", rows[0]
    # No endpointing metric in this mode, so `pipeline` must stay absent, not zero.
    assert rows[0]["endpointing"] is None and rows[0]["pipeline"] is None, rows[0]
    summary = turn_latency.summarize(rows)
    assert summary["e2e_derived"] == 2, summary
    assert "pipeline" not in summary, "a stage with no data must not be reported"
    assert "derived" in turn_latency.format_table(summary)


def check_config_labels() -> None:
    cascaded = {"config": {"voice_mode": "cascaded",
                           "llm": {"provider": "groq", "model": "openai/gpt-oss-120b"}}}
    realtime_call = {"config": {"voice_mode": "realtime",
                                "llm": {"provider": "openai-realtime", "model": "gpt-realtime"}}}
    assert turn_latency.config_label(cascaded) == "cascaded: groq openai/gpt-oss-120b"
    assert turn_latency.config_label(realtime_call) == "realtime: openai-realtime gpt-realtime"
    # A call archived before configs were recorded must still group, not crash.
    assert turn_latency.config_label({}) == "unknown: unrecorded config"


def main() -> int:
    rows = turn_latency.turn_rows(build_call())
    assert len(rows) == 3, f"expected 3 answered turns, got {len(rows)}"
    assert rows[0]["e2e"] == 1550.0, rows[0]
    assert rows[0]["endpointing"] == 920.0, rows[0]
    assert rows[0]["pipeline"] == 630.0, "pipeline must be e2e minus endpointing"
    assert rows[2]["interrupted"] is True, rows[2]

    summary = turn_latency.summarize(rows)
    assert summary["turns"] == 3
    assert summary["turns_interrupted"] == 1
    assert summary["e2e"]["n"] == 2, "interrupted turns must not reach the stats"
    assert summary["e2e"]["p50"] == 1280.0 and summary["e2e"]["p95"] == 1550.0

    # Nearest-rank, so a percentile is always an observed value.
    assert turn_latency.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95) == 10
    assert turn_latency.percentile([42], 0.95) == 42

    # A call with no answered turn must summarize, not crash.
    empty = turn_latency.summarize([])
    assert empty["turns"] == 0 and "e2e" not in empty

    assert all(r["e2e_source"] == "framework" for r in rows), rows

    check_realtime()
    check_config_labels()

    print(turn_latency.format_table(summary))
    print(
        "\nlatency self-test OK (cascaded: 3 turns, 1 interrupted excluded; "
        "realtime: 2 derived turns; config labels)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
