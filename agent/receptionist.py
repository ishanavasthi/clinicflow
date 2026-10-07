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
from policy import load_policy
from server_client import ServerClient
from state import AgentStatePublisher, CallState
from tools.appointments import book_appointment, check_availability
from tools.faq import answer_faq
from tools.intake import _canonical_field, apply_intake
from tools.routing import route_to_department

# Matches a single leading tone tag like "[happy] " that a model might still emit.
_TONE_TAG_RE = re.compile(r"^\s*\[[^\]]*\]\s*")

# Insert a space after sentence/clause punctuation when it is run into the next
# word ("please?Could" -> "please? Could"), so muga hears a boundary and pauses.
# The letter-only lookahead leaves numbers intact (9.30, 9:30 stay as-is).
_PUNCT_SPACE_RE = re.compile(r"([.,!?;:])(?=[A-Za-z])")


def _clean_reply(text: str) -> str:
    """Prepare the model's reply for both speech and the transcript:

    - drop any stray leading tone tag (the voice is pinned to one style),
    - keep at most one question so a rambling turn cannot ask two things,
    - normalize punctuation spacing so the TTS pauses naturally at full stops and
      commas. Delivery is neutral and accurate; there is no emotion handling.
    """
    text = _TONE_TAG_RE.sub("", text, count=1).strip()
    first = text.find("?")
    if first != -1 and "?" in text[first + 1 :]:
        text = text[: first + 1].strip()
    text = _PUNCT_SPACE_RE.sub(r"\1 ", text)
    return text


_NUM_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen",
    17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty", 30: "thirty",
    40: "forty", 50: "fifty",
}


def _num_to_words(n: int) -> str:
    if n in _NUM_WORDS:
        return _NUM_WORDS[n]
    tens, ones = divmod(n, 10)
    return f"{_NUM_WORDS[tens * 10]} {_NUM_WORDS[ones]}"


def _clock(hour: int, minute: int) -> str:
    h12 = hour % 12 or 12
    if minute == 0:
        return _num_to_words(h12)
    if minute < 10:
        return f"{_num_to_words(h12)} oh {_num_to_words(minute)}"
    return f"{_num_to_words(h12)} {_num_to_words(minute)}"


# Whitespace incl. the narrow / no-break spaces some models emit before am/pm.
_WS = r"\s*"  # \s matches the narrow / no-break spaces models emit
_MERIDIEM_TIME_RE = re.compile(
    rf"\b(\d{{1,2}})(?::(\d{{2}}))?{_WS}([ap])\.?{_WS}m\.?\b", re.IGNORECASE
)
_BARE_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def _spell_meridiem(m: "re.Match[str]") -> str:
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    h12 = hour % 12 or 12
    if m.group(3).lower() == "a":
        period = "in the morning"
    else:
        period = "in the afternoon" if h12 in (12, 1, 2, 3, 4) else "in the evening"
    return f"{_clock(hour, minute)} {period}"


def _normalize_times(text: str) -> str:
    """Spell out clock times for speech so the TTS never voices the meridiem twice
    ('9:30 am' -> 'nine thirty in the morning', '9:30' -> 'nine thirty'). Applied to
    the spoken audio only; the transcript keeps the compact digit form."""
    text = _MERIDIEM_TIME_RE.sub(_spell_meridiem, text)
    text = _BARE_TIME_RE.sub(lambda m: _clock(int(m.group(1)), int(m.group(2))), text)
    return text


# Single-digit words, so we can tell what digits the caller actually spoke and
# reject a fabricated phone number the model invents (a recurring failure).
_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "o": "0", "nought": "0", "one": "1", "two": "2",
    "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9",
}


def _spoken_digits(text: str) -> str:
    """The digits the caller actually spoke, from literal digits and digit words."""
    out = []
    for tok in re.findall(r"\d|[a-z]+", (text or "").lower()):
        if tok.isdigit():
            out.append(tok)
        elif tok in _DIGIT_WORDS:
            out.append(_DIGIT_WORDS[tok])
    return "".join(out)


def _explicit_choice(text: str, slots: list[dict]) -> int | None:
    """Conservative consent check: ambiguity requires another patient turn.

    This recognizes explicit option ordinals or an exact displayed clock time.
    It is deliberately narrower than general language understanding. Semantic
    intent remains a separate evaluation criterion; a tool argument is not proof.
    """
    text = text.lower().strip()
    if re.search(r"\b(no|not|don.?t|wait|maybe|either|or|hold|cancel)\b", text):
        return None
    choices = set()
    for n, word in enumerate(("first", "second", "third"), 1):
        if re.search(rf"\b{word}\b", text):
            choices.add(n)
    for match in re.finditer(r"\b(?:option|number|slot|book|take|choose|pick)\s+([123])\b", text):
        choices.add(int(match.group(1)))
    if text.rstrip('.!') in ('1', '2', '3'):
        choices.add(int(text.rstrip('.!')))
    for n, slot in enumerate(slots, 1):
        from datetime import datetime
        start = datetime.fromisoformat(slot["start"])
        clock = f"{start.hour % 12 or 12}:{start.minute:02d}"
        if re.search(rf"(?<!\d){re.escape(clock)}(?!\d)", text):
            choices.add(n)
    return next(iter(choices)) if len(choices) == 1 else None


class Receptionist(Agent):
    def __init__(
        self,
        state: CallState,
        server: ServerClient,
        publisher: AgentStatePublisher,
    ) -> None:
        self.policy = load_policy()
        instructions = SYSTEM_PROMPT
        if self.policy["system_addendum"]:
            instructions += "\n\n" + self.policy["system_addendum"]
        super().__init__(instructions=instructions)
        self.state = state
        self.server = server
        self.publisher = publisher

    def _recent_user_text(self, turns: int = 3) -> str:
        """The caller's last few messages, used to verify a phone was really said."""
        session = getattr(self, "session", None)
        items = getattr(getattr(session, "history", None), "items", []) or []
        texts: list[str] = []
        for item in reversed(list(items)):
            if getattr(item, "role", None) != "user":
                continue
            content = getattr(item, "content", None)
            text = (
                content
                if isinstance(content, str)
                else " ".join(p for p in (content or []) if isinstance(p, str))
            )
            if text.strip():
                texts.append(text)
                if len(texts) >= turns:
                    break
        return " ".join(reversed(texts))

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

        Strips any stray tone tag, keeps at most one question, and spells out clock
        times so the TTS reads them once and naturally ("9:30 am" -> "nine thirty in
        the morning"). Buffering the whole reply here is fine; it is short.
        """
        full = ""
        async for chunk in text:
            full += chunk
        cleaned = _normalize_times(_clean_reply(full))

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
        if self.state.emergency:
            return "Emergency escalation is active. Stop routine intake and follow the escalation instructions."
        # Guard against a fabricated phone: only record digits the caller actually
        # spoke recently. Catches the model inventing a placeholder number.
        if _canonical_field(field) == "phone":
            recorded = re.sub(r"\D", "", value)
            spoken = _spoken_digits(self._recent_user_text())
            if len(recorded) >= 7 and recorded not in spoken:
                return (
                    "The caller has not actually given their phone number yet. Ask "
                    "for their 10-digit number and wait for them to say it; never "
                    "guess or use an example number."
                )
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
    async def check_availability(
        self, context: RunContext, department: str, date: str | None = None,
        not_before: str | None = None, not_after: str | None = None,
    ) -> str:
        """Look up open slots in a department, before booking.

        Args:
            department: Emergency, General Medicine, Pediatrics, Orthopedics, or
                Cardiology.
            date: requested clinic-local date in YYYY-MM-DD, if supplied.
            not_before: earliest acceptable clinic-local time HH:MM, if supplied.
            not_after: latest acceptable clinic-local time HH:MM, if supplied.
        """
        # Do not offer appointment times until intake is complete. The model tends
        # to rush ahead and check availability before the caller has given every
        # detail (the phone especially); make that impossible, not just discouraged.
        missing = self.state.missing_intake()
        if missing:
            return (
                "Do not offer appointment times yet. First ask for the caller's "
                f"{', '.join(missing)}, one at a time, and wait for each answer. "
                "Check availability only once you have them all."
            )
        result = await check_availability(
            self.state, self.server, self.publisher, department, date, not_before, not_after
        )
        self.state.offered_after_user_text = self._recent_user_text(turns=1)
        if not result["ok"]:
            return self.policy["availability_error"].format(error=result["error"])
        slots = result["data"]["slots"]
        if not slots:
            return self.policy["no_slots"].format(department=department)
        lines = [
            f"{i + 1}. {s['doctor']} at {s['when']}" for i, s in enumerate(slots)
        ]
        return (
            "Available appointments:\n"
            + "\n".join(lines)
            + "\nOffer these numbered options with doctor, date, and time in Asia/Kolkata. "
            "Ask the patient to choose one explicitly; never expose database IDs. When they choose one, call "
            "book_appointment with its option number."
        )

    @function_tool()
    async def book_appointment(
        self, context: RunContext, option: int, reason: str = ""
    ) -> str:
        """Book the appointment time the caller chose from check_availability.

        Args:
            option: the option number the caller picked (1, 2, or 3), in the order
                you offered them.
            reason: the visit reason or symptom, if known.
        """
        if self.state.booking is None and self.state.status != "booking_uncertain":
            latest = self._recent_user_text(turns=1)
            choice = _explicit_choice(latest, self.state.offered_slots)
            if latest == self.state.offered_after_user_text or choice != option:
                return "No unambiguous patient choice for this option. Ask which numbered appointment they want and wait. Do not book yet."
            self.state.selection_evidence = latest
        result = await book_appointment(
            self.state, self.server, self.publisher, option, reason
        )
        if not result["ok"]:
            if result.get("code") == "uncertain":
                return result["error"]
            if result.get("code") == "conflict":
                return "That booking was not made. Refresh availability, offer current options, and wait for a new patient choice."
            return self.policy["booking_error"].format(error=result["error"])
        appt = result["data"]
        return (
            f"Booked: {appt['doctor']}, {appt['department']}, {appt['when']}. "
            "Confirm the doctor, department, and time to the caller."
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
            return self.policy["emergency_response"]
        return (
            f"Noted {result['data']['department']} for the caller. Do not put them "
            "on hold or say a person is joining. Offer to book an appointment there "
            "and call check_availability for that department."
        )
