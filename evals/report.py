"""Render committed run summaries as Markdown results tables.

    python -m evals.report baseline=runs/a/summary.json candidate=runs/b/summary.json

Each column is one labelled summary. Rows are scenarios: trials passed and
mean score, then the critical failures observed across that scenario's trials.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def per_scenario(summary: dict) -> dict[str, dict]:
    cards = defaultdict(list)
    for card in summary["scorecards"]:
        cards[card["scenario_id"]].append(card)
    out = {}
    for scenario, items in cards.items():
        critical = Counter(code for card in items for code in card["critical_failures"])
        out[scenario] = {"trials": len(items), "passed": sum(card["passed"] for card in items),
                         "mean": sum(card["score"] for card in items) / len(items), "critical": critical,
                         "errors": sum(bool(card["evaluator_errors"]) for card in items)}
    return out


def totals(summary: dict) -> dict:
    cards = summary["scorecards"]
    return {"trials": len(cards), "passed": sum(c["passed"] for c in cards),
            "mean": sum(c["score"] for c in cards) / len(cards),
            "critical": sum(bool(c["critical_failures"]) for c in cards),
            "spent": (summary.get("budget") or {}).get("spent_usd")}


def render(columns: list[tuple[str, dict]]) -> str:
    tables = [(label, per_scenario(summary)) for label, summary in columns]
    scenarios = sorted(set().union(*(set(t) for _, t in tables)))
    head = "| Scenario | " + " | ".join(f"{label}: passed, mean" for label, _ in tables) + " |"
    lines = [head, "| --- |" + " --- |" * len(tables)]
    for scenario in scenarios:
        cells = []
        for _, table in tables:
            row = table.get(scenario)
            cells.append("n/a" if row is None else f"{row['passed']}/{row['trials']}, {row['mean']:.1f}")
        lines.append(f"| {scenario} | " + " | ".join(cells) + " |")
    cells = []
    for _, summary in columns:
        t = totals(summary)
        cells.append(f"**{t['passed']}/{t['trials']}, {t['mean']:.1f}**")
    lines.append("| **All** | " + " | ".join(cells) + " |")
    lines += ["", "Critical failures by scenario (count of trials):", ""]
    lines.append("| Scenario | " + " | ".join(label for label, _ in tables) + " |")
    lines.append("| --- |" + " --- |" * len(tables))
    for scenario in scenarios:
        cells = []
        for _, table in tables:
            row = table.get(scenario)
            critical = row["critical"] if row else Counter()
            cells.append(", ".join(f"{code} ×{n}" for code, n in sorted(critical.items())) or "none")
        if any(cell != "none" for cell in cells):
            lines.append(f"| {scenario} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    columns = []
    for argument in sys.argv[1:]:
        label, _, path = argument.partition("=")
        if not path:
            raise SystemExit("usage: python -m evals.report label=path/summary.json ...")
        columns.append((label, json.loads(Path(path).read_text(encoding="utf-8"))))
    if not columns:
        raise SystemExit("usage: python -m evals.report label=path/summary.json ...")
    sys.stdout.write(render(columns))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
