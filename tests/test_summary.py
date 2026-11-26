"""Translations and the doctor summary for Hindi calls (no keys, no network)."""
import asyncio
import json
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from call_log import build_record, summary_of  # noqa: E402
from state import CallState  # noqa: E402
from summary import build_doctor_summary, summary_for_record, translate_exchange, verbatim_quote  # noqa: E402


def replying(payload):
    calls = []

    async def chat(messages):
        calls.append(messages)
        return payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)

    chat.calls = calls
    return chat


async def failing(messages):
    raise httpx.ReadTimeout("slow provider")


def run(coro):
    return asyncio.run(coro)


def hindi_state(**fields):
    state = CallState(languages=("en", "hi"), language="hi", **fields)
    state.intake = {"name": "Rahul Sharma", "age": "34", "phone": "9876501101", "symptoms": "persistent cough"}
    return state


TRANSCRIPT = [
    {"role": "assistant", "text": "नमस्ते, मैं ClinicFlow से Riya बोल रही हूँ।"},
    {"role": "user", "text": "मुझे  तीन दिन से खांसी है"},
    {"role": "assistant", "text": "कब से?"},
]


class TranslationTests(unittest.TestCase):
    def test_translates_one_exchange(self):
        chat = replying({"user": "I have a cough", "assistant": "Since when?"})
        self.assertEqual(run(translate_exchange("मुझे खांसी है", "कब से?", chat)),
                         {"user": "I have a cough", "assistant": "Since when?"})
        self.assertEqual(len(chat.calls), 1)

    def test_a_failed_translation_is_dropped(self):
        self.assertIsNone(run(translate_exchange("मुझे खांसी है", "कब से?", failing)))
        self.assertIsNone(run(translate_exchange("मुझे खांसी है", "कब से?", replying("not json"))))

    def test_english_exchanges_are_not_sent(self):
        chat = replying({"user": "x", "assistant": "y"})
        self.assertIsNone(run(translate_exchange("I have a cough", "Since when?", chat)))
        self.assertEqual(chat.calls, [])


class DoctorSummaryTests(unittest.TestCase):
    def test_quote_must_be_verbatim(self):
        lines = ["मुझे  तीन दिन से खांसी है"]
        self.assertEqual(verbatim_quote("तीन दिन से खांसी", lines), "तीन दिन से खांसी")
        self.assertIsNone(verbatim_quote("three days of cough", lines))
        self.assertIsNone(verbatim_quote("", lines))
        self.assertIsNone(verbatim_quote(None, lines))

    def test_quote_must_not_drop_a_negation_or_be_a_fragment(self):
        lines = ["सीने में दर्द नहीं है, बस खांसी है", "I don't have chest pain. Just a cough"]
        self.assertIsNone(verbatim_quote("सीने में दर्द", lines))
        self.assertIsNone(verbatim_quote("chest pain", lines))
        self.assertIsNone(verbatim_quote("है", lines))
        self.assertEqual(verbatim_quote("बस खांसी है", lines), "बस खांसी है")

    def test_structured_fields_come_from_state_not_the_model(self):
        chat = replying({"chief_complaint": "Cough", "duration": "3 days", "key_answers": ["No fever"],
                         "patient_words": "तीन दिन से खांसी", "name": "Someone Else"})
        summary = run(build_doctor_summary(TRANSCRIPT, hindi_state(), chat))
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["chief_complaint"], "Cough")
        self.assertEqual(summary["duration"], "3 days")
        self.assertEqual(summary["key_answers"], ["No fever"])
        self.assertEqual(summary["patient_words"], "तीन दिन से खांसी")
        self.assertEqual(summary["structured"]["name"], "Rahul Sharma")
        self.assertFalse(summary["structured"]["red_flag"])
        self.assertNotIn("name", {k for k in summary if k != "structured"})

    def test_invented_patient_words_are_dropped(self):
        chat = replying({"chief_complaint": "Cough", "patient_words": "मुझे बहुत दर्द है"})
        self.assertIsNone(run(build_doctor_summary(TRANSCRIPT, hindi_state(), chat))["patient_words"])

    def test_red_flag_comes_from_the_emergency_state(self):
        state = hindi_state(emergency=True, routed_department="Emergency")
        summary = run(build_doctor_summary(TRANSCRIPT, state, replying({"chief_complaint": "Chest pain"})))
        self.assertTrue(summary["structured"]["red_flag"])
        self.assertEqual(summary["structured"]["routed_department"], "Emergency")

    def test_a_slow_model_never_holds_up_the_call_record(self):
        async def slow(messages):
            await asyncio.sleep(5)
            return "{}"
        t0 = time.perf_counter()
        summary = run(summary_for_record(TRANSCRIPT, hindi_state(), slow, timeout=0.1))
        self.assertLess(time.perf_counter() - t0, 1.0)
        self.assertEqual(summary["status"], "unavailable")
        self.assertEqual(summary["structured"]["name"], "Rahul Sharma")

    def test_failure_keeps_the_structured_fields(self):
        summary = run(build_doctor_summary(TRANSCRIPT, hindi_state(), failing))
        self.assertEqual(summary["status"], "unavailable")
        self.assertEqual(summary["structured"]["phone"], "9876501101")


def chat_ctx(lines):
    return SimpleNamespace(items=[SimpleNamespace(role=line["role"], content=[line["text"]], metrics=None)
                                  for line in lines])


ENGLISH_KEYS = {"call_id", "room", "config", "started_at", "ended_at", "patient",
                "routed_department", "booking", "transcript", "latency"}


class CallRecordTests(unittest.TestCase):
    def record(self, state):
        now = datetime(2026, 11, 26, 10, 0)
        return build_record(state, chat_ctx(TRANSCRIPT), now, now)

    def test_english_records_are_unchanged(self):
        state = CallState()
        state.intake = {"name": "Asha Nair"}
        record = self.record(state)
        self.assertEqual(set(record), ENGLISH_KEYS)
        self.assertTrue(all(set(line) == {"role", "text"} for line in record["transcript"]))
        self.assertEqual(set(summary_of(record)),
                         {"name", "age", "phone", "symptom", "booking", "routed_department"})

    def test_hindi_records_carry_translations_and_the_summary(self):
        state = hindi_state()
        state.translations = [{"role": "user", "text": "मुझे  तीन दिन से खांसी है",
                               "text_en": "I have had a cough for three days"}]
        state.doctor_summary = {"status": "ok", "chief_complaint": "Cough"}
        record = self.record(state)
        self.assertEqual(record["language"], "hi")
        self.assertEqual(record["doctor_summary"]["chief_complaint"], "Cough")
        by_text = {line["text"]: line for line in record["transcript"]}
        self.assertEqual(by_text["मुझे  तीन दिन से खांसी है"]["text_en"], "I have had a cough for three days")
        self.assertNotIn("text_en", by_text["कब से?"])
        summary = summary_of(record)
        self.assertEqual(summary["language"], "hi")
        self.assertEqual(summary["doctor_summary"]["chief_complaint"], "Cough")


if __name__ == "__main__":
    unittest.main()
