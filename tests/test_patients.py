"""Scripted patient behaviour: answers facts, repeats choices, ends visibly."""
import json
import unittest
from pathlib import Path

from evals.patients import ScriptedPatient

SCENARIOS = Path(__file__).resolve().parents[1] / "evals" / "scenarios"
SLOTS = [{"slot_id": 7, "when": "Thursday, October 8 at 9:30 in the morning"}]


def patient(sid):
    return ScriptedPatient(json.loads((SCENARIOS / f"{sid}.json").read_text()))


class PatientTests(unittest.TestCase):
    def test_answers_reasked_facts_from_persona(self):
        p = patient("S02")
        self.assertEqual(p.reply("May I have your phone number, please?", []), "My phone number is 9876501002.")
        self.assertEqual(p.reply("Could you describe the knee pain you're experiencing?", []), "It is for knee pain.")

    def test_confirms_read_back_only_when_asked_to_confirm(self):
        p = patient("S01")
        self.assertEqual(p.reply("Just to confirm, your phone is 9876501001, correct?", []), "Yes, that's right.")

    def test_withheld_fact_is_left_to_scenario_rule(self):
        p = patient("S04")
        self.assertIn("prefer not to provide", p.reply("Could you share your phone number?", []))

    def test_repeats_slot_choice_when_agent_reoffers(self):
        p = patient("S01")
        offer = "We have Thursday at 9:30 AM, 11 AM or 2 PM. Which works?"
        first = p.reply(offer, SLOTS)
        self.assertIn("The first time", first)
        self.assertEqual(p.reply(offer, SLOTS), first)

    def test_cannot_choose_times_never_offered_by_a_tool(self):
        p = patient("S01")
        self.assertNotIn("The first time", p.reply("We have Thursday at 9:30 AM. Which works?", []) or "")

    def test_unmatched_turn_ends_call_and_is_recorded(self):
        p = patient("S06")
        self.assertIsNone(p.reply("Lovely weather today.", []))
        self.assertEqual(p.unmatched, "Lovely weather today.")


if __name__ == "__main__":
    unittest.main()
