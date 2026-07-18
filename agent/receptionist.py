"""The receptionist Agent definition and its function tools.

The tools are thin: each one calls a core helper in tools/ (which persists to the
server and publishes an agent-state event), then returns a short instruction
string the LLM uses to phrase its spoken reply. Tools never fabricate a result,
so on failure the LLM apologizes instead of claiming success.
"""
from __future__ import annotations

import re
from typing import AsyncIterable

from livekit.agents import Agent, ModelSettings, RunContext, function_tool

import cached_audio
from prompts import GREETING_INSTRUCTION, GREETING_TEXT, SYSTEM_PROMPT
from server_client import ServerClient
from state import AgentStatePublisher, CallState
from tools.appointments import book_appointment, check_availability
from tools.faq import answer_faq
from tools.intake import apply_intake
from tools.routing import route_to_department

# Matches a single leading tone tag like "[happy] " that a model might still emit.
_TONE_TAG_RE = re.compile(r"^\s*\[[^\]]*\]\s*")


def _clean_reply(text: str) -> str:
    """Prepare the model's reply for speech: drop any leading tone tag, and keep
    at most one question so a rambling turn cannot ask two things (or rephrase the
    same question) at once."""
    text = _TONE_TAG_RE.sub("", text, count=1).strip()
    first = text.find("?")
    if first != -1 and "?" in text[first + 1 :]:
        text = text[: first + 1].strip()
    return text


class Receptionist(Agent):
    def __init__(
        self,
        state: CallState,
        server: ServerClient,
        publisher: AgentStatePublisher,
    ) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)
        self.state = state
        self.server = server
        self.publisher = publisher

    async def on_enter(self) -> None:
        """Speak first: greet the caller as soon as the agent joins.

        Plays the pre-generated greeting audio for an instant start (no LLM or TTS
        round trip), falling back to a live reply only if the cache is missing.
        """
        if cached_audio.has("greeting.wav"):
            await self.session.say(
                GREETING_TEXT, audio=cached_audio.stream("greeting.wav")
            )
        else:
            self.session.generate_reply(instructions=GREETING_INSTRUCTION)

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ) -> AsyncIterable:
        """Clean the model's reply before synthesis.

        Strips any stray tone tag (Rumik muga is pinned to one tone and raises on a
        conflicting tag) and keeps at most one question. muga aggregates the full
        response before speaking anyway, so buffering the text here costs nothing.
        """
        full = ""
        async for chunk in text:
            full += chunk
        cleaned = _clean_reply(full)

        async def single() -> AsyncIterable[str]:
            if cleaned:
                yield cleaned

        async for frame in Agent.default.tts_node(self, single(), model_settings):
            yield frame

    async def transcription_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ) -> AsyncIterable:
        """Clean the forwarded transcript the same way as the audio, so the
        dashboard shows exactly what was spoken (one question, no stray tone tag)
        instead of the model's raw, possibly-doubled reply.
        """
        full = ""
        async for chunk in text:
            full += chunk
        cleaned = _clean_reply(full)

        async def single() -> AsyncIterable[str]:
            if cleaned:
                yield cleaned

        async for out in Agent.default.transcription_node(
            self, single(), model_settings
        ):
            yield out

    @function_tool()
    async def update_intake(
        self, context: RunContext, field: str, value: str
    ) -> str:
        """Record one detail the caller just said. Only with a value they actually
        gave (never invented).

        Args:
            field: one of name, age, phone, symptoms.
            value: the value the caller gave.
        """
        result = await apply_intake(
            self.state, self.server, self.publisher, field, value
        )
        if not result["ok"]:
            return f"Could not record that ({result['error']}). Continue naturally."
        missing = result["data"]["missing"]
        if missing:
            return f"Recorded {field}. Still need: {', '.join(missing)}."
        return f"Recorded {field}. All intake details are collected."

    @function_tool()
    async def check_availability(self, context: RunContext, department: str) -> str:
        """Look up open slots in a department, before booking.

        Args:
            department: Emergency, General Medicine, Pediatrics, Orthopedics, or
                Cardiology.
        """
        result = await check_availability(
            self.state, self.server, self.publisher, department
        )
        if not result["ok"]:
            return f"Could not check availability ({result['error']}). Offer a callback."
        slots = result["data"]["slots"]
        if not slots:
            return f"No open slots in {department} right now. Offer to take a callback."
        lines = [
            f"slot_id {s['slot_id']}: {s['doctor']}, {s['when']}" for s in slots
        ]
        return (
            "Open slots:\n"
            + "\n".join(lines)
            + "\nRead these times to the caller, ask which they prefer, then call "
            "book_appointment with that slot_id."
        )

    @function_tool()
    async def book_appointment(
        self, context: RunContext, slot_id: int, reason: str = ""
    ) -> str:
        """Book a slot the caller picked from check_availability.

        Args:
            slot_id: the chosen slot_id.
            reason: the visit reason or symptom, if known.
        """
        result = await book_appointment(
            self.state, self.server, self.publisher, slot_id, reason
        )
        if not result["ok"]:
            return (
                f"Booking did not go through ({result['error']}). Apologize and offer "
                "a callback. Do not tell the caller it is booked."
            )
        appt = result["data"]
        return (
            f"Booked: {appt['doctor']}, {appt['department']}, {appt['when']}. "
            "Confirm this warmly to the caller."
        )

    @function_tool()
    async def answer_faq(self, context: RunContext, topic: str) -> str:
        """Log an answered FAQ, after answering from the clinic info.

        Args:
            topic: hours, location, parking, insurance, or visiting.
        """
        await answer_faq(self.state, self.server, self.publisher, topic)
        return "Logged. Continue helping the caller."

    @function_tool()
    async def route_to_department(
        self, context: RunContext, department: str, reason: str
    ) -> str:
        """Route the caller to a department. Use immediately for emergencies.

        Args:
            department: Emergency, General Medicine, Pediatrics, Orthopedics, or
                Cardiology.
            reason: a short reason for the routing.
        """
        result = await route_to_department(
            self.state, self.server, self.publisher, department, reason
        )
        if not result["ok"]:
            return f"Could not route ({result['error']})."
        if result["data"]["emergency"]:
            return (
                "Routed to Emergency. Tell the caller calmly and urgently that you "
                "are connecting them to Emergency right now."
            )
        return (
            f"Routed to {result['data']['department']}. Tell the caller you are "
            "transferring them and to hold briefly."
        )
