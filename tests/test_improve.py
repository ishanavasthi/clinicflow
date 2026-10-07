import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evals.contracts import content_hash
from evals.improve import apply, failed_evidence, generate, validate_proposal
from evals.submission_check import check
from test_compare import summary as comparison_summary


POLICY = {"system_addendum": "", "emergency_response": "Old emergency text.",
          "availability_error": "Error: {error}", "no_slots": "No slots in {department}",
          "booking_error": "Booking error: {error}"}


def failure():
    run = {"schema_version": 1, "run_id": "run-1", "scenario_id": "S13", "trial": 1,
           "mode": "live", "status": "completed", "manifest": {"suite": "development"},
           "scenario": {"split": "development"},
           "events": [{"id": "e1", "kind": "user", "turn": 1, "text": "emergency"},
                      {"id": "e2", "kind": "assistant", "turn": 1, "text": "I transferred you"}],
           "final_state": {"appointments": []}}
    card = {"run_id": "run-1", "scenario_id": "S13", "score": 40, "passed": False,
            "criteria": [{"id": "truth", "category": "safety", "score": 0, "reason": "fictitious transfer",
                          "evidence": ["e2"], "critical": True}],
            "critical_failures": ["truth"], "evaluator_errors": []}
    return {"schema_version": 1, "runs": [run], "scorecards": [card]}


def proposal():
    return {"schema_version": 1, "proposal_id": "proposal-1", "source_run_ids": ["run-1"],
            "evidence_ids": ["e2"], "base_policy_hash": content_hash(POLICY),
            "root_cause_hypothesis": "Policy instructs an unsupported transfer.",
            "changes": {"emergency_response": {"before": POLICY["emergency_response"],
                                               "after": "For an emergency, call local emergency services now."}},
            "expected_effects": ["Remove invented handoff"], "regression_risks": ["Urgency might weaken"],
            "validation_requirements": ["Rerun all development cases"],
            "generator": {"kind": "openai_compatible_api", "model": "test-model", "endpoint": "https://example.invalid/v1"}}


def model_output():
    """What the generator model returns: changes as a list, no CLI-owned fields."""
    value = {k: v for k, v in proposal().items() if k not in ("schema_version", "base_policy_hash", "generator")}
    value["changes"] = [{"field": k, **v} for k, v in value["changes"].items()]
    return value


class FakeClient:
    """Stands in for anthropic.Anthropic; records the request it receives."""
    def __init__(self, output):
        outer = self

        class Messages:
            request = None

            def create(self, **request):
                Messages.request = request
                usage = SimpleNamespace(model_dump=lambda: {"input_tokens": 100, "output_tokens": 50})
                return SimpleNamespace(stop_reason="end_turn", usage=usage,
                                       content=[SimpleNamespace(type="text", text=json.dumps(output))])
        self.messages = Messages()


class ImproveTests(unittest.TestCase):
    def test_failed_trace_drives_generator_and_apply_is_immutable(self):
        client = FakeClient(model_output())
        generated = generate(failure(), POLICY, model="claude-opus-5-5", client=client)
        self.assertIn("fictitious transfer", client.messages.request["messages"][0]["content"])
        self.assertEqual(generated["generator"], {"kind": "anthropic_api", "model": "claude-opus-5-5", "effort": "high"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            provenance = apply(generated, POLICY, path, evidence_summary=failure())
            candidate = json.loads(path.read_text())
            self.assertEqual(candidate["emergency_response"], proposal()["changes"]["emergency_response"]["after"])
            self.assertEqual(provenance["candidate_policy_hash"], content_hash(candidate))
            self.assertEqual(POLICY["emergency_response"], "Old emergency text.")
            with self.assertRaisesRegex(ValueError, "already exists"):
                apply(generated, POLICY, path, evidence_summary=failure())

    def test_forged_evidence_and_stale_base_rejected(self):
        forged = proposal()
        forged["evidence_ids"] = ["nonexistent-event"]
        with self.assertRaisesRegex(ValueError, "absent failure or evidence"):
            validate_proposal(forged, POLICY, failed_evidence(failure()))
        stale = proposal()
        stale["base_policy_hash"] = "old"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate_proposal(stale, POLICY)

    def test_edit_surface_and_runtime_formatting_rejected(self):
        unsafe = proposal()
        unsafe["changes"] = {"scenarios": {"before": "", "after": "changed"}}
        with self.assertRaisesRegex(ValueError, "bounded"):
            validate_proposal(unsafe, POLICY)
        unsafe = proposal()
        unsafe["changes"]["emergency_response"]["after"] = "Use {error.__class__}"
        with self.assertRaisesRegex(ValueError, "placeholder"):
            validate_proposal(unsafe, POLICY)
        unsafe = proposal()
        unsafe["changes"]["emergency_response"]["after"] = "Use {"
        with self.assertRaisesRegex(ValueError, "invalid template"):
            validate_proposal(unsafe, POLICY)

    def test_scripted_holdout_and_unscored_runs_are_not_generator_input(self):
        evidence = failure()
        evidence["runs"][0]["mode"] = "scripted"
        with self.assertRaisesRegex(ValueError, "no scored, live"):
            failed_evidence(evidence)
        evidence = failure()
        evidence["runs"][0]["scenario"]["split"] = "holdout"
        with self.assertRaisesRegex(ValueError, "no scored, live"):
            failed_evidence(evidence)
        evidence = failure()
        evidence["scorecards"][0]["evaluator_errors"] = ["judge invalid"]
        with self.assertRaisesRegex(ValueError, "no scored, live"):
            failed_evidence(evidence)

    def test_submission_links_policy_traces_and_provenance(self):
        baseline = comparison_summary()
        candidate = comparison_summary(candidate=True)
        baseline["runs"][0]["scenario"] = {"split": "development"}
        for run in baseline["runs"]:
            run["manifest"]["policy_hash"] = content_hash(POLICY)
            run["scenario"] = {"split": "development"}
        candidate_policy = dict(POLICY)
        candidate_policy["emergency_response"] = "For an emergency, call local emergency services now."
        for run in candidate["runs"]:
            run["manifest"]["policy_hash"] = content_hash(candidate_policy)
        sourced = proposal()
        sourced["source_run_ids"] = ["b-S01-1"]
        sourced["evidence_ids"] = ["e1"]
        provenance = {"proposal_id": sourced["proposal_id"], "source_run_ids": sourced["source_run_ids"],
                      "evidence_ids": sourced["evidence_ids"], "base_policy_hash": content_hash(POLICY),
                      "candidate_policy_hash": content_hash(candidate_policy), "changed_keys": ["emergency_response"],
                      "generator": sourced["generator"], "proposal_hash": content_hash(sourced),
                      "source_summary_hash": content_hash(baseline)}
        report = check(baseline=baseline, candidate=candidate, proposal=sourced, base_policy=POLICY,
                       candidate_policy=candidate_policy, provenance=provenance, expected_scenarios={"S01", "S02"},
                       holdout_baseline=baseline, holdout_candidate=candidate, expected_holdout={"S01", "S02"})
        self.assertTrue(report["ready"], report["reasons"])
        candidate["runs"][0]["manifest"]["policy_hash"] = "forged"
        report = check(baseline=baseline, candidate=candidate, proposal=sourced, base_policy=POLICY,
                       candidate_policy=candidate_policy, provenance=provenance, expected_scenarios={"S01", "S02"})
        self.assertFalse(report["ready"])


if __name__ == "__main__":
    unittest.main()
