"""Offline check of the latency extraction (no keys, no network, no audio).

Builds a chat context shaped exactly like a finished call, with the timings the
framework writes onto each message, and asserts the report reads it correctly:
the greeting is not a turn, an interrupted reply is excluded from the stats, and
`pipeline` is `e2e` minus the endpointing wait.

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

    print(turn_latency.format_table(summary))
    print("\nlatency self-test OK (3 turns parsed, 1 interrupted excluded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
