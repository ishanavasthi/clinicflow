"""The receptionist Agent definition.

M1: the Agent carries the system prompt and persona. M2 attaches the five
function tools (intake, availability, booking, FAQ logging, routing) here.
"""
from __future__ import annotations

from livekit.agents import Agent

from prompts import SYSTEM_PROMPT


class Receptionist(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)
