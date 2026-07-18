"""answer_faq: log which FAQ topic was answered.

The agent answers FAQs directly from the clinic knowledge in its system prompt
(no RAG for 10 items). This tool exists purely to record the detour on the
timeline and analytics, so the dashboard can show it.
"""
from __future__ import annotations

from state import AgentStatePublisher, CallState
from server_client import ServerClient

FAQ_TOPICS = {"hours", "location", "parking", "insurance", "visiting"}


async def answer_faq(
    state: CallState,
    server: ServerClient,
    publisher: AgentStatePublisher,
    topic: str,
) -> dict:
    topic = topic.strip().lower()
    normalized = topic if topic in FAQ_TOPICS else "other"
    await publisher.publish("faq", {"topic": normalized, "raw": topic})
    return {"ok": True, "data": {"topic": normalized}}
