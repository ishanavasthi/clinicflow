"""Verify that archived live evidence links failure, proposal and candidate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .compare import compare, suite_ids
from .contracts import content_hash
from .improve import failed_evidence, read_json, validate_policy, validate_proposal


def check(*, baseline: dict, candidate: dict, proposal: dict, base_policy: dict,
          candidate_policy: dict, provenance: dict, expected_scenarios: set[str],
          holdout_baseline: dict | None = None, holdout_candidate: dict | None = None,
          expected_holdout: set[str] | None = None) -> dict:
    reasons = []
    try:
        findings = failed_evidence(baseline)
        validate_proposal(proposal, base_policy, findings)
        validate_policy(candidate_policy)
        expected_policy = dict(base_policy)
        expected_policy.update({key: edit["after"] for key, edit in proposal["changes"].items()})
        if candidate_policy != expected_policy:
            reasons.append("candidate policy does not equal applied proposal")
        if proposal.get("generator", {}).get("kind") != "openai_compatible_api":
            reasons.append("proposal is not attributed to a live API generator")
        required = {"proposal_id": proposal["proposal_id"], "source_run_ids": proposal["source_run_ids"],
                    "evidence_ids": proposal["evidence_ids"], "base_policy_hash": content_hash(base_policy),
                    "candidate_policy_hash": content_hash(candidate_policy), "changed_keys": sorted(proposal["changes"]),
                    "generator": proposal["generator"], "proposal_hash": content_hash(proposal),
                    "source_summary_hash": content_hash(baseline)}
        for key, value in required.items():
            if provenance.get(key) != value:
                reasons.append(f"provenance {key} does not match proposal/policies")
        comparison = compare(baseline, candidate, expected_scenarios, final=True)
        if comparison["baseline_policy_hash"] != content_hash(base_policy):
            reasons.append("baseline runs do not use supplied base policy")
        if comparison["candidate_policy_hash"] != content_hash(candidate_policy):
            reasons.append("candidate runs do not use supplied candidate policy")
        reasons.extend(comparison["reasons"])
        if holdout_baseline is None or holdout_candidate is None or not expected_holdout:
            reasons.append("paired live held-out suite evidence is absent")
        else:
            # Held-out evaluation is reported separately; its regression rules
            # still apply, without requiring a new strict gain on this suite.
            holdout = compare(holdout_baseline, holdout_candidate, expected_holdout, final=True)
            reasons.extend(f"holdout: {reason}" for reason in holdout["reasons"] if
                           reason not in ("aggregate mean score did not strictly improve", "no failed baseline scenario passed every candidate trial"))
            if holdout["candidate_critical"]:
                reasons.append("holdout candidate has critical failures")
    except (ValueError, KeyError, TypeError) as error:
        reasons.append(str(error))
        comparison = None
    return {"schema_version": 1, "status": "ready" if not reasons else "blocked",
            "ready": not reasons, "reasons": reasons, "comparison": comparison}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("baseline", "candidate", "proposal", "base-policy", "candidate-policy", "provenance"):
        parser.add_argument(f"--{arg}", required=True)
    parser.add_argument("--holdout-baseline")
    parser.add_argument("--holdout-candidate")
    parser.add_argument("--scenarios-dir", default="evals/scenarios")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = check(baseline=read_json(args.baseline), candidate=read_json(args.candidate),
                       proposal=read_json(args.proposal), base_policy=read_json(args.base_policy),
                       candidate_policy=read_json(args.candidate_policy), provenance=read_json(args.provenance),
                       expected_scenarios=suite_ids(args.scenarios_dir, "development"),
                       holdout_baseline=read_json(args.holdout_baseline) if args.holdout_baseline else None,
                       holdout_candidate=read_json(args.holdout_candidate) if args.holdout_candidate else None,
                       expected_holdout=suite_ids(args.scenarios_dir, "holdout") if args.holdout_baseline or args.holdout_candidate else None)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        report = {"schema_version": 1, "status": "blocked", "ready": False, "reasons": [f"live artifact missing or invalid: {error}"]}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
