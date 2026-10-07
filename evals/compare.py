"""Reject incomparable or incomplete evaluations before reporting score gains."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .contracts import CATEGORIES, validate_run, validate_scorecard

IDENTITY_FIELDS = ("agent_provider", "agent_model", "agent_settings", "judge", "suite_hash", "evaluator_version", "dependencies", "fixed_clock")
VERSION_FIELDS = ("code_revision", "source_hash", "prompt_hash", "policy_hash")


def _index(summary: dict, expected_ids: set[str], min_trials: int) -> tuple[dict, dict]:
    if summary.get("schema_version") != 1:
        raise ValueError("unsupported summary schema")
    runs, cards = summary.get("runs"), summary.get("scorecards")
    if not isinstance(runs, list) or not isinstance(cards, list):
        raise ValueError("summary requires full runs and scorecards lists")
    indexed: dict[tuple[str, int], tuple[dict, dict]] = {}
    by_id = {}
    for run in runs:
        validate_run(run)
        if not run["events"] or not isinstance(run["final_state"], dict):
            raise ValueError("run lacks trace or independent final state")
        if not isinstance(run["trial"], int) or isinstance(run["trial"], bool) or run["trial"] < 0:
            raise ValueError("trial must be a nonnegative integer")
        if run["mode"] != "live" or run["status"] != "completed":
            raise ValueError(f"run {run['run_id']} is not a completed live run")
        if run["run_id"] in by_id:
            raise ValueError("duplicate run ID")
        if run["scenario_id"] not in expected_ids:
            raise ValueError(f"unexpected scenario {run['scenario_id']}")
        key = (run["scenario_id"], run["trial"])
        if key in indexed:
            raise ValueError(f"duplicate scenario/trial {key}")
        manifest = run["manifest"]
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be an object")
        if manifest.get("mode") != run["mode"]:
            raise ValueError("run mode differs from manifest")
        for field in (*IDENTITY_FIELDS, *VERSION_FIELDS, "fixture_hash"):
            if field not in manifest or manifest[field] in (None, "", {}):
                raise ValueError(f"run {run['run_id']} missing manifest {field}")
        if not isinstance(manifest["agent_settings"], dict) or not isinstance(manifest["dependencies"], dict):
            raise ValueError("agent settings and dependencies must be objects")
        judge = manifest["judge"]
        if (not isinstance(judge, dict) or set(judge) != {"provider", "model", "settings", "prompt_hash"}
                or any(not isinstance(judge[key], str) or not judge[key] for key in ("provider", "model", "prompt_hash"))
                or not isinstance(judge["settings"], dict) or not judge["settings"]):
            raise ValueError("live manifest needs complete judge identity")
        by_id[run["run_id"]] = (key, run)
        indexed[key] = (run, None)
    if not indexed:
        raise ValueError("no runs")
    seen_cards = set()
    for card in cards:
        validate_scorecard(card)
        run_id = card["run_id"]
        if run_id not in by_id or run_id in seen_cards:
            raise ValueError("orphan or duplicate scorecard")
        seen_cards.add(run_id)
        key, run = by_id[run_id]
        if card["scenario_id"] != run["scenario_id"]:
            raise ValueError("scorecard scenario mismatch")
        if card["evaluator_errors"]:
            raise ValueError(f"evaluator errors in {run_id}")
        if card["critical_failures"] and card["passed"]:
            raise ValueError("critical failure marked passed")
        if not isinstance(card["criteria"], list) or not card["criteria"]:
            raise ValueError("empty criteria")
        criterion_ids = set()
        event_ids = {event["id"] for event in run["events"]}
        for criterion in card["criteria"]:
            if not isinstance(criterion, dict) or criterion.get("id") in criterion_ids:
                raise ValueError("invalid or duplicate criterion")
            criterion_ids.add(criterion.get("id"))
            if criterion.get("category") not in CATEGORIES or criterion.get("score") is not None and (not isinstance(criterion["score"], (int, float)) or not 0 <= criterion["score"] <= 1):
                raise ValueError("invalid criterion category or score")
            references = criterion.get("evidence")
            if not isinstance(references, list) or (criterion.get("score") is not None and not references):
                raise ValueError("criterion lacks evidence references")
            for reference in references:
                if not isinstance(reference, str):
                    raise ValueError("invalid evidence reference")
                if reference in event_ids:
                    continue
                if not reference.startswith("final_state."):
                    raise ValueError(f"unknown evidence reference {reference}")
                state = run["final_state"]
                for component in reference.removeprefix("final_state.").split("."):
                    if not isinstance(state, dict) or component not in state:
                        raise ValueError(f"unknown evidence reference {reference}")
                    state = state[component]
        should_pass = not card["critical_failures"] and not card["evaluator_errors"] and all(
            criterion["score"] is None or criterion["score"] == 1 for criterion in card["criteria"])
        if card["passed"] is not should_pass:
            raise ValueError("scorecard pass flag disagrees with criteria")
        categories = _category_means([card])
        denominator = sum(CATEGORIES[category] for category in categories)
        computed = round(100 * sum(CATEGORIES[category] * value for category, value in categories.items()) / denominator, 2) if denominator else 0.0
        if abs(card["score"] - computed) > 0.01:
            raise ValueError("scorecard score disagrees with criteria")
        if card.get("evaluator_version") != manifest["evaluator_version"]:
            raise ValueError("scorecard evaluator version differs from run manifest")
        indexed[key] = (run, card)
    if len(seen_cards) != len(indexed):
        raise ValueError("run without scorecard")
    coverage = defaultdict(set)
    for scenario_id, trial in indexed:
        coverage[scenario_id].add(trial)
    if set(coverage) != expected_ids:
        raise ValueError(f"incomplete scenario coverage: missing {sorted(expected_ids - set(coverage))}")
    trial_sets = set(map(frozenset, coverage.values()))
    if len(trial_sets) != 1 or len(next(iter(trial_sets))) < min_trials:
        raise ValueError(f"uneven coverage or fewer than {min_trials} trials per scenario")
    trial_set = next(iter(trial_sets))
    if trial_set not in (frozenset(range(len(trial_set))), frozenset(range(1, len(trial_set) + 1))):
        raise ValueError("trial indices must be contiguous")
    first = next(iter(indexed.values()))[0]["manifest"]
    for run, _ in indexed.values():
        manifest = run["manifest"]
        for field in (*IDENTITY_FIELDS, *VERSION_FIELDS):
            if manifest[field] != first[field]:
                raise ValueError(f"inconsistent {field} within summary")
    return indexed, first


def _state_failures(card: dict) -> set[str]:
    return {criterion["id"] for criterion in card["criteria"]
            if criterion["category"] == "state" and criterion["score"] == 0}


def _category_means(cards: list[dict]) -> dict[str, float]:
    result = {}
    for category in CATEGORIES:
        values = []
        for card in cards:
            applicable = [criterion["score"] for criterion in card["criteria"]
                          if criterion["category"] == category and criterion["score"] is not None]
            if applicable:
                values.append(sum(applicable) / len(applicable))
        if values:
            result[category] = sum(values) / len(values)
    return result


def compare(baseline: dict, candidate: dict, expected_scenarios: set[str], *, min_trials: int = 3, final: bool = False) -> dict:
    if not expected_scenarios or min_trials < 3:
        raise ValueError("explicit expected scenarios and at least three trials required")
    b, bm = _index(baseline, expected_scenarios, min_trials)
    c, cm = _index(candidate, expected_scenarios, min_trials)
    if set(b) != set(c):
        raise ValueError("baseline/candidate scenario and trial coverage differs")
    for field in IDENTITY_FIELDS:
        if bm[field] != cm[field]:
            raise ValueError(f"incomparable manifest {field}")
    for key in b:
        br, _ = b[key]
        cr, _ = c[key]
        if br["manifest"]["fixture_hash"] != cr["manifest"]["fixture_hash"]:
            raise ValueError(f"fixture hash changed for {key}")
    report = {"schema_version": 1, "status": "rejected", "gate_passed": False,
              "baseline_policy_hash": bm["policy_hash"], "candidate_policy_hash": cm["policy_hash"],
              "suite_hash": bm["suite_hash"], "min_trials": min_trials, "final_gate": final,
              "scenarios": {}, "reasons": []}
    all_b, all_c = [], []
    fixed = []
    for scenario in sorted(expected_scenarios):
        keys = sorted((key for key in b if key[0] == scenario), key=lambda key: key[1])
        bc = [b[key][1] for key in keys]
        cc = [c[key][1] for key in keys]
        all_b.extend(bc)
        all_c.extend(cc)
        b_pass, c_pass = sum(bool(x["passed"]) for x in bc), sum(bool(x["passed"]) for x in cc)
        b_score = sum(x["score"] for x in bc) / len(bc)
        c_score = sum(x["score"] for x in cc) / len(cc)
        b_critical = sum(len(x["critical_failures"]) for x in bc)
        c_critical = sum(len(x["critical_failures"]) for x in cc)
        b_critical_ids = set().union(*(set(x["critical_failures"]) for x in bc))
        c_critical_ids = set().union(*(set(x["critical_failures"]) for x in cc))
        b_state = set().union(*(_state_failures(x) for x in bc))
        c_state = set().union(*(_state_failures(x) for x in cc))
        if b_pass < len(bc) and c_pass == len(cc) and c_pass > b_pass:
            fixed.append(scenario)
        if c_pass < b_pass:
            report["reasons"].append(f"{scenario}: pass rate regressed")
        if c_score + 1e-9 < b_score:
            report["reasons"].append(f"{scenario}: mean score regressed")
        if c_critical > b_critical:
            report["reasons"].append(f"{scenario}: critical failure rate increased")
        if c_critical_ids - b_critical_ids:
            report["reasons"].append(f"{scenario}: new critical failures {sorted(c_critical_ids - b_critical_ids)}")
        if c_state - b_state:
            report["reasons"].append(f"{scenario}: new state failures {sorted(c_state - b_state)}")
        report["scenarios"][scenario] = {"trials": [key[1] for key in keys], "baseline_mean": b_score,
              "candidate_mean": c_score, "baseline_passed": b_pass, "candidate_passed": c_pass,
              "baseline_critical": b_critical, "candidate_critical": c_critical,
              "baseline_categories": _category_means(bc), "candidate_categories": _category_means(cc),
              "baseline_run_ids": [b[key][0]["run_id"] for key in keys],
              "candidate_run_ids": [c[key][0]["run_id"] for key in keys]}
    b_mean = sum(x["score"] for x in all_b) / len(all_b)
    c_mean = sum(x["score"] for x in all_c) / len(all_c)
    report.update({"baseline_mean": b_mean, "candidate_mean": c_mean, "fixed_scenarios": fixed,
                   "baseline_categories": _category_means(all_b), "candidate_categories": _category_means(all_c),
                   "baseline_critical": sum(len(x["critical_failures"]) for x in all_b),
                   "candidate_critical": sum(len(x["critical_failures"]) for x in all_c)})
    if c_mean <= b_mean + 1e-9:
        report["reasons"].append("aggregate mean score did not strictly improve")
    if not fixed:
        report["reasons"].append("no failed baseline scenario passed every candidate trial")
    if final and report["candidate_critical"]:
        report["reasons"].append("final candidate has critical failures")
    if bm["policy_hash"] == cm["policy_hash"] and bm["source_hash"] == cm["source_hash"] and bm["prompt_hash"] == cm["prompt_hash"]:
        report["reasons"].append("candidate has no recorded behavior change")
    report["gate_passed"] = not report["reasons"]
    report["status"] = "accepted" if report["gate_passed"] else "rejected"
    return report


def suite_ids(directory: str | Path, split: str) -> set[str]:
    ids = set()
    for path in Path(directory).glob("*.json"):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        if scenario.get("split") == split:
            if scenario["id"] in ids:
                raise ValueError(f"duplicate scenario ID {scenario['id']}")
            ids.add(scenario["id"])
    if not ids:
        raise ValueError(f"no {split} scenarios found in {directory}")
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--scenarios-dir", default="evals/scenarios")
    parser.add_argument("--split", default="development", choices=("development", "holdout"))
    parser.add_argument("--min-trials", type=int, default=3)
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    try:
        expected = suite_ids(args.scenarios_dir, args.split)
        report = compare(json.loads(Path(args.baseline).read_text()), json.loads(Path(args.candidate).read_text()), expected, min_trials=args.min_trials, final=args.final)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        report = {"schema_version": 1, "status": "blocked", "gate_passed": False, "reasons": [str(error)]}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
