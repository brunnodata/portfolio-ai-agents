from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.config import get_settings

settings = get_settings()


@dataclass
class LLMCostTotals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_brl: Decimal = Decimal("0")
    updated_at: datetime | None = None


class LLMCostTracker:
    def __init__(self) -> None:
        self._totals = LLMCostTotals()

    def track_usage(self, input_tokens: int, output_tokens: int) -> None:
        input_tokens = max(int(input_tokens or 0), 0)
        output_tokens = max(int(output_tokens or 0), 0)
        total_tokens = input_tokens + output_tokens

        input_cost = (Decimal(input_tokens) / Decimal("1000")) * Decimal(
            str(settings.llm_input_cost_per_1k_brl)
        )
        output_cost = (Decimal(output_tokens) / Decimal("1000")) * Decimal(
            str(settings.llm_output_cost_per_1k_brl)
        )

        self._totals.calls += 1
        self._totals.input_tokens += input_tokens
        self._totals.output_tokens += output_tokens
        self._totals.total_tokens += total_tokens
        self._totals.estimated_brl += input_cost + output_cost
        self._totals.updated_at = datetime.now(timezone.utc)

    def snapshot(self) -> dict:
        budget = Decimal(str(settings.llm_daily_budget_brl))
        spent = self._totals.estimated_brl.quantize(Decimal("0.0001"))
        pct = float((spent / budget * Decimal("100")) if budget > 0 else Decimal("0"))
        remaining = (budget - spent).quantize(Decimal("0.0001"))

        return {
            "calls": self._totals.calls,
            "input_tokens": self._totals.input_tokens,
            "output_tokens": self._totals.output_tokens,
            "total_tokens": self._totals.total_tokens,
            "estimated_brl": float(spent),
            "daily_budget_brl": float(budget),
            "budget_used_percent": max(pct, 0.0),
            "budget_remaining_brl": float(remaining),
            "updated_at": self._totals.updated_at.isoformat() if self._totals.updated_at else None,
            "rates": {
                "input_per_1k_brl": settings.llm_input_cost_per_1k_brl,
                "output_per_1k_brl": settings.llm_output_cost_per_1k_brl,
            },
        }


llm_cost_tracker = LLMCostTracker()
