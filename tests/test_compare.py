import unittest

from evals.compare import compare


def summary(*, candidate=False):
    runs, cards = [], []
    for scenario in ("S01", "S02"):
        for trial in (1, 2, 3):
            run_id = f"{'c' if candidate else 'b'}-{scenario}-{trial}"
            manifest = {"agent_provider": "provider", "agent_model": "model", "agent_settings": {"temperature": 0},
                        "judge": {"provider": "provider", "model": "judge", "settings": {"temperature": 0}, "prompt_hash": "judge-prompt"},
                        "suite_hash": "suite", "evaluator_version": "v1", "dependencies": {"x": "1"},
                        "fixed_clock": "2026-10-07T09:00:00+05:30", "code_revision": "c1" if candidate else "c0",
                        "source_hash": "s1" if candidate else "s0", "prompt_hash": "p1" if candidate else "p0",
                        "policy_hash": "h1" if candidate else "h0", "fixture_hash": scenario, "mode": "live"}
            runs.append({"schema_version": 1, "run_id": run_id, "scenario_id": scenario, "trial": trial,
                         "mode": "live", "status": "completed", "manifest": manifest,
                         "events": [{"id": "e1", "kind": "user", "turn": 1, "text": "hello"}], "final_state": {"appointments": []}})
            passed = scenario == "S02" or candidate
            cards.append({"run_id": run_id, "scenario_id": scenario, "evaluator_version": "v1", "score": 100 if passed else 0,
                          "passed": passed, "criteria": [{"id": "outcome", "category": "outcome", "score": 1 if passed else 0,
                                                           "reason": "result", "evidence": ["e1"], "critical": False}],
                          "critical_failures": [], "evaluator_errors": []})
    return {"schema_version": 1, "runs": runs, "scorecards": cards}


class CompareTests(unittest.TestCase):
    def test_full_live_gain(self):
        report = compare(summary(), summary(candidate=True), {"S01", "S02"}, final=True)
        self.assertTrue(report["gate_passed"])
        self.assertEqual(report["fixed_scenarios"], ["S01"])

    def test_missing_scenario_and_trial_rejected(self):
        baseline = summary()
        with self.assertRaisesRegex(ValueError, "incomplete scenario"):
            compare(baseline, summary(candidate=True), {"S01", "S02", "S03"})
        baseline["runs"].pop()
        with self.assertRaisesRegex(ValueError, "orphan or duplicate scorecard"):
            compare(baseline, summary(candidate=True), {"S01", "S02"})

    def test_scripted_and_errors_cannot_pass(self):
        baseline = summary()
        baseline["runs"][0]["mode"] = "scripted"
        with self.assertRaisesRegex(ValueError, "completed live"):
            compare(baseline, summary(candidate=True), {"S01", "S02"})
        baseline = summary()
        baseline["scorecards"][0]["evaluator_errors"] = ["judge timeout"]
        with self.assertRaisesRegex(ValueError, "evaluator errors"):
            compare(baseline, summary(candidate=True), {"S01", "S02"})

    def test_duplicate_and_manifest_mismatch_rejected(self):
        baseline = summary()
        baseline["runs"][1]["trial"] = 1
        with self.assertRaisesRegex(ValueError, "duplicate scenario/trial"):
            compare(baseline, summary(candidate=True), {"S01", "S02"})
        candidate = summary(candidate=True)
        for run in candidate["runs"]:
            run["manifest"]["agent_model"] = "different"
        with self.assertRaisesRegex(ValueError, "agent_model"):
            compare(summary(), candidate, {"S01", "S02"})

    def test_forged_score_or_pass_flag_rejected(self):
        baseline = summary()
        baseline["scorecards"][0]["score"] = 100
        with self.assertRaisesRegex(ValueError, "scorecard score disagrees"):
            compare(baseline, summary(candidate=True), {"S01", "S02"})
        baseline = summary()
        baseline["scorecards"][0]["passed"] = True
        with self.assertRaisesRegex(ValueError, "pass flag disagrees"):
            compare(baseline, summary(candidate=True), {"S01", "S02"})

    def test_regression_and_critical_failure_rejected(self):
        candidate = summary(candidate=True)
        target = candidate["scorecards"][-1]
        target["passed"] = False
        target["score"] = 0
        target["critical_failures"] = ["unsafe"]
        target["criteria"][0]["score"] = 0
        report = compare(summary(), candidate, {"S01", "S02"}, final=True)
        self.assertFalse(report["gate_passed"])
        self.assertTrue(any("S02: pass rate" in reason for reason in report["reasons"]))
        self.assertTrue(any("final candidate" in reason for reason in report["reasons"]))

    def test_new_state_failure_rejected(self):
        candidate = summary(candidate=True)
        candidate["scorecards"][0]["criteria"].append({"id": "duplicate_booking", "category": "state", "score": 0,
                                                         "reason": "two rows", "evidence": ["final_state.appointments"], "critical": False})
        candidate["scorecards"][0]["score"] = 54.55
        candidate["scorecards"][0]["passed"] = False
        report = compare(summary(), candidate, {"S01", "S02"})
        self.assertTrue(any("new state failures" in reason for reason in report["reasons"]))


if __name__ == "__main__":
    unittest.main()
