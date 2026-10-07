"""Backoff for rate-limited or transient model-provider responses.

A 429 or 5xx is an infrastructure event, not agent behavior, so every model
caller in the harness waits it out instead of failing the trial.
"""
from __future__ import annotations

RETRYABLE_STATUS = (429, 500, 502, 503, 504)
ATTEMPTS = 8


def retry_delay(headers, attempt: int) -> float:
    """Seconds to wait before retry `attempt` (0-based), honoring Retry-After."""
    value = headers.get("retry-after") if headers else None
    try:
        return min(max(float(value), 1.0), 90.0)
    except (TypeError, ValueError):
        return min(5.0 * 2 ** attempt, 90.0)
