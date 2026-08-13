"""Measure the caller's wait from session events, in any voice mode.

The cascaded pipeline gets its timings for free: LiveKit writes them onto every
ChatMessage. Speech-to-speech does not. In realtime mode the user's message is
built from the model's transcription event, which carries no timing at all (the
framework says as much in a TODO), so `ChatMessage.metrics` has nothing to read
and the mode would go unmeasured.

The session still announces both edges of the gap, though:

    user_state_changed  -> "listening"   the caller stopped speaking
    agent_state_changed -> "speaking"    the agent's first audio frame went out

Timing those two gives the same quantity as the framework's `e2e_latency`, by
the same definition, without depending on the model provider.

Two caveats, both in the honest direction:

- The user event carries the VAD's own speech-stop anchor, but the agent event is
  stamped when it is dispatched rather than when the audio started, so the result
  can run a hair long. It is an upper bound, never flattering.
- Only the total is available this way. There are no stage timings, because in
  speech-to-speech there are no separate stages to time.

In cascaded mode both methods run, which is the point: the framework's numbers
and this clock can be compared on the same calls before the clock is trusted
alone on a realtime call.
"""
from __future__ import annotations

from typing import Any

import turn_latency


class SessionTurnClock:
    """Pairs 'caller stopped' with 'agent started' and records the gap."""

    def __init__(self) -> None:
        self._stopped_at: float | None = None
        self._rows: list[dict] = []

    def attach(self, session: Any) -> None:
        session.on("user_state_changed", self._on_user_state)
        session.on("agent_state_changed", self._on_agent_state)

    def _on_user_state(self, event: Any) -> None:
        if getattr(event, "new_state", None) != "listening":
            return
        if getattr(event, "old_state", None) != "speaking":
            return
        self._stopped_at = getattr(event, "created_at", None)

    def _on_agent_state(self, event: Any) -> None:
        if getattr(event, "new_state", None) != "speaking":
            return
        started_at = getattr(event, "created_at", None)
        stopped_at, self._stopped_at = self._stopped_at, None
        # No pending caller turn means the agent spoke unprompted: the opening
        # greeting, or the error fallback. Neither is a response time.
        if stopped_at is None or started_at is None:
            return
        gap = started_at - stopped_at
        if gap < 0:
            return
        self._rows.append(
            turn_latency.total_only_row(
                turn=len(self._rows) + 1,
                e2e_ms=round(gap * 1000, 1),
                source="session_events",
            )
        )

    def rows(self) -> list[dict]:
        return list(self._rows)
