"""Speech cleaning: tool calls written as text never reach the caller."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from prompts import GREETING_TEXT, GREETING_TEXT_HI, SYSTEM_PROMPT, UNSUPPORTED_LINE, build_system_prompt  # noqa: E402
from receptionist import LEAK_FALLBACK, Receptionist, _clean_reply, _unsupported_times  # noqa: E402
from state import CallState  # noqa: E402

TAMIL = "வணக்கம், எனக்கு மருத்துவர் வேண்டும்"


class _Stub:
    async def publish(self, *args, **kwargs):
        return None


class _OfflineReceptionist(Receptionist):
    """No live session: the caller's recent words come from the test."""
    caller_text = ""

    def _recent_user_text(self, turns: int = 3) -> str:
        return self.caller_text


def agent(languages):
    return _OfflineReceptionist(CallState(), _Stub(), _Stub(), languages=languages)


class ReplyCleaningTests(unittest.TestCase):
    def test_strips_json_tool_call_and_keeps_speech(self):
        raw = 'Booking your appointment now.{   "tool": "book_appointment",   "arguments": {"option": 1} }'
        self.assertEqual(_clean_reply(raw), "Booking your appointment now.")

    def test_drops_narration_naming_a_tool(self):
        raw = "We should call book_appointment. Your slot is noted."
        self.assertEqual(_clean_reply(raw), "Your slot is noted.")

    def test_reply_that_is_only_a_tool_call_falls_back(self):
        self.assertEqual(_clean_reply('{"tool": "functions. check_availability", "arguments": {}}'), LEAK_FALLBACK)

    def test_ordinary_reply_is_unchanged(self):
        self.assertEqual(_clean_reply("May I have your phone number, please?"), "May I have your phone number, please?")


OFFERED = [{"start": "2026-10-08T09:30:00"}, {"start": "2026-10-08T11:00:00"}, {"start": "2026-10-08T14:00:00"}]


class SlotGuardTests(unittest.TestCase):
    def test_invented_slots_without_a_tool_result_are_blocked(self):
        self.assertTrue(_unsupported_times("Here are three slots: 1) 2024-11-05 at 10:00, 2) 14:30.", [], None))
        self.assertTrue(_unsupported_times("We have openings at 10 AM and 2:30 PM.", [], None))

    def test_offered_times_may_be_spoken(self):
        self.assertFalse(_unsupported_times("We have openings at 9:30 AM, 11 AM or 2 PM.", OFFERED, None))

    def test_a_time_not_in_the_offer_is_blocked(self):
        self.assertTrue(_unsupported_times("We have openings at 9:30 AM or 3:30 PM.", OFFERED, None))

    def test_echoing_the_callers_requested_time_is_allowed(self):
        reply = "We cannot book an appointment at 9:30 AM yesterday because that date has passed."
        self.assertFalse(_unsupported_times(reply, [], None, "I need General Medicine yesterday at 9:30 AM."))
        self.assertTrue(_unsupported_times("We have openings at 11 AM.", [], None, "I need yesterday at 9:30 AM."))

    def test_clinic_hours_are_not_appointment_offers(self):
        self.assertFalse(_unsupported_times("We are open from 8 AM to 8 PM, Monday to Saturday.", [], None))



class LanguageModeTests(unittest.TestCase):
    def test_english_prompt_is_unchanged(self):
        self.assertEqual(build_system_prompt(("en",)), SYSTEM_PROMPT)
        bilingual = build_system_prompt(("en", "hi"))
        self.assertIn("Hindi, Hinglish or English", bilingual)
        self.assertNotIn("conversational English", bilingual)

    def test_greeting_follows_the_clinic_languages(self):
        self.assertEqual(agent(("en",)).greeting_text, GREETING_TEXT)
        self.assertEqual(agent(("en", "hi")).greeting_text, GREETING_TEXT_HI)

    def test_hindi_clinic_starts_in_hindi_and_follows_the_caller(self):
        a = agent(("en", "hi"))
        self.assertEqual(a.state.language, "hi")
        self.assertTrue(a.language_note("मुझे खांसी है").startswith("[language note] The caller is speaking Hindi"))
        self.assertEqual(a.state.language, "hi")
        self.assertIn("speaking English", a.language_note("I would like an appointment please"))
        self.assertEqual(a.state.language, "en")
        self.assertIn("speaking English", a.language_note("haan ji"))  # too short to switch back

    def test_unsupported_language_gets_the_fixed_line(self):
        a = agent(("en", "hi"))
        note = a.language_note(TAMIL)
        self.assertIn(UNSUPPORTED_LINE, note)
        self.assertIn("Emergency", note)
        self.assertEqual(a.state.language, "hi")

    def test_english_only_clinic_adds_no_note(self):
        a = agent(("en",))
        self.assertIsNone(a.language_note("मुझे खांसी है"))
        self.assertEqual(a.state.language, "en")

    def test_other_indic_replies_are_never_spoken_on_a_hindi_clinic(self):
        self.assertEqual(agent(("en", "hi")).speakable("வணக்கம்! உங்கள் பெயர் என்ன?"), UNSUPPORTED_LINE)
        self.assertEqual(agent(("en",)).speakable("வணக்கம்! உங்கள் பெயர் என்ன?"), "வணக்கம்! உங்கள் பெயர் என்ன?")


if __name__ == "__main__":
    unittest.main()
