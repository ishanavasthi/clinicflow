"""Per-turn latency for the voice pipeline.

What a caller feels is the silence between finishing their sentence and hearing
the agent start to speak. LiveKit times the pieces of that silence onto every
chat message; this module reads them off a call, turns them into one row per
turn, and summarizes them:

    caller stops speaking
      |-- endpointing     VAD plus the configured patience window end the turn
      |-- transcription   Deepgram returns the final transcript
      |-- llm_ttft        the LLM produces its first token (tool steps included)
      |-- tts_ttfb        Rumik returns the first audio chunk
    agent starts speaking

`e2e` is the gap between those two moments, measured by the framework itself, so
it also carries scheduling overhead the four stages do not add up to. Read it
with one caveat: **endpointing is mostly a deliberate wait, not provider
latency**, because main.py sets `min_endpointing_delay` so the agent sits through
a natural pause instead of interrupting. `pipeline` (e2e minus endpointing) is
the part that engineering can actually shrink, so both are reported.

Everything here is read-only and runs after the fact; nothing touches the audio
path.
"""
from __future__ import annotations

import math
from typing import Any

# Ordered as the caller experiences them; `e2e` and `pipeline` are the totals.
FIELDS = (
    "e2e",
    "pipeline",
    "endpointing",
    "transcription",
    "llm_ttft",
    "tts_ttfb",
)

LABELS = {
    "e2e": "end to end (heard pause)",
    "pipeline": "pipeline (e2e - endpointing)",
    "endpointing": "endpointing (mostly configured wait)",
    "transcription": "transcription (Deepgram)",
    "llm_ttft": "LLM first token (Groq)",
    "tts_ttfb": "TTS first audio (Rumik)",
}


def _ms(value: Any) -> float | None:
    """Seconds to milliseconds, one decimal. None for a stage that never ran."""
    if isinstance(value, (int, float)):
        return round(float(value) * 1000, 1)
    return None


def _metrics_of(item: Any) -> dict:
    metrics = getattr(item, "metrics", None)
    return dict(metrics) if isinstance(metrics, dict) else {}


def turn_rows(chat_ctx: Any) -> list[dict]:
    """One row per answered caller turn, oldest first.

    A turn only counts once the agent actually spoke back, so the opening
    greeting (no caller turn before it) and any reply cut off before audio
    started are absent: they have no `e2e_latency` to report.
    """
    rows: list[dict] = []
    pending_user: dict = {}

    for item in getattr(chat_ctx, "items", []) or []:
        role = getattr(item, "role", None)
        if role == "user":
            pending_user = _metrics_of(item)
            continue
        if role != "assistant":
            continue

        assistant = _metrics_of(item)
        e2e = _ms(assistant.get("e2e_latency"))
        if e2e is None:
            continue

        endpointing = _ms(pending_user.get("end_of_turn_delay"))
        rows.append(
            {
                "turn": len(rows) + 1,
                "e2e": e2e,
                # What is left after the deliberate wait: the work, not the pause.
                "pipeline": (
                    round(e2e - endpointing, 1) if endpointing is not None else None
                ),
                "endpointing": endpointing,
                "transcription": _ms(pending_user.get("transcription_delay")),
                "llm_ttft": _ms(assistant.get("llm_node_ttft")),
                "tts_ttfb": _ms(assistant.get("tts_node_ttfb")),
                "interrupted": bool(getattr(item, "interrupted", False)),
            }
        )
        pending_user = {}

    return rows


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile. Small samples make interpolation a fiction."""
    if not values:
        raise ValueError("percentile of an empty sample")
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(pct * len(ordered))))
    return ordered[rank - 1]


def summarize(rows: list[dict]) -> dict:
    """Per-stage n / p50 / p95 / min / max in milliseconds.

    Interrupted turns are excluded: the caller talked over the agent, so the
    measured gap is their timing, not the pipeline's.
    """
    clean = [r for r in rows if not r.get("interrupted")]
    summary: dict[str, Any] = {
        "turns": len(rows),
        "turns_measured": len(clean),
        "turns_interrupted": len(rows) - len(clean),
        "unit": "ms",
    }
    for field in FIELDS:
        values = [r[field] for r in clean if isinstance(r.get(field), (int, float))]
        if not values:
            continue
        summary[field] = {
            "n": len(values),
            "p50": round(percentile(values, 0.50), 1),
            "p95": round(percentile(values, 0.95), 1),
            "min": round(min(values), 1),
            "max": round(max(values), 1),
            "mean": round(sum(values) / len(values), 1),
        }
    return summary


def format_table(summary: dict) -> str:
    """The summary as a fixed-width table, for a log line or a terminal."""
    header = (
        f"{'stage':38}{'n':>4}{'p50':>9}{'p95':>9}{'min':>9}{'max':>9}{'mean':>9}"
    )
    lines = [header, "-" * len(header)]
    for field in FIELDS:
        stat = summary.get(field)
        if not stat:
            continue
        lines.append(
            f"{LABELS[field]:38}{stat['n']:>4}"
            f"{stat['p50']:>9.0f}{stat['p95']:>9.0f}"
            f"{stat['min']:>9.0f}{stat['max']:>9.0f}{stat['mean']:>9.0f}"
        )
    lines.append("-" * len(header))
    lines.append(
        f"{summary.get('turns_measured', 0)} turn(s) measured, "
        f"{summary.get('turns_interrupted', 0)} interrupted and excluded. "
        "Milliseconds."
    )
    return "\n".join(lines)
