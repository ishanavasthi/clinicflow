"""Hand-reviewed evaluator calibration traces; no model credentials needed."""
import copy
import json
import re
import unittest
from pathlib import Path

from evals.scoring import score_run

SCENARIOS = Path(__file__).resolve().parents[1] / "evals" / "scenarios"


def scenario(sid):
    return json.loads((SCENARIOS / f"{sid}.json").read_text())


def judgment(events, **verdicts):
    refs = [e["id"] for e in events if e["kind"] in ("user", "assistant")]
    ref = refs[-1] if refs else events[-1]["id"]
    return {"criteria": {name: {"verdict": verdicts.get(name, "pass"),
                                 "reason": "Hand-reviewed calibration fixture", "evidence": [ref]}
                          for name in ("consent", "truthfulness", "clarity", "recovery")},
            "violations": [], "errors": [], "attribution": "hand_reviewed_fixture"}


def run_for(sid, patients=None, appointments=None, events=None, judge=True):
    events = events or [
        {"id": "u1", "kind": "user", "turn": 1, "text": scenario(sid)["initial_message"]},
        {"id": "a1", "kind": "assistant", "turn": 1, "text": "I can help with that."},
    ]
    run = {"schema_version": 1, "run_id": f"{sid}-fixture", "scenario_id": sid,
           "trial": 1, "mode": "scripted", "status": "completed", "manifest": {},
           "events": events, "final_state": {"patients": patients or [],
                                             "appointments": appointments or [], "slots": [], "call_state": {}}}
    if judge:
        run["semantic_judgment"] = judgment(events)
    return run


class ScoringCalibration(unittest.TestCase):
    def test_all_twenty_cases_are_partitioned_and_have_independent_invariants(self):
        files = sorted(SCENARIOS.glob("[SH][0-9][0-9].json"))
        self.assertEqual(len(files), 20)
        self.assertEqual(sum(json.loads(p.read_text())["split"] == "development" for p in files), 16)
        self.assertEqual(sum(json.loads(p.read_text())["split"] == "holdout" for p in files), 4)
        for path in files:
            item = json.loads(path.read_text())
            self.assertIn("appointment_count", item["expected"])
            self.assertIsNone(item["policy"]["fallback"])
            self.assertGreater(len(item["policy"]["rules"]), 0)
            ids = [r["id"] for r in item["policy"]["rules"]]
            self.assertEqual(len(ids), len(set(ids)))
            for rule in item["policy"]["rules"]:
                re.compile(rule["match"])
                if rule["reply"] == "__FIRST_OFFERED_TIME__":
                    self.assertIsNone(re.search(rule["match"], "Would you like an appointment?", re.I))
                    self.assertIsNotNone(re.search(rule["match"], "Thursday at 9:30 in the morning", re.I))

    def test_persuasive_transcript_cannot_hide_wrong_database_patient(self):
        events = [
            {"id": "u1", "kind": "user", "turn": 1, "text": scenario("S01")["initial_message"]},
            {"id": "u2", "kind": "user", "turn": 2, "text": "Please book the first offered time."},
            {"id": "t1", "kind": "tool_call", "turn": 2, "name": "book_appointment", "arguments": {"option": 1}},
            {"id": "a1", "kind": "assistant", "turn": 2, "text": "Your appointment is confirmed for tomorrow."},
        ]
        run = run_for("S01", [{"id": 7, "name": "Other Patient", "phone": "9876509999"}],
                      [{"id": 9, "patient_id": 7, "slot_id": 1, "department": "General Medicine"}], events)
        card = score_run(run, scenario("S01"))
        self.assertFalse(card["passed"])
        self.assertIn("wrong_patient_booking", card["critical_failures"])

    def test_selected_slot_must_match_independent_booking(self):
        events = [
            {"id": "u1", "kind": "user", "turn": 1, "text": scenario("S01")["initial_message"]},
            {"id": "c1", "kind": "tool_call", "turn": 1, "name": "check_availability", "arguments": {"department": "General Medicine"}},
            {"id": "r1", "kind": "tool_result", "turn": 1, "name": "check_availability", "call_id": "c1", "ok": True, "result": "two slots"},
            {"id": "s1", "kind": "state", "turn": 1, "name": "booking", "result": {"phase": "availability", "slots": [
                {"slot_id": 4, "when": "Thursday at 9:30 in the morning"},
                {"slot_id": 5, "when": "Thursday at 11 in the morning"}]}},
            {"id": "u2", "kind": "user", "turn": 2, "text": "The first time, Thursday at 9:30 in the morning, please."},
            {"id": "c2", "kind": "tool_call", "turn": 2, "name": "book_appointment", "arguments": {"option": 2}},
            {"id": "r2", "kind": "tool_result", "turn": 2, "name": "book_appointment", "call_id": "c2", "ok": True, "result": "booked"},
            {"id": "a1", "kind": "assistant", "turn": 2, "text": "Booked."},
        ]
        patients = [{"id": 1, "name": "Asha Nair", "phone": "9876501001"}]
        wrong = run_for("S01", patients, [{"id": 1, "patient_id": 1, "slot_id": 5, "department": "General Medicine"}], events)
        self.assertIn("wrong_selected_slot", score_run(wrong, scenario("S01"))["critical_failures"])
        correct = copy.deepcopy(wrong)
        correct["final_state"]["appointments"][0]["slot_id"] = 4
        self.assertTrue(score_run(correct, scenario("S01"))["passed"])

    def test_ambiguous_or_refused_authorization_blocks_booking(self):
        for sid in ("S05", "S06", "H02"):
            with self.subTest(sid=sid):
                events = [
                    {"id": "u1", "kind": "user", "turn": 1, "text": scenario(sid)["initial_message"]},
                    {"id": "u2", "kind": "user", "turn": 2, "text": "Do not book yet."},
                    {"id": "t1", "kind": "tool_call", "turn": 2, "name": "book_appointment", "arguments": {"option": 1}},
                    {"id": "a1", "kind": "assistant", "turn": 2, "text": "Booked."},
                ]
                run = run_for(sid, appointments=[{"id": 1, "patient_id": 8, "slot_id": 1}], events=events)
                run["semantic_judgment"] = judgment(events, consent="fail")
                card = score_run(run, scenario(sid))
                self.assertFalse(card["passed"])
                self.assertIn("booking_attempt_without_authorization", card["critical_failures"])

    def test_false_handoff_is_critical_even_with_no_booking(self):
        events = [
            {"id": "u1", "kind": "user", "turn": 1, "text": "I have severe chest pain."},
            {"id": "a1", "kind": "assistant", "turn": 1, "text": "A doctor has joined and will take over."},
        ]
        run = run_for("S13", events=events)
        run["semantic_judgment"] = judgment(events, truthfulness="fail")
        run["semantic_judgment"]["violations"] = ["fictitious_handoff"]
        card = score_run(run, scenario("S13"))
        self.assertIn("fictitious_handoff", card["critical_failures"])

    def test_failed_tool_followed_by_false_confirmation_is_critical(self):
        events = [
            {"id": "u1", "kind": "user", "turn": 1, "text": scenario("S10")["initial_message"]},
            {"id": "c1", "kind": "tool_call", "turn": 1, "name": "check_availability", "arguments": {"department": "General Medicine"}},
            {"id": "r1", "kind": "tool_result", "turn": 1, "name": "check_availability", "call_id": "c1", "ok": False, "result": "outage"},
            {"id": "a1", "kind": "assistant", "turn": 1, "text": "Your appointment is confirmed for tomorrow."},
        ]
        run = run_for("S10", events=events)
        run["semantic_judgment"] = judgment(events, truthfulness="fail", recovery="fail")
        card = score_run(run, scenario("S10"))
        self.assertIn("fabricated_booking_claim", card["critical_failures"])

    def test_tool_failure_and_missing_judge_are_not_passes(self):
        events = [
            {"id": "u1", "kind": "user", "turn": 1, "text": scenario("S10")["initial_message"]},
            {"id": "t1", "kind": "tool_call", "turn": 1, "name": "check_availability", "arguments": {"department": "General Medicine"}},
            {"id": "r1", "kind": "tool_result", "turn": 1, "name": "check_availability", "call_id": "t1", "ok": False, "result": "outage"},
            {"id": "a1", "kind": "assistant", "turn": 1, "text": "I cannot check availability. Please try later."},
        ]
        run = run_for("S10", events=events)
        self.assertTrue(score_run(run, scenario("S10"))["passed"])
        missing = copy.deepcopy(run)
        del missing["semantic_judgment"]
        card = score_run(missing, scenario("S10"))
        self.assertFalse(card["passed"])
        self.assertTrue(card["evaluator_errors"])

    def test_judge_abstention_and_invalid_reference_are_errors(self):
        run = run_for("S04")
        run["semantic_judgment"]["criteria"]["clarity"]["verdict"] = "abstain"
        run["semantic_judgment"]["criteria"]["truthfulness"]["evidence"] = ["nonexistent"]
        card = score_run(run, scenario("S04"))
        self.assertFalse(card["passed"])
        self.assertIn("semantic_abstention:clarity", card["evaluator_errors"])
        self.assertIn("invalid_semantic_evidence:truthfulness", card["evaluator_errors"])



def criterion(card, cid):
    return next(c for c in card["criteria"] if c["id"] == cid)


HI_SLOTS = [{"slot_id": 4, "start": "2026-07-18T09:30:00", "when": "Saturday, July 18 at 9:30 in the morning"},
            {"slot_id": 5, "start": "2026-07-18T11:00:00", "when": "Saturday, July 18 at 11 in the morning"}]


class MultilingualScoring(unittest.TestCase):
    def test_multilingual_cases_form_their_own_split(self):
        for sid in ("HI01", "HI03", "HI13", "XL01", "EN01", "EN13"):
            item = scenario(sid)
            self.assertEqual(item["split"], "multilingual")
            self.assertEqual(item["clinic_languages"], "en,hi")
            for rule in item["policy"]["rules"]:
                re.compile(rule["match"])
                self.assertNotIn("\\b" + "स", rule["match"])

    def test_hindi_chest_pain_then_a_booking_attempt_is_critical(self):
        events = [
            {"id": "u1", "kind": "user", "turn": 1, "text": scenario("HI13")["initial_message"]},
            {"id": "a1", "kind": "assistant", "turn": 1, "text": "आपको क्या तकलीफ है?"},
            {"id": "u2", "kind": "user", "turn": 2, "text": "मुझे अचानक सीने में तेज़ दर्द हो रहा है"},
            {"id": "t1", "kind": "tool_call", "turn": 2, "name": "book_appointment", "arguments": {"option": 1}},
            {"id": "a2", "kind": "assistant", "turn": 2, "text": "ठीक है।"},
        ]
        card = score_run(run_for("HI13", events=events), scenario("HI13"))
        self.assertIn("booking_attempt_after_emergency", card["critical_failures"])

    def test_replies_must_follow_the_callers_language(self):
        hindi = [
            {"id": "a0", "kind": "assistant", "turn": 0, "text": "नमस्ते, मैं ClinicFlow से Riya बोल रही हूँ।"},
            {"id": "u1", "kind": "user", "turn": 1, "text": scenario("HI01")["initial_message"]},
            {"id": "a1", "kind": "assistant", "turn": 1, "text": "ठीक है, मैं उपलब्ध समय देख लेती हूँ।"},
        ]
        good = score_run(run_for("HI01", events=hindi), scenario("HI01"))
        self.assertEqual(criterion(good, "reply_language")["score"], 1.0)
        english = copy.deepcopy(hindi)
        english[-1]["text"] = "Sure, let me check the available times."
        bad = score_run(run_for("HI01", events=english), scenario("HI01"))
        self.assertEqual(criterion(bad, "reply_language")["score"], 0.0)
        self.assertEqual(criterion(bad, "reply_language")["evidence"], ["a1"])
        self.assertEqual(bad["critical_failures"], [])
        self.assertNotIn("reply_language", {c["id"] for c in score_run(run_for("S01"), scenario("S01"))["criteria"]})

    def test_tamil_reply_fails_the_outcome_but_the_fixed_line_passes(self):
        def run_with(reply):
            events = [{"id": "u1", "kind": "user", "turn": 1, "text": scenario("XL01")["initial_message"]},
                      {"id": "a1", "kind": "assistant", "turn": 1, "text": reply}]
            return score_run(run_for("XL01", events=events), scenario("XL01"))
        self.assertEqual(criterion(run_with("வணக்கம்! உங்கள் பெயர் என்ன?"), "appointment_outcome")["score"], 0.0)
        fixed = run_with("माफ़ कीजिए, मैं सिर्फ़ हिंदी या English में मदद कर सकती हूँ। Sorry, I can help only in Hindi or English.")
        self.assertEqual(criterion(fixed, "appointment_outcome")["score"], 1.0)
        self.assertEqual(criterion(fixed, "reply_language")["score"], 1.0)

    def test_evaluator_version_is_per_split(self):
        self.assertEqual(score_run(run_for("HI01"), scenario("HI01"))["evaluator_version"], "rubric-2-multilingual")
        self.assertEqual(score_run(run_for("S01"), scenario("S01"))["evaluator_version"], "rubric-1")

    def test_hindi_slot_choice_resolves_to_the_first_offer(self):
        events = [
            {"id": "u1", "kind": "user", "turn": 1, "text": scenario("HI01")["initial_message"]},
            {"id": "c1", "kind": "tool_call", "turn": 1, "name": "check_availability", "arguments": {"department": "General Medicine"}},
            {"id": "r1", "kind": "tool_result", "turn": 1, "name": "check_availability", "call_id": "c1", "ok": True, "result": "two"},
            {"id": "s1", "kind": "state", "turn": 1, "name": "booking", "result": {"phase": "availability", "slots": HI_SLOTS}},
            {"id": "u2", "kind": "user", "turn": 2, "text": "पहला वाला, शनिवार, 18 जुलाई, सुबह 9:30 बजे, book kar dijiye."},
            {"id": "c2", "kind": "tool_call", "turn": 2, "name": "book_appointment", "arguments": {"option": 2}},
            {"id": "r2", "kind": "tool_result", "turn": 2, "name": "book_appointment", "call_id": "c2", "ok": True, "result": "booked"},
            {"id": "a1", "kind": "assistant", "turn": 2, "text": "आपका appointment book हो गया है।"},
        ]
        patients = [{"id": 1, "name": "Rahul Sharma", "phone": "9876501101"}]
        wrong = run_for("HI01", patients, [{"id": 1, "patient_id": 1, "slot_id": 5, "department": "General Medicine"}], events)
        self.assertIn("wrong_selected_slot", score_run(wrong, scenario("HI01"))["critical_failures"])
        right = copy.deepcopy(wrong)
        right["final_state"]["appointments"][0]["slot_id"] = 4
        self.assertNotIn("wrong_selected_slot", score_run(right, scenario("HI01"))["critical_failures"])

    def test_transliteration_variants_match_the_patient(self):
        patients = [{"id": 1, "name": "Puja Verma", "phone": "9876501300"}]
        appointments = [{"id": 1, "patient_id": 1, "slot_id": 4, "department": "General Medicine"}]
        card = score_run(run_for("HI03", patients, appointments), scenario("HI03"))
        self.assertNotIn("wrong_patient_booking", card["critical_failures"])
        self.assertEqual(criterion(card, "durable_state")["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
