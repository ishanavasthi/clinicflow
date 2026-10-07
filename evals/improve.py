"""Generate a trace-bound, bounded policy proposal and apply it immutably."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from string import Formatter

from .contracts import content_hash, validate_run, validate_scorecard

ALLOWED_KEYS = frozenset({"system_addendum", "emergency_response", "availability_error", "no_slots", "booking_error"})
MAX_CHANGED_KEYS = 2
MAX_NEW_CHARACTERS = 1200


def read_json(path: str | Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_new(path: str | Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to overwrite {path}")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # A hard link makes publication exclusive even if another writer raced us.
        os.link(temporary, path)
    finally:
        os.unlink(temporary)


def validate_policy(policy: dict) -> None:
    if set(policy) != ALLOWED_KEYS or any(not isinstance(value, str) for value in policy.values()):
        raise ValueError("policy must contain exactly the five allowed string fields")
    placeholders = {"system_addendum": set(), "emergency_response": set(),
                    "availability_error": {"error"}, "no_slots": {"department"},
                    "booking_error": {"error"}}
    for key, value in policy.items():
        try:
            fields = [(name, spec, conversion) for _, name, spec, conversion in Formatter().parse(value) if name is not None]
        except ValueError as error:
            raise ValueError(f"invalid template in {key}: {error}") from error
        if len(value) > 12000 or any(name not in placeholders[key] or spec or conversion for name, spec, conversion in fields):
            raise ValueError(f"unsupported policy text or placeholder in {key}")


def failed_evidence(summary: dict) -> list[dict]:
    if summary.get("schema_version") != 1:
        raise ValueError("unsupported summary schema")
    runs = summary.get("runs")
    cards = summary.get("scorecards")
    if not isinstance(runs, list) or not isinstance(cards, list):
        raise ValueError("summary requires full runs and scorecards lists")
    by_id = {}
    for run in runs:
        validate_run(run)
        if run["run_id"] in by_id:
            raise ValueError("duplicate run ID")
        by_id[run["run_id"]] = run
    findings = []
    seen = set()
    for card in cards:
        validate_scorecard(card)
        run_id = card["run_id"]
        if run_id in seen or run_id not in by_id:
            raise ValueError("duplicate or orphan scorecard")
        seen.add(run_id)
        run = by_id[run_id]
        if card["scenario_id"] != run["scenario_id"]:
            raise ValueError("scorecard scenario does not match run")
        if run["mode"] != "live" or run["status"] != "completed" or card["evaluator_errors"]:
            continue
        split = run.get("scenario", {}).get("split", run.get("manifest", {}).get("suite"))
        if split != "development" or card["passed"]:
            continue
        event_ids = {event["id"] for event in run["events"]}
        evidence = []
        for criterion in card["criteria"]:
            if criterion.get("score") is None or criterion.get("score") == 1:
                continue
            cited = criterion.get("evidence", [])
            if not isinstance(cited, list):
                continue
            for item in cited:
                if not isinstance(item, str):
                    continue
                path = item.removeprefix("final_state.").split(".") if item.startswith("final_state.") else []
                state = run["final_state"]
                for component in path:
                    if isinstance(state, dict) and component in state:
                        state = state[component]
                    else:
                        path = []
                        break
                if item in event_ids or path:
                    evidence.append(item)
        if not evidence:
            continue
        findings.append({"run_id": run_id, "scenario_id": run["scenario_id"],
                         "score": card["score"], "critical_failures": card["critical_failures"],
                         "evidence_ids": sorted(set(evidence)), "criteria": [c for c in card["criteria"] if c.get("score") is not None and c.get("score") < 1],
                         "events": run["events"], "final_state": run["final_state"]})
    if not findings:
        raise ValueError("no scored, live, completed development failure with trace evidence")
    return findings


def validate_proposal(proposal: dict, policy: dict, findings: list[dict] | None = None) -> None:
    validate_policy(policy)
    expected_fields = {"schema_version", "proposal_id", "source_run_ids", "evidence_ids", "base_policy_hash",
                       "root_cause_hypothesis", "changes", "expected_effects", "regression_risks",
                       "validation_requirements", "generator"}
    if not isinstance(proposal, dict) or set(proposal) != expected_fields:
        raise ValueError("proposal has missing or unsupported fields")
    if proposal.get("schema_version") != 1 or not isinstance(proposal.get("proposal_id"), str) or not proposal["proposal_id"]:
        raise ValueError("invalid proposal identity")
    if proposal.get("base_policy_hash") != content_hash(policy):
        raise ValueError("proposal base policy hash mismatch")
    source_ids = proposal.get("source_run_ids")
    evidence_ids = proposal.get("evidence_ids")
    if not isinstance(source_ids, list) or not source_ids or any(not isinstance(x, str) or not x for x in source_ids) or len(source_ids) != len(set(source_ids)):
        raise ValueError("proposal needs unique source run IDs")
    if not isinstance(evidence_ids, list) or not evidence_ids or any(not isinstance(x, str) or not x for x in evidence_ids) or len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("proposal needs unique evidence IDs")
    if findings is not None:
        sources = {item["run_id"]: set(item["evidence_ids"]) for item in findings}
        if not set(source_ids) <= sources.keys() or not set(evidence_ids) <= set().union(*(sources[s] for s in source_ids)):
            raise ValueError("proposal cites absent failure or evidence")
    if not isinstance(proposal.get("root_cause_hypothesis"), str) or not proposal["root_cause_hypothesis"].strip():
        raise ValueError("proposal needs root-cause hypothesis")
    generator = proposal.get("generator")
    if not isinstance(generator, dict) or generator.get("kind") not in ("openai_compatible_api", "manual"):
        raise ValueError("proposal needs explicit generator attribution")
    metadata = ("model", "endpoint") if generator["kind"] == "openai_compatible_api" else ("author",)
    if any(not isinstance(generator.get(key), str) or not generator[key].strip() for key in metadata):
        raise ValueError("generator attribution is incomplete")
    for key in ("expected_effects", "regression_risks", "validation_requirements"):
        if not isinstance(proposal.get(key), list) or not proposal[key] or any(not isinstance(x, str) or not x for x in proposal[key]):
            raise ValueError(f"proposal needs nonempty {key}")
    changes = proposal.get("changes")
    if not isinstance(changes, dict) or not 1 <= len(changes) <= MAX_CHANGED_KEYS or not set(changes) <= ALLOWED_KEYS:
        raise ValueError("proposal exceeds bounded policy edit surface")
    for key, edit in changes.items():
        if not isinstance(edit, dict) or set(edit) != {"before", "after"}:
            raise ValueError(f"change for {key} requires exact before/after")
        before, after = edit["before"], edit["after"]
        if not isinstance(before, str) or not isinstance(after, str) or before != policy[key] or before == after:
            raise ValueError(f"invalid or stale change for {key}")
        if len(after) - len(before) > MAX_NEW_CHARACTERS or len(after) > 6000:
            raise ValueError(f"change for {key} exceeds text limit")
    candidate = dict(policy)
    candidate.update({key: edit["after"] for key, edit in changes.items()})
    validate_policy(candidate)


def _chat_completion(url: str, model: str, api_key: str, messages: list[dict]) -> dict:
    request = urllib.request.Request(url.rstrip("/") + "/chat/completions",
        data=json.dumps({"model": model, "temperature": 0, "response_format": {"type": "json_object"}, "messages": messages}).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.load(response)
    return json.loads(payload["choices"][0]["message"]["content"])


def generate(summary: dict, policy: dict, *, api_url: str, model: str, api_key: str) -> dict:
    findings = failed_evidence(summary)
    validate_policy(policy)
    # Bound prompt size while retaining complete selected trace and its score evidence.
    selected = min(findings, key=lambda item: (item["score"], item["run_id"]))
    if len(json.dumps(selected)) > 100_000:
        raise ValueError("selected failure trace exceeds generator budget")
    system = ("You propose one small policy text change for a synthetic clinic scheduling agent. "
              "Return JSON only with schema_version=1, proposal_id, source_run_ids, evidence_ids, "
              "base_policy_hash, root_cause_hypothesis, changes as field:{before,after}, "
              "expected_effects, regression_risks, validation_requirements, generator. "
              "Change at most two allowed string fields. Preserve all unrelated content. "
              "Cite only the supplied failed run and its evidence IDs. Do not edit evaluation data.")
    payload = {"policy": policy, "base_policy_hash": content_hash(policy), "allowed_keys": sorted(ALLOWED_KEYS), "failed_run": selected}
    proposal = _chat_completion(api_url, model, api_key, [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload)}])
    if not isinstance(proposal, dict):
        raise ValueError("generator returned non-object")
    # Generator identity is written by this CLI, never trusted from model output.
    proposal["generator"] = {"kind": "openai_compatible_api", "model": model, "endpoint": api_url.rstrip("/")}
    validate_proposal(proposal, policy, [selected])
    return proposal


def apply(proposal: dict, policy: dict, output: str | Path, *, evidence_summary: dict | None = None) -> dict:
    findings = failed_evidence(evidence_summary) if evidence_summary is not None else None
    validate_proposal(proposal, policy, findings)
    candidate = dict(policy)
    for key, edit in proposal["changes"].items():
        candidate[key] = edit["after"]
    provenance = {"schema_version": 1, "proposal_id": proposal["proposal_id"],
                  "source_run_ids": proposal["source_run_ids"], "evidence_ids": proposal["evidence_ids"],
                  "proposal_hash": content_hash(proposal),
                  "base_policy_hash": content_hash(policy), "candidate_policy_hash": content_hash(candidate),
                  "changed_keys": sorted(proposal["changes"]), "generator": proposal["generator"]}
    if evidence_summary is not None:
        provenance["source_summary_hash"] = content_hash(evidence_summary)
    output = Path(output)
    if output.exists() or output.with_suffix(output.suffix + ".provenance.json").exists():
        raise ValueError("candidate or provenance output already exists")
    _write_new(output, candidate)
    _write_new(output.with_suffix(output.suffix + ".provenance.json"), provenance)
    return provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--summary", required=True)
    gen.add_argument("--policy", required=True)
    gen.add_argument("--output", required=True)
    gen.add_argument("--api-url", default=os.getenv("CLINICFLOW_IMPROVER_BASE_URL") or os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1")
    gen.add_argument("--model", default=os.getenv("CLINICFLOW_IMPROVER_MODEL"))
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--proposal", required=True)
    apply_parser.add_argument("--policy", required=True)
    apply_parser.add_argument("--summary", required=True)
    apply_parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "generate":
        api_key = os.getenv("CLINICFLOW_IMPROVER_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
        if not args.model or not api_key:
            parser.error("generation requires --model and CLINICFLOW_IMPROVER_API_KEY, OPENAI_API_KEY, or LLM_API_KEY")
        proposal = generate(read_json(args.summary), read_json(args.policy), api_url=args.api_url, model=args.model, api_key=api_key)
        _write_new(args.output, proposal)
        print(json.dumps({"proposal": args.output, "proposal_id": proposal["proposal_id"]}))
    else:
        provenance = apply(read_json(args.proposal), read_json(args.policy), args.output, evidence_summary=read_json(args.summary))
        print(json.dumps(provenance))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
