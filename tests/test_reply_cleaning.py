"""Speech cleaning: tool calls written as text never reach the caller."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from receptionist import LEAK_FALLBACK, _clean_reply, _unsupported_times  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
