"""Hard spend cap shared by every paid model call in one command.

The cap is checked before each call. A call that cannot start inside the
remaining budget raises BudgetExceeded; the runner records that trial as
`budget_stopped`, which scoring treats as incomplete, never as a pass.

Costs come from provider-reported usage. OpenRouter returns a dollar cost on
each response; Anthropic returns token counts, priced here from the published
per-million-token rates (cache writes 1.25x, cache reads 0.1x, batch 0.5x).
"""
from __future__ import annotations

ANTHROPIC_PRICES = {  # USD per million tokens: (input, output)
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


class BudgetExceeded(RuntimeError):
    pass


def anthropic_cost(model: str, usage: dict, *, batch: bool = False) -> float:
    if model not in ANTHROPIC_PRICES:
        raise ValueError(f"no price recorded for {model}")
    price_in, price_out = ANTHROPIC_PRICES[model]
    tokens_in = (usage.get("input_tokens") or 0) \
        + 1.25 * (usage.get("cache_creation_input_tokens") or 0) \
        + 0.1 * (usage.get("cache_read_input_tokens") or 0)
    cost = (tokens_in * price_in + (usage.get("output_tokens") or 0) * price_out) / 1e6
    return cost * (0.5 if batch else 1.0)


class Budget:
    def __init__(self, limit_usd: float | None):
        self.limit = limit_usd
        self.spent = 0.0
        self.by_role: dict[str, float] = {}

    def check(self, reserve: float = 0.0, *, role: str = "") -> None:
        """Refuse to start a call that could take spend past the limit."""
        if self.limit is not None and self.spent + reserve > self.limit:
            raise BudgetExceeded(
                f"budget ${self.limit:.2f} would be exceeded by {role or 'next call'}: "
                f"spent ${self.spent:.4f}, reserving ${reserve:.4f}")

    def add(self, cost: float, role: str) -> None:
        self.spent += cost
        self.by_role[role] = self.by_role.get(role, 0.0) + cost

    def summary(self) -> dict:
        return {"limit_usd": self.limit, "spent_usd": round(self.spent, 4),
                "by_role": {k: round(v, 4) for k, v in sorted(self.by_role.items())}}
