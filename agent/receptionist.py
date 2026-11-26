"""The receptionist Agent definition and its function tools.

The tools are thin: each one calls a core helper in tools/ (which persists to the
server and publishes an agent-state event), then returns a short instruction
string the LLM uses to phrase its spoken reply. Tools never fabricate a result,
so on failure the LLM apologizes instead of claiming success.
"""
from __future__ import annotations

import re
import unicodedata
from typing import AsyncIterable

from livekit.agents import Agent, ModelSettings, RunContext, function_tool

import cached_audio
from language import classify, enabled_languages, has_other_indic, next_language, normalize_digits, words
from prompts import UNSUPPORTED_LINE, build_system_prompt, greeting_for
from policy import load_policy
from server_client import ServerClient
from state import AgentStatePublisher, CallState
from tools.appointments import book_appointment, check_availability, format_slot_time_hi
from tools.faq import answer_faq
from tools.intake import _canonical_field, apply_intake
from tools.routing import hindi_department, route_to_department

# Matches a single leading tone tag like "[happy] " that a model might still emit.
_TONE_TAG_RE = re.compile(r"^\s*\[[^\]]*\]\s*")

# Insert a space after sentence/clause punctuation when it is run into the next
# word ("please?Could" -> "please? Could"), so muga hears a boundary and pauses.
# The letter-only lookahead leaves numbers intact (9.30, 9:30 stay as-is).
_PUNCT_SPACE_RE = re.compile(r"([.,!?;:])(?=[A-Za-z])")


_TOOL_NAMES = ("update_intake", "check_availability", "book_appointment", "answer_faq",
               "route_to_department", "functions.")
_JSON_BLOB_RE = re.compile(r"\{.*\}", re.DOTALL)
_SENTENCE_RE = re.compile(r"[^.!?]*[.!?]?")
LEAK_FALLBACK = "Sorry, one moment. Could you say that again?"


def _strip_leaked_calls(text: str) -> str:
    """Remove tool-call JSON and tool-name narration the model wrote as speech.

    gpt-oss sometimes writes a call into its reply instead of making it. On a
    phone line that JSON would be read aloud. The call itself is lost; the
    caller is asked to repeat so the model gets another turn to make it.
    """
    blob = _JSON_BLOB_RE.search(text)
    if blob and any(key in blob.group(0) for key in ('"arguments"', '"tool"', '"option"', '"department"', '"field"')):
        text = text[: blob.start()] + text[blob.end():]
    sentences = [s for s in _SENTENCE_RE.findall(text) if s.strip() and not any(name in s for name in _TOOL_NAMES)]
    return " ".join(s.strip() for s in sentences).strip()


def _clean_reply(text: str) -> str:
    """Prepare the model's reply for both speech and the transcript:

    - remove tool-call JSON or tool names the model wrote instead of calling,
    - drop any stray leading tone tag (the voice is pinned to one style),
    - keep at most one question so a rambling turn cannot ask two things,
    - normalize punctuation spacing so the TTS pauses naturally at full stops and
      commas. Delivery is neutral and accurate; there is no emotion handling.
    """
    text = _TONE_TAG_RE.sub("", text, count=1).strip()
    if any(name in text for name in _TOOL_NAMES) or _JSON_BLOB_RE.search(text):
        text = _strip_leaked_calls(text) or LEAK_FALLBACK
    first = text.find("?")
    if first != -1 and "?" in text[first + 1 :]:
        text = text[: first + 1].strip()
    text = _PUNCT_SPACE_RE.sub(r"\1 ", text)
    return text


# Times the model may say without a tool result: the clinic's own hours from
# the prompt (8 AM-8 PM, visitors 10 AM-7 PM), as 12-hour (hour, minute).
_CLINIC_INFO_TIMES = {(8, 0), (10, 0), (7, 0)}
_SPOKEN_TIME_RE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(?:a\.?m\.?|p\.?m\.?|in the (?:morning|afternoon|evening))"
    r"|\b(\d{1,2}):(\d{2})\b", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_OFFER_CUE_RE = re.compile(r"slot|available|opening|option|appointment|book", re.IGNORECASE)
SLOT_GUARD_REPLY = "Let me check the available times for you first."
SLOT_GUARD_REPLY_HI = "एक मिनट, मैं पहले उपलब्ध समय देख लेती हूँ।"


def _spoken_times(text: str) -> set[tuple[int, int]]:
    times = set()
    for match in _SPOKEN_TIME_RE.finditer(text):
        hour = match.group(1) or match.group(3)
        minute = match.group(2) or match.group(4) or "0"
        times.add((int(hour) % 12 or 12, int(minute)))
    return times


# Hindi clock times. Matched on NFC text with ASCII digits; no \b, because
# Python's \w does not cover Devanagari vowel signs.
def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


_HI_BAJE = {_nfc(w) for w in ("बजे", "बज", "baje", "baj")}
_HI_DIGIT_TIME_RE = re.compile(r"(?<!\d)(\d{1,2})(?::(\d{2}))?\s*(?:बजे|बज|baje)", re.IGNORECASE)
_HI_PERIOD_TIME_RE = re.compile(
    r"(?:सुबह|दोपहर|शाम|रात|subah|subha|dopahar|dopehar|shaam|sham|raat)\s*(\d{1,2})(?::(\d{2}))?",
    re.IGNORECASE)
_HI_HOURS = {_nfc(k): v for k, v in {
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "छः": 6, "सात": 7,
    "आठ": 8, "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhah": 6,
    "chhe": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10, "gyarah": 11, "barah": 12,
}.items()}
# साढ़े N = N:30, सवा N = N:15, पौने N = (N-1):45.
_HI_FRACTIONS = {_nfc(k): v for k, v in {
    "साढ़े": 30, "साढे": 30, "sadhe": 30, "saadhe": 30, "सवा": 15, "sava": 15, "savaa": 15,
    "पौने": -15, "paune": -15, "pone": -15,
}.items()}
_HI_FIXED = {_nfc(k): v for k, v in {
    "डेढ़": (1, 30), "डेढ": (1, 30), "dedh": (1, 30), "ढाई": (2, 30), "dhai": (2, 30), "dhaai": (2, 30),
}.items()}


def _hour_value(token: str) -> int | None:
    if token.isdigit() and token.isascii() and 1 <= int(token) <= 12:
        return int(token)
    return _HI_HOURS.get(token)


def _hindi_times(text: str) -> set[tuple[int, int]]:
    text = normalize_digits(_nfc(text))
    times = set()
    for match in _HI_DIGIT_TIME_RE.finditer(text):
        times.add((int(match.group(1)) % 12 or 12, int(match.group(2) or 0)))
    for match in _HI_PERIOD_TIME_RE.finditer(text):
        times.add((int(match.group(1)) % 12 or 12, int(match.group(2) or 0)))
    tokens = words(text)
    for i, token in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if token in _HI_FIXED:
            times.add(_HI_FIXED[token])
        elif token in _HI_FRACTIONS and _hour_value(nxt):
            hour, offset = _hour_value(nxt), _HI_FRACTIONS[token]
            times.add(((hour - 1) % 12 or 12, 45) if offset < 0 else (hour, offset))
        elif token in _HI_HOURS and nxt in _HI_BAJE and (i == 0 or tokens[i - 1] not in _HI_FRACTIONS):
            times.add((_HI_HOURS[token], 0))
    return times


def _unsupported_times(text: str, offered: list[dict], booking: dict | None, caller_text: str = "",
                       hindi: bool = False) -> bool:
    """True when a reply offers appointment times no tool returned.

    gpt-oss sometimes says it is checking availability and then invents slots
    without calling the tool. Those times are never spoken: the reply is
    replaced so the model gets another turn to make the real call.

    In Hindi the English offer words never appear, so Hindi mode fails closed:
    every time in the reply is checked, whatever the wording.
    """
    if not hindi and not _OFFER_CUE_RE.search(text):
        return False
    if _ISO_DATE_RE.search(text):
        return True
    from datetime import datetime
    spoken = _spoken_times(text) | (_hindi_times(text) if hindi else set())
    # Echoing a time the caller asked for ("no slot at 9:30 yesterday") is not
    # an offer; only times nobody supplied are blocked.
    allowed = set(_CLINIC_INFO_TIMES) | _spoken_times(caller_text)
    if hindi:
        allowed |= _hindi_times(caller_text)
    for start in [s["start"] for s in offered] + ([booking["start"]] if booking and booking.get("start") else []):
        dt = datetime.fromisoformat(start)
        allowed.add((dt.hour % 12 or 12, dt.minute))
    return bool(spoken - allowed)


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


# Hindi digit words, Devanagari and Roman. Used only in Hindi mode: "do" (2) is
# also an English word.
_HI_DIGIT_WORDS = {_nfc(k): v for k, v in {
    "शून्य": "0", "ज़ीरो": "0", "जीरो": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4",
    "पांच": "5", "पाँच": "5", "छह": "6", "छः": "6", "छे": "6", "सात": "7", "आठ": "8", "नौ": "9",
    "shunya": "0", "sunya": "0", "ek": "1", "do": "2", "teen": "3", "char": "4", "chaar": "4",
    "paanch": "5", "panch": "5", "chhah": "6", "chhe": "6", "cheh": "6", "saat": "7", "aath": "8",
    "nau": "9",
}.items()}


def _spoken_digits(text: str, hindi: bool = False) -> str:
    """The digits the caller actually spoke, from literal digits and digit words."""
    out = []
    if hindi:
        text = normalize_digits(_nfc(text))
        tokens = re.findall(r"\d|[a-z\u0900-\u0963\u0966-\u097F]+", (text or "").lower())
    else:
        tokens = re.findall(r"\d|[a-z]+", (text or "").lower())
    for tok in tokens:
        if tok.isdigit():
            out.append(tok)
        elif tok in _DIGIT_WORDS:
            out.append(_DIGIT_WORDS[tok])
        elif hindi and tok in _HI_DIGIT_WORDS:
            out.append(_HI_DIGIT_WORDS[tok])
    return "".join(out)


# Hindi refusals and hedges: no, don't, wait, maybe, or. Matched as whole
# tokens ("लिया" contains "या" but is not "or").
_HI_REFUSALS = {_nfc(w) for w in (
    "नहीं", "नही", "ना", "मत", "रुको", "रुकिए", "रुकिये", "रुकें", "शायद", "या", "कैंसल",
    "nahi", "nahin", "nai", "mat", "ruko", "rukiye", "rukie", "shayad", "ya", "cancel",
)}
# Only the unambiguous ordinal forms: "पहले" also means "before", so it is not
# a choice.
_HI_ORDINALS = {_nfc(k): v for k, v in {
    "पहला": 1, "पहली": 1, "pehla": 1, "pahla": 1, "pehli": 1, "pahli": 1,
    "दूसरा": 2, "दूसरी": 2, "doosra": 2, "dusra": 2, "doosri": 2, "dusri": 2,
    "तीसरा": 3, "तीसरी": 3, "teesra": 3, "tisra": 3, "teesri": 3, "tisri": 3,
}.items()}


def _explicit_choice(text: str, slots: list[dict], hindi: bool = False) -> int | None:
    """Conservative consent check: ambiguity requires another patient turn.

    This recognizes explicit option ordinals or an exact displayed clock time.
    It is deliberately narrower than general language understanding. Semantic
    intent remains a separate evaluation criterion; a tool argument is not proof.
    In Hindi mode, Hindi refusals, hedges and ordinals count too.
    """
    text = text.lower().strip()
    choices = set()
    if hindi:
        text = normalize_digits(_nfc(text))
        tokens = words(text)
        if any(t in _HI_REFUSALS for t in tokens):
            return None
        choices |= {_HI_ORDINALS[t] for t in tokens if t in _HI_ORDINALS}
    if re.search(r"\b(no|not|don.?t|wait|maybe|either|or|hold|cancel)\b", text):
        return None
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


LANGUAGE_NOTE_PREFIX = "[language note] "
LANGUAGE_NOTES = {
    "hi": (
        "The caller is speaking Hindi. Reply in natural Hindi: Hindi words in "
        "Devanagari, everyday English clinic words (appointment, doctor, department "
        "names) in Latin letters. When a tool result gives a Hindi time label, say it "
        "exactly as written. Record intake values in English: the name in Latin "
        "letters, the symptom as a short English phrase, age and phone as plain digits."
    ),
    "en": "The caller is speaking English. Reply in English.",
    "other": (
        "The caller is speaking a language this clinic cannot support. Reply with "
        f"exactly this and nothing else: {UNSUPPORTED_LINE} If they describe chest "
        "pain, trouble breathing, severe bleeding or stroke signs, first call "
        "route_to_department with Emergency."
    ),
}


class Receptionist(Agent):
    def __init__(
        self,
        state: CallState,
        server: ServerClient,
        publisher: AgentStatePublisher,
        languages: tuple[str, ...] | None = None,
    ) -> None:
        self.policy = load_policy()
        languages = enabled_languages() if languages is None else languages
        state.languages = languages
        if "hi" in languages:
            # A Hindi-enabled clinic greets in Hindi, so it starts in Hindi.
            state.language = "hi"
        instructions = build_system_prompt(languages)
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

    @property
    def hindi_enabled(self) -> bool:
        return "hi" in self.state.languages

    @property
    def greeting_text(self) -> str:
        return greeting_for(self.state.languages)[0]

    def language_note(self, caller_text: str) -> str | None:
        """Track the caller's language and tell the model which one to reply in.

        Shared by the live call (on_user_turn_completed) and the eval runner, so
        both follow the same rule. English-only clinics get no note at all.
        """
        if not self.hindi_enabled:
            return None
        if classify(caller_text) == "other":
            return LANGUAGE_NOTE_PREFIX + LANGUAGE_NOTES["other"]
        self.state.language = next_language(
            self.state.language, caller_text, self.state.languages
        )
        return LANGUAGE_NOTE_PREFIX + LANGUAGE_NOTES[self.state.language]

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        """Add this turn's language note. LiveKit passes a temporary copy of the
        context here, so the note steers this reply only and is not kept."""
        note = self.language_note(new_message.text_content or "")
        if note:
            turn_ctx.add_message(role="system", content=note)

    async def on_enter(self) -> None:
        """Speak first: greet the caller as soon as the agent joins.

        Plays the pre-generated greeting audio for an instant start (no LLM or TTS
        round trip), falling back to a live reply only if the cache is missing.
        """
        text, audio, instruction = greeting_for(self.state.languages)
        if cached_audio.has(audio):
            await self.session.say(text, audio=cached_audio.stream(audio))
        else:
            self.session.generate_reply(instructions=instruction)

    def speakable(self, text: str) -> str:
        """The reply as it may be spoken: cleaned, and never offering times a
        tool did not return."""
        cleaned = _clean_reply(text)
        if self.hindi_enabled and has_other_indic(cleaned):
            # Never speak a language nobody on the team can check.
            return UNSUPPORTED_LINE
        hindi = self.state.language == "hi"
        if _unsupported_times(cleaned, self.state.offered_slots, self.state.booking,
                              self._recent_user_text(), hindi=hindi):
            return SLOT_GUARD_REPLY_HI if hindi else SLOT_GUARD_REPLY
        return cleaned

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
        cleaned = self.speakable(full)
        if self.state.language != "hi":
            # English words for times; a Hindi reply keeps the Hindi label.
            cleaned = _normalize_times(cleaned)

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
        cleaned = self.speakable(full)

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
            recorded = re.sub(r"\D", "", normalize_digits(value))
            spoken = _spoken_digits(self._recent_user_text(), hindi=self.state.language == "hi")
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
            if str(result["error"]).startswith("could not save"):
                return (
                    f"Not saved: the clinic system could not store {field} just now, so it does "
                    "not count as recorded. Tell the caller briefly, then call update_intake again "
                    "with the value they already gave. Do not ask them to repeat it."
                )
            return f"Could not record that ({result['error']}). Ask the caller for a corrected value."
        missing = result["data"]["missing"]
        if missing:
            return (
                f"Recorded {field}. Not yet recorded: {', '.join(missing)}. If the caller already "
                "said any of these on this call, record it now with update_intake; ask only for "
                "what they have not said."
            )
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
                f"Do not offer appointment times yet. Not yet recorded: {', '.join(missing)}. "
                "If the caller already said any of these on this call, record each now with "
                "update_intake; otherwise ask for it, one at a time. Check availability once "
                "all are recorded."
            )
        # A Hindi call may name the department in Hindi; English names pass as is.
        department = hindi_department(department) or department
        result = await check_availability(
            self.state, self.server, self.publisher, department, date, not_before, not_after
        )
        self.state.offered_after_user_text = self._recent_user_text(turns=1)
        if not result["ok"]:
            return self.policy["availability_error"].format(error=result["error"])
        slots = result["data"]["slots"]
        if not slots:
            return self.policy["no_slots"].format(department=department)
        hindi = self.state.language == "hi"
        lines = [
            f"{i + 1}. {s['doctor']}, {format_slot_time_hi(s['start'])}" if hindi
            else f"{i + 1}. {s['doctor']} at {s['when']}"
            for i, s in enumerate(slots)
        ]
        return (
            "Available appointments:\n"
            + "\n".join(lines)
            + "\nOffer these numbered options with doctor, date, and time in Asia/Kolkata. "
            "Ask the patient to choose one explicitly; never expose database IDs. When they choose one, call "
            "book_appointment with its option number."
            + (" Say each time exactly as written above." if hindi else "")
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
            choice = _explicit_choice(latest, self.state.offered_slots,
                                      hindi=self.state.language == "hi")
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
        if self.state.language == "hi":
            return (
                f"Booked: {appt['doctor']}, {appt['department']}, {format_slot_time_hi(appt['start'])}. "
                "Confirm the doctor, department, and time to the caller, saying the time exactly as written."
            )
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
