"""Aggregate voice latency across every archived call.

Reads the call records under runs/calls/ and prints p50/p95 per stage: how long
the caller waits before the agent starts talking, and which stage owns that wait.

Calls are grouped by the pipeline that produced them (cascaded on Groq, cascaded
on OpenAI, speech-to-speech), because a percentile pooled across two different
pipelines describes neither. That grouping is what makes this an A/B: run the
same call script under each config, then read the tables side by side.

Run:  agent/.venv/bin/python scripts/latency_report.py [--json] [--per-call]

Calls recorded before latency instrumentation existed carry no timings and are
reported as skipped rather than silently ignored.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import turn_latency

RUNS_CALLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "runs",
    "calls",
)


def load_calls(directory: str) -> tuple[list[dict], list[str]]:
    """Every readable call record, plus the paths that carry no timings."""
    calls: list[dict] = []
    skipped: list[str] = []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"skipping {os.path.basename(path)}: {exc}", file=sys.stderr)
            skipped.append(path)
            continue
        turns = (record.get("latency") or {}).get("turns") or []
        if not turns:
            skipped.append(path)
            continue
        calls.append({"path": path, "record": record, "turns": turns})
    return calls, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON, not a table")
    parser.add_argument(
        "--per-call", action="store_true", help="also summarize each call on its own"
    )
    parser.add_argument("--dir", default=RUNS_CALLS_DIR, help="call records directory")
    args = parser.parse_args()

    calls, skipped = load_calls(args.dir)

    groups: dict[str, list[dict]] = {}
    for call in calls:
        groups.setdefault(turn_latency.config_label(call["record"]), []).append(call)

    if args.json:
        print(
            json.dumps(
                {
                    "calls": len(calls),
                    "calls_without_timings": len(skipped),
                    "configs": {
                        label: {
                            "calls": len(group),
                            "summary": turn_latency.summarize(
                                [t for c in group for t in c["turns"]]
                            ),
                            "per_call": [
                                {
                                    "file": os.path.basename(c["path"]),
                                    "summary": turn_latency.summarize(c["turns"]),
                                }
                                for c in group
                            ],
                        }
                        for label, group in groups.items()
                    },
                },
                indent=2,
            )
        )
        return 0

    if not calls:
        print(f"No timed turns found in {args.dir}.")
        print("Run a call (make agent + make web), hang up, then try again.")
        return 1

    print(
        f"ClinicFlow voice latency: {len(calls)} call(s) across "
        f"{len(groups)} configuration(s)"
    )
    if skipped:
        print(f"({len(skipped)} call record(s) predate the timings and were skipped)")

    for label, group in groups.items():
        turns = [turn for call in group for turn in call["turns"]]
        print(f"\n=== {label}  ({len(group)} call(s)) ===")
        if args.per_call:
            for call in group:
                call_summary = turn_latency.summarize(call["turns"])
                e2e = call_summary.get("e2e", {})
                print(
                    f"  {os.path.basename(call['path']):44}"
                    f"{call_summary['turns_measured']:>3} turns   "
                    f"e2e p50 {e2e.get('p50', 0):>6.0f} ms   "
                    f"p95 {e2e.get('p95', 0):>6.0f} ms"
                )
            print()
        print(turn_latency.format_table(turn_latency.summarize(turns)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
