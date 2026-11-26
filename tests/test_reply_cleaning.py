"""Speech cleaning: tool calls written as text never reach the caller."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from prompts import GREETING_TEXT, GREETING_TEXT_HI, SYSTEM_PROMPT, UNSUPPORTED_LINE, build_system_prompt  # noqa: E402
from receptionist import (  # noqa: E402
    LEAK_FALLBACK, Receptionist, _clean_reply, _explicit_choice, _spoken_digits, _unsupported_times,
)
from tools.intake import _normalize  # noqa: E402
from tools.routing import _canonical  # noqa: E402
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



class HindiSlotGuardTests(unittest.TestCase):
    def blocked(self, text, caller=""):
        return _unsupported_times(text, OFFERED, None, caller, hindi=True)

    def test_hindi_times_no_tool_returned_are_blocked(self):
        # Offered: 9:30, 11 and 2. Clinic hours (8, 10 and 7 o'clock) are allowed.
        for reply in ("सुबह 11:30 बजे खाली है।", "12:00 बजे आ जाइए।", "साढ़े दस बजे आ सकते हैं।",
                      "१०:३० बजे डॉक्टर मिलेंगे।", "Kal subah 9 baje aa jaiye.", "सवा दस बजे ठीक रहेगा?",
                      "पौने ग्यारह बजे?", "ढाई बजे का समय है।", "शाम 4 बजे", "चार बजे आइए।"):
            with self.subTest(reply=reply):
                self.assertTrue(self.blocked(reply))

    def test_offered_times_may_be_spoken_in_hindi(self):
        for reply in ("सुबह 9:30 बजे या 11 बजे, कौन सा ठीक रहेगा?", "साढ़े नौ बजे वाला?",
                      "दोपहर 2 बजे भी खाली है।", "Subah 11 baje ka slot hai."):
            with self.subTest(reply=reply):
                self.assertFalse(self.blocked(reply))

    def test_clinic_hours_in_hindi_are_not_offers(self):
        self.assertFalse(self.blocked("हम सुबह 8 बजे से रात 8 बजे तक खुले हैं।"))

    def test_hindi_mode_checks_times_without_an_english_offer_word(self):
        # No slot/available/appointment word: the English gate would let it through.
        self.assertFalse(_unsupported_times("सुबह 11:30 बजे आ जाइए।", OFFERED, None))
        self.assertTrue(_unsupported_times("सुबह 11:30 बजे आ जाइए।", OFFERED, None, hindi=True))

    def test_hindi_agent_replaces_the_reply_with_a_hindi_guard(self):
        a = agent(("en", "hi"))
        self.assertEqual(a.state.language, "hi")
        guarded = a.speakable("सुबह 11:30 बजे आ जाइए।")
        self.assertNotIn("11", guarded)
        self.assertIn("समय", guarded)


class HindiConsentTests(unittest.TestCase):
    def choice(self, text):
        return _explicit_choice(text, OFFERED, hindi=True)

    def test_clear_hindi_choices(self):
        self.assertEqual(self.choice("पहला वाला, book kar dijiye"), 1)
        self.assertEqual(self.choice("pehla wala please"), 1)
        self.assertEqual(self.choice("9:30 वाला"), 1)
        self.assertEqual(self.choice("Option 1"), 1)
        self.assertEqual(self.choice("दूसरा"), 2)
        self.assertEqual(self.choice("teesra wala"), 3)
        self.assertEqual(self.choice("पहला वाला, शनिवार, 18 जुलाई, सुबह 9:30 बजे, book kar dijiye."), 1)

    def test_hindi_refusals_and_hedges_never_book(self):
        for text in ("नहीं, पहला नहीं", "पहला नहीं।", "रुकिए।", "रुको, पहला", "शायद पहला", "पहला या दूसरा",
                     "nahi pehla mat karo", "ruko", "shayad doosra", "pehla ya doosra", "मत कीजिए पहला"):
            with self.subTest(text=text):
                self.assertIsNone(self.choice(text))

    def test_refusal_words_match_whole_tokens_only(self):
        # "लिया" contains "या" (or); only the whole token is a hedge.
        self.assertEqual(self.choice("मैंने पहला वाला चुन लिया"), 1)

    def test_english_consent_is_unchanged(self):
        self.assertEqual(_explicit_choice("The first one, please.", OFFERED), 1)
        self.assertIsNone(_explicit_choice("Not the first one.", OFFERED))
        self.assertIsNone(_explicit_choice("pehla", OFFERED))  # Hindi words only in Hindi mode


class HindiDigitsAndNamesTests(unittest.TestCase):
    def test_hindi_digit_words_and_numerals(self):
        self.assertEqual(_spoken_digits("नौ आठ सात छह पांच शून्य एक शून्य शून्य एक", hindi=True), "9876501001")
        self.assertEqual(_spoken_digits("nau aath saat chhah paanch shunya ek shunya shunya ek", hindi=True), "9876501001")
        self.assertEqual(_spoken_digits("९८७६५०१००१", hindi=True), "9876501001")
        self.assertEqual(_spoken_digits("do it", hindi=False), "")
        self.assertEqual(_spoken_digits("nine eight seven"), "987")

    def test_intake_normalizes_devanagari_digits(self):
        self.assertEqual(_normalize("phone", "९८७६५०१००१"), "9876501001")
        self.assertEqual(_normalize("age", "३४"), "34")
        self.assertEqual(_normalize("name", "Rahul Sharma"), "Rahul Sharma")

    def test_hindi_department_names_reach_the_canonical_department(self):
        self.assertEqual(_canonical("आपातकालीन"), "Emergency")
        self.assertEqual(_canonical("इमरजेंसी"), "Emergency")
        self.assertEqual(_canonical("Emergency"), "Emergency")
        self.assertEqual(_canonical("हृदय रोग"), "Cardiology")
        self.assertEqual(_canonical("सामान्य चिकित्सा"), "General Medicine")
        self.assertIsNone(_canonical("Dermatology"))


if __name__ == "__main__":
    unittest.main()
