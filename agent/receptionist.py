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

from prompts import GREETING_INSTRUCTION, SYSTEM_PROMPT
from server_client import ServerClient
from state import AgentStatePublisher, CallState
from tools.appointments import book_appointment, check_availability
from tools.faq import answer_faq
from tools.intake import apply_intake
from tools.routing import route_to_department

# Matches a single leading tone tag like "[happy] " that a model might still emit.
_TONE_TAG_RE = re.compile(r"^\s*\[[^\]]*\]\s*")


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
        """Speak first: greet the caller as soon as the agent joins."""
        self.session.generate_reply(instructions=GREETING_INSTRUCTION)

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ) -> AsyncIterable:
        """Strip any leading tone tag before synthesis.

        Rumik muga is pinned to a single tone, and it raises if the text carries a
        conflicting tag. English mode uses no tags, but this guarantees a stray
        one never silences a turn.
        """

        async def scrub() -> AsyncIterable[str]:
            buffer = ""
            done = False
            async for chunk in text:
                if done:
                    yield chunk
                    continue
                buffer += chunk
                lead = buffer.lstrip()
                if not lead:
                    continue
                if lead[0] != "[":
                    yield buffer
                    buffer = ""
                    done = True
                elif "]" in lead:
                    buffer = _TONE_TAG_RE.sub("", buffer, count=1)
                    if buffer:
                        yield buffer
                    buffer = ""
                    done = True
                # else: a partial "[..." is still arriving; keep buffering
            if buffer:
                yield buffer

        async for frame in Agent.default.tts_node(self, scrub(), model_settings):
            yield frame

    @function_tool()
    async def update_intake(
        self, context: RunContext, field: str, value: str
    ) -> str:
        """Record one patient intake detail as soon as the caller gives it.

        Call this once per detail, right after the caller provides it.

        Args:
            field: one of name, dob, phone, symptoms, insurance.
            value: the value the caller gave, as plain text.
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
        """Look up open appointment slots in a department.

        Call this once you know which department the caller needs, before booking.

        Args:
            department: one of Emergency, General Medicine, Pediatrics,
                Orthopedics, Cardiology.
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
        """Book a specific slot for the caller.

        Only call this after check_availability and after the caller picks a time.

        Args:
            slot_id: the slot_id of the chosen slot from check_availability.
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
        """Log that you answered a frequently asked question, for the timeline.

        Call this right after you answer a question about hours, location,
        parking, insurance, or the visitor policy, using the clinic knowledge in
        your instructions.

        Args:
            topic: one of hours, location, parking, insurance, visiting.
        """
        await answer_faq(self.state, self.server, self.publisher, topic)
        return "Logged. Continue helping the caller."

    @function_tool()
    async def route_to_department(
        self, context: RunContext, department: str, reason: str
    ) -> str:
        """Route the caller to the right department.

        Use for a normal transfer once you know the department, or immediately
        for an emergency (chest pain, trouble breathing, severe bleeding, stroke).

        Args:
            department: one of Emergency, General Medicine, Pediatrics,
                Orthopedics, Cardiology.
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
