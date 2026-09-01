"""Fail-closed credit pre-flight for commands that make live LLM calls."""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from typing import Mapping


class LiveCreditError(ValueError):
    """A live command has no sufficient configured credit lower bound."""


def live_credit_preflight(
    maximum_planned_llm_calls: int,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return (credit floor, per-call ceiling, command ceiling) or fail closed.

    OpenAI's installed client exposes no supported available-balance resource,
    so the operator supplies a conservative lower bound on current USD credit.
    """
    if maximum_planned_llm_calls < 0:
        raise LiveCreditError("maximum planned LLM calls must not be negative")
    values = os.environ if environ is None else environ
    credit_floor = _positive_usd(values, "AGENTSIM_LIVE_CREDIT_FLOOR_USD")
    per_call = _positive_usd(values, "AGENTSIM_MAX_COST_PER_LLM_CALL_USD")
    ceiling = per_call * maximum_planned_llm_calls
    if credit_floor <= ceiling:
        raise LiveCreditError(
            "configured live credit floor must exceed the printed cost ceiling: "
            f"AGENTSIM_LIVE_CREDIT_FLOOR_USD={credit_floor} <= {ceiling} USD"
        )
    return credit_floor, per_call, ceiling


def _positive_usd(values: Mapping[str, str], name: str) -> Decimal:
    raw = values.get(name)
    if raw is None:
        raise LiveCreditError(f"{name} must be configured before any live command")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise LiveCreditError(f"{name} must be a finite positive USD amount") from exc
    if not value.is_finite() or value <= 0:
        raise LiveCreditError(f"{name} must be a finite positive USD amount")
    return value
