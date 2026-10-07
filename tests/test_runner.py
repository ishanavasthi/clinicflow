"""Offline checks of the evaluator seam; scripted runs are not model evidence."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from evals.runner import run_scenario


def _scenario(*, fault=None, script=None):
    return {
        "id": "T01",
        "split": "development",
        "initial_message": "I need a doctor. I am Ada, 34, 9876543210, with a headache.",
        "policy": {"rules": []},
        "fault": fault,
        "script": script or [
            {"name": "update_intake", "arguments": {"field": "name", "value": "Ada"}},
            {"name": "update_intake", "arguments": {"field": "age", "value": "34"}},
            {"name": "update_intake", "arguments": {"field": "phone", "value": "9876543210"}},
            {"name": "update_intake", "arguments": {"field": "symptoms", "value": "headache"}},
            {"name": "check_availability", "arguments": {"department": "General Medicine"}},
            {"user": "The first one, please.", "name": "book_appointment", "arguments": {"option": 1}},
        ],
    }


class RunnerTests(unittest.TestCase):
    def test_real_wrappers_and_backend_book_once_with_isolated_state(self):
        with tempfile.TemporaryDirectory() as temp:
            first = asyncio.run(run_scenario(_scenario(), {}, mode="scripted", work_dir=Path(temp)))
            self.assertEqual(first["status"], "completed")
            self.assertEqual(len(first["final_state"]["appointments"]), 1)
            self.assertEqual(first["final_state"]["patients"][0]["phone"], "9876543210")
            self.assertEqual(first["final_state"]["appointments"][0]["department"], "General Medicine")
            self.assertTrue(any(e["kind"] == "state" and e.get("name") == "booking" for e in first["events"]))
            calls = [e for e in first["events"] if e["kind"] == "tool_call"]
            results = [e for e in first["events"] if e["kind"] == "tool_result"]
            self.assertEqual({e["id"] for e in calls}, {e["call_id"] for e in results})

            second = asyncio.run(run_scenario(_scenario(), {}, mode="scripted", trial=2, work_dir=Path(temp)))
            self.assertEqual(len(second["final_state"]["appointments"]), 1)
            self.assertEqual(second["final_state"]["appointments"][0]["id"], 1)

    def test_fault_records_failed_attempt_without_durable_booking(self):
        run = asyncio.run(run_scenario(_scenario(fault={"operation": "book", "trigger": 1, "effect": "raise", "times": 1}), {}, mode="scripted"))
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["final_state"]["appointments"], [])
        failed = [e for e in run["events"] if e["kind"] == "tool_result" and e["name"] == "book_appointment"]
        self.assertEqual(len(failed), 1)
        self.assertFalse(failed[0]["ok"])
        # Nothing committed and the receipt lookup finds nothing, so the agent is
        # told the outcome is unknown rather than that it failed.
        self.assertIn("Booking status is unknown", failed[0]["result"])

    def test_lost_response_is_reconciled_from_the_request_receipt(self):
        run = asyncio.run(run_scenario(_scenario(fault={"operation": "book", "trigger": 1, "effect": "commit_then_raise", "times": 1}), {}, mode="scripted"))
        self.assertEqual(len(run["final_state"]["appointments"]), 1)
        result = next(e for e in run["events"] if e["kind"] == "tool_result" and e["name"] == "book_appointment")
        self.assertTrue(result["ok"])
        self.assertIn("Booked:", result["result"])

    def test_booking_without_a_patient_choice_is_refused(self):
        script = _scenario()["script"]
        script[-1] = {"name": "book_appointment", "arguments": {"option": 1}}
        run = asyncio.run(run_scenario(_scenario(script=script), {}, mode="scripted"))
        self.assertEqual(run["final_state"]["appointments"], [])
        result = next(e for e in run["events"] if e["kind"] == "tool_result" and e["name"] == "book_appointment")
        self.assertFalse(result["ok"])

    def test_missing_model_credentials_are_blocked_not_scored_as_live(self):
        run = asyncio.run(run_scenario(_scenario(), {"model": "example", "api_key_env": "CLINICFLOW_NONEXISTENT_TEST_KEY"}, mode="live"))
        self.assertEqual(run["status"], "blocked")
        self.assertEqual(run["mode"], "live")
        self.assertEqual(run["final_state"]["appointments"], [])
        self.assertEqual(run["events"][0]["kind"], "error")


if __name__ == "__main__":
    unittest.main()
