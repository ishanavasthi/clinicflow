"""Generate a trace-bound, bounded policy proposal and apply it immutably."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from collections import Counter
from pathlib import Path
from string import Formatter

from .budget import Budget, anthropic_cost
from .contracts import content_hash, validate_run, validate_scorecard

GENERATOR_MODEL = "claude-opus-5-5"
GENERATOR_EFFORT = "high"
MAX_SOURCE_RUNS = 4

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
        # A proposal may cite any event in a supplied failed trace, not only
        # the events a scorecard criterion happened to reference.
        sources = {item["run_id"]: set(item["evidence_ids"]) | {e["id"] for e in item.get("events", [])}
                   for item in findings}
        if not set(source_ids) <= sources.keys() or not set(evidence_ids) <= set().union(*(sources[s] for s in source_ids)):
            raise ValueError("proposal cites absent failure or evidence")
    if not isinstance(proposal.get("root_cause_hypothesis"), str) or not proposal["root_cause_hypothesis"].strip():
        raise ValueError("proposal needs root-cause hypothesis")
    generator = proposal.get("generator")
    if not isinstance(generator, dict) or generator.get("kind") not in ("anthropic_api", "openai_compatible_api", "manual"):
        raise ValueError("proposal needs explicit generator attribution")
    metadata = {"anthropic_api": ("model",), "openai_compatible_api": ("model", "endpoint"),
                "manual": ("author",)}[generator["kind"]]
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


GENERATOR_SYSTEM = """You improve a synthetic clinic scheduling voice agent from its own failed
evaluation runs. You may change only the agent's response-policy text: the
system prompt addendum and the tool-response templates listed in allowed_keys.
You cannot change code, tools, scenarios, the rubric, or the evaluator.

Ground truth about the system: route_to_department only records routing on a
staff dashboard; there is no call transfer, live handoff, or notification.
There is no callback system and no cancellation or rescheduling tool. A booking
exists only if book_appointment returned ok true.

Diagnose the root cause the failed traces share, then propose the smallest
policy text change that removes it. Prefer fixing the template that causes the
behaviour over adding general advice. Keep placeholders exactly as the
original field uses them. Change at most two fields. In `changes`, `before`
must be the field's current text verbatim and `after` the full replacement.
Cite only run IDs and evidence IDs that appear in the supplied failures. Name
regression risks honestly: behaviour that currently passes and might break."""

PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "proposal_id": {"type": "string"},
        "source_run_ids": {"type": "array", "items": {"type": "string"}},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "root_cause_hypothesis": {"type": "string"},
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": sorted(ALLOWED_KEYS)},
                    "before": {"type": "string"},
                    "after": {"type": "string"},
                },
                "required": ["field", "before", "after"],
                "additionalProperties": False,
            },
        },
        "expected_effects": {"type": "array", "items": {"type": "string"}},
        "regression_risks": {"type": "array", "items": {"type": "string"}},
        "validation_requirements": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["proposal_id", "source_run_ids", "evidence_ids", "root_cause_hypothesis", "changes",
                 "expected_effects", "regression_risks", "validation_requirements"],
    "additionalProperties": False,
}


def select_failures(findings: list[dict], limit: int = MAX_SOURCE_RUNS) -> list[dict]:
    """Severity first: target the critical failure code seen in the most
    trials; only when no trial has a critical failure, target the most common
    set of below-threshold criteria. Up to `limit` traces of the target are
    returned, preferring different scenarios so the fix is not tailored to one
    script."""
    critical = Counter(code for item in findings for code in set(item["critical_failures"]))
    if critical:
        target = max(critical, key=lambda code: (critical[code], code))
        matching = [item for item in findings if target in item["critical_failures"]]
    else:
        def signature(item: dict) -> str:
            return ",".join(sorted(c["id"] for c in item["criteria"]))
        counts = Counter(signature(item) for item in findings)
        target = max(counts, key=lambda key: (counts[key], key))
        matching = [item for item in findings if signature(item) == target]
    matching.sort(key=lambda i: (i["score"], i["run_id"]))
    chosen, scenarios = [], set()
    for item in matching:
        if item["scenario_id"] not in scenarios:
            chosen.append(item)
            scenarios.add(item["scenario_id"])
    for item in matching:
        if len(chosen) >= limit:
            break
        if item not in chosen:
            chosen.append(item)
    return chosen[:limit]


def _compact(item: dict) -> dict:
    from .judge import compact_events
    return {"run_id": item["run_id"], "scenario_id": item["scenario_id"], "score": item["score"],
            "critical_failures": item["critical_failures"], "evidence_ids": item["evidence_ids"],
            "failed_criteria": [{k: c.get(k) for k in ("id", "score", "reason", "evidence")} for c in item["criteria"]],
            "events": compact_events({"events": item["events"]}),
            "appointments": item["final_state"].get("appointments", [])}


def generate(summary: dict, policy: dict, *, model: str = GENERATOR_MODEL, budget: Budget | None = None,
             client=None) -> dict:
    import anthropic
    budget = budget or Budget(None)
    findings = failed_evidence(summary)
    validate_policy(policy)
    selected = select_failures(findings)
    payload = {"policy": policy, "allowed_keys": sorted(ALLOWED_KEYS),
               "failures": [_compact(item) for item in selected]}
    if len(json.dumps(payload)) > 200_000:
        raise ValueError("selected failure traces exceed generator budget")
    budget.check(0.5, role="generator")
    client = client or anthropic.Anthropic()
    message = client.messages.create(
        model=model, max_tokens=16000, system=GENERATOR_SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        output_config={"effort": GENERATOR_EFFORT, "format": {"type": "json_schema", "schema": PROPOSAL_SCHEMA}},
    )
    budget.add(anthropic_cost(model, message.usage.model_dump()), "generator")
    if message.stop_reason != "end_turn":
        raise ValueError(f"generator stopped with {message.stop_reason}")
    raw = json.loads(next(b.text for b in message.content if b.type == "text"))
    changes = {}
    for change in raw.pop("changes"):
        if change["field"] in changes:
            raise ValueError("generator changed one field twice")
        changes[change["field"]] = {"before": change["before"], "after": change["after"]}
    # Identity, base hash and schema version are written by this CLI, never
    # trusted from model output.
    proposal = {**raw, "changes": changes, "schema_version": 1, "base_policy_hash": content_hash(policy),
                "generator": {"kind": "anthropic_api", "model": model, "effort": GENERATOR_EFFORT}}
    validate_proposal(proposal, policy, selected)
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
    gen.add_argument("--model", default=GENERATOR_MODEL)
    gen.add_argument("--budget-usd", type=float, default=0.5)
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--proposal", required=True)
    apply_parser.add_argument("--policy", required=True)
    apply_parser.add_argument("--summary", required=True)
    apply_parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "generate":
        from dotenv import load_dotenv
        load_dotenv(Path.home() / ".secrets" / "anthropic.env", override=False)
        budget = Budget(args.budget_usd)
        proposal = generate(read_json(args.summary), read_json(args.policy), model=args.model, budget=budget)
        _write_new(args.output, proposal)
        print(json.dumps({"proposal": args.output, "proposal_id": proposal["proposal_id"],
                          "source_run_ids": proposal["source_run_ids"], "budget": budget.summary()}))
    else:
        provenance = apply(read_json(args.proposal), read_json(args.policy), args.output, evidence_summary=read_json(args.summary))
        print(json.dumps(provenance))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
