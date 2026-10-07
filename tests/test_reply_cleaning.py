"""Speech cleaning: tool calls written as text never reach the caller."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from receptionist import LEAK_FALLBACK, _clean_reply  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
