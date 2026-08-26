"""The deterministic assertion engine (amendment 13): pure Python, no LLM,
over the canonical Trace artifact ONLY — never engine or mock internals — so
it runs unchanged on real-agent traces in Phase 5.

Checks (the closed set from design §3 / amendment 13):
- validated_submit — each of the five submit tools requires a prior matching,
  successful counterpart call (validate or token/options fetch, per
  registry.SUBMIT_PAIRINGS) with a user turn strictly between the two agent
  turns. A warning/blocking counterpart status poisons the pair until a later
  successful re-validate. Whether the user turn between them is a genuine
  confirmation is a judge criterion, not checked here (amendment 4).
- amount_in_options — every validated amount (J1) or payment type (J2/J3)
  must come from the most recent options result for that card, or be a figure
  the customer stated themselves ("Other amount").
- refetch_after_card_switch — after ``selected_card`` changes, no validate or
  submit until the journey's options tool has been fetched again.
- must_not_call — scenario-forbidden tools must never be called.

The engine only REPORTS (adjustment 3): whether a failure stops the run is
the orchestrator's outcome derivation, so a future collect mode is a
parameter there, not a refactor here.

Degraded traces (amendment 18): every piece of evidence is optional. Missing
tool results drop only the status/identity/options-content checks; missing
``selected_card`` drops the switch check; both are recorded as structured
``degraded`` entries, and nothing here ever raises on a sparse trace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from . import registry
from .trace import Trace, TraceTurn
from .types import FailureRecord, ToolCall

# Assertion ids (FailureRecord.id values; Phase 4 clustering keys on these).
VALIDATED_SUBMIT = "validated_submit"
AMOUNT_IN_OPTIONS = "amount_in_options"
REFETCH_AFTER_CARD_SWITCH = "refetch_after_card_switch"
MUST_NOT_CALL = "must_not_call"


@dataclass
class AssertionReport:
    """Everything one check pass found: hard failures plus which checks could
    not fully run on this trace and why (structured, for reporting)."""

    failures: list[FailureRecord] = field(default_factory=list)
    degraded: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "failures": [f.to_dict() for f in self.failures],
            "degraded": self.degraded,
        }


@dataclass(frozen=True)
class _Call:
    pos: int  # global call order across the trace
    turn: TraceTurn
    call: ToolCall


class AssertionEngine:
    """Stateless and prefix-safe: the orchestrator calls ``check`` on the
    trace-so-far after every agent turn; Phase 4/5 call it on deserialized
    full traces. Same method, same results."""

    def __init__(self, must_not_call: Sequence[str] = ()) -> None:
        self.must_not_call = tuple(must_not_call)

    def check(self, trace: Trace) -> AssertionReport:
        report = AssertionReport()
        calls = [
            _Call(pos, turn, call)
            for pos, (turn, call) in enumerate(trace.iter_tool_calls())
        ]
        self._check_must_not_call(calls, report)
        self._check_validated_submit(trace, calls, report)
        self._check_amount_in_options(trace, calls, report)
        self._check_refetch_after_card_switch(trace, calls, report)
        return report

    # ------------------------------------------------------- must_not_call

    def _check_must_not_call(self, calls: list[_Call], report: AssertionReport) -> None:
        for c in calls:
            if c.call.name in self.must_not_call:
                report.failures.append(
                    FailureRecord(
                        source="assertion",
                        id=MUST_NOT_CALL,
                        turn_index=c.turn.index,
                        message=f"forbidden tool {c.call.name} was called",
                        data={"tool": c.call.name},
                    )
                )

    # ---------------------------------------------------- validated_submit

    def _check_validated_submit(
        self, trace: Trace, calls: list[_Call], report: AssertionReport
    ) -> None:
        for submit in calls:
            meta = registry.SUBMIT_PAIRINGS.get(submit.call.name)
            if meta is None:
                continue
            counterpart_name = meta["counterpart"]
            id_key = meta["id_result_key"]
            prior = [
                c
                for c in calls
                if c.pos < submit.pos and c.call.name == counterpart_name
            ]
            if not prior:
                report.failures.append(
                    FailureRecord(
                        source="assertion",
                        id=VALIDATED_SUBMIT,
                        turn_index=submit.turn.index,
                        message=(
                            f"{submit.call.name} called with no prior "
                            f"{counterpart_name}"
                        ),
                        data={"submit": submit.call.name, "counterpart": counterpart_name},
                    )
                )
                continue

            matching, identity_checked = self._match_pair(submit, prior, meta)
            if not identity_checked:
                report.degraded.append(
                    {
                        "check": VALIDATED_SUBMIT,
                        "turn_index": submit.turn.index,
                        "reason": (
                            f"pair identity for {submit.call.name} unverifiable "
                            "(no result/argument identity fields); matched by "
                            "ordering only"
                        ),
                    }
                )
            if not matching:
                report.failures.append(
                    FailureRecord(
                        source="assertion",
                        id=VALIDATED_SUBMIT,
                        turn_index=submit.turn.index,
                        message=(
                            f"{submit.call.name} does not match any prior "
                            f"{counterpart_name} (stale or different "
                            f"{id_key})"
                        ),
                        data={
                            "submit": submit.call.name,
                            "counterpart": counterpart_name,
                            "id_key": id_key,
                            "submit_id": submit.call.arguments.get(id_key)
                            if isinstance(submit.call.arguments, dict)
                            else None,
                        },
                    )
                )
                continue
            pair = matching[-1]  # the LAST matching counterpart governs

            ok = _result_success(pair.call.result)
            if ok is False:
                status = _result_status(pair.call.result)
                report.failures.append(
                    FailureRecord(
                        source="assertion",
                        id=VALIDATED_SUBMIT,
                        turn_index=submit.turn.index,
                        message=(
                            f"{submit.call.name} submitted while the matching "
                            f"{counterpart_name} status is {status!r} — the "
                            "pair is poisoned until re-validated"
                        ),
                        data={
                            "submit": submit.call.name,
                            "counterpart": counterpart_name,
                            "counterpart_status": status,
                        },
                    )
                )
                continue
            if ok is None:
                report.degraded.append(
                    {
                        "check": VALIDATED_SUBMIT,
                        "turn_index": submit.turn.index,
                        "reason": (
                            f"{counterpart_name} result missing — success "
                            "status unverifiable"
                        ),
                    }
                )

            if not _user_turn_between(trace, pair.turn.index, submit.turn.index):
                same_turn = pair.turn.index == submit.turn.index
                report.failures.append(
                    FailureRecord(
                        source="assertion",
                        id=VALIDATED_SUBMIT,
                        turn_index=submit.turn.index,
                        message=(
                            f"{submit.call.name} in the same agent turn as "
                            f"{counterpart_name} — no user turn between "
                            "validation and submission"
                            if same_turn
                            else f"no user turn between {counterpart_name} "
                            f"(turn {pair.turn.index}) and {submit.call.name} "
                            f"(turn {submit.turn.index})"
                        ),
                        data={
                            "submit": submit.call.name,
                            "counterpart": counterpart_name,
                            "validate_turn": pair.turn.index,
                            "submit_turn": submit.turn.index,
                        },
                    )
                )

    def _match_pair(
        self, submit: _Call, prior: list[_Call], meta: dict[str, object]
    ) -> tuple[list[_Call], bool]:
        """Counterpart calls that are FOR this submit's staged action:
        primary = the counterpart RESULT's id field equals the submit
        ARGUMENT of the same name; fallback = shared argument fields; last
        resort = all prior (ordering-only). Second value: whether any
        identity evidence existed."""
        id_key = str(meta["id_result_key"])
        submit_args = submit.call.arguments if isinstance(submit.call.arguments, dict) else {}
        submit_id = submit_args.get(id_key)
        if submit_id is not None:
            with_ids = [c for c in prior if _result_value(c.call.result, id_key) is not None]
            if with_ids:
                return [
                    c for c in with_ids if _result_value(c.call.result, id_key) == submit_id
                ], True
        for key in meta["match_arg_keys"]:  # type: ignore[union-attr]
            want = submit_args.get(key)
            if want is None:
                continue
            with_args = [
                c
                for c in prior
                if isinstance(c.call.arguments, dict) and c.call.arguments.get(key) is not None
            ]
            if with_args:
                return [c for c in with_args if c.call.arguments.get(key) == want], True
        return prior, False

    # --------------------------------------------------- amount_in_options

    # Validate tool → (options tool, how to read the chosen value).
    _AMOUNT_VALIDATES = {
        registry.ADD_VALIDATE_ONE_TIME_PAYMENT: (
            registry.ADD_OPTIONS_ONE_TIME_PAYMENT,
            "amount",
        ),
        registry.ADD_VALIDATE_AUTOPAY: (registry.ADD_OPTIONS_AUTOPAY, "paymentType"),
        registry.UPDATE_VALIDATE_AUTOPAY: (registry.UPDATE_AUTOPAY_OPTIONS, "paymentType"),
    }

    def _check_amount_in_options(
        self, trace: Trace, calls: list[_Call], report: AssertionReport
    ) -> None:
        for v in calls:
            spec = self._AMOUNT_VALIDATES.get(v.call.name)
            if spec is None:
                continue
            options_name, value_key = spec
            args = v.call.arguments if isinstance(v.call.arguments, dict) else {}
            value = args.get(value_key)
            if value is None:
                report.degraded.append(
                    {
                        "check": AMOUNT_IN_OPTIONS,
                        "turn_index": v.turn.index,
                        "reason": f"{v.call.name} arguments carry no {value_key!r}",
                    }
                )
                continue
            payee = args.get("payeeId")
            fetches = [
                c
                for c in calls
                if c.pos < v.pos
                and c.call.name == options_name
                and _payee_matches(c.call.arguments, payee)
            ]
            if not fetches:
                report.failures.append(
                    FailureRecord(
                        source="assertion",
                        id=AMOUNT_IN_OPTIONS,
                        turn_index=v.turn.index,
                        message=(
                            f"{v.call.name} for card {payee!r} with no prior "
                            f"{options_name} fetch for that card"
                        ),
                        data={
                            "validate": v.call.name,
                            "options_tool": options_name,
                            "payeeId": payee,
                            value_key: value,
                        },
                    )
                )
                continue
            options = _result_value(fetches[-1].call.result, "options")
            if not isinstance(options, list):
                report.degraded.append(
                    {
                        "check": AMOUNT_IN_OPTIONS,
                        "turn_index": v.turn.index,
                        "reason": f"{options_name} result carries no options list",
                    }
                )
                continue

            if value_key == "amount":
                offered = {
                    float(o["amount"])
                    for o in options
                    if isinstance(o, dict) and o.get("amount") is not None
                }
                if any(_money_eq(value, o) for o in offered):
                    continue
                if any(
                    _money_eq(value, fig)
                    for t in trace.turns
                    if t.speaker == "user" and t.index < v.turn.index
                    for fig in _user_figures(t.text)
                ):
                    continue  # the customer's own "Other amount"
                report.failures.append(
                    FailureRecord(
                        source="assertion",
                        id=AMOUNT_IN_OPTIONS,
                        turn_index=v.turn.index,
                        message=(
                            f"amount {value} is not among the options fetched for "
                            f"card {payee!r} and was never stated by the customer"
                        ),
                        data={
                            "validate": v.call.name,
                            "amount": value,
                            "payeeId": payee,
                            "offered": sorted(offered),
                        },
                    )
                )
            else:
                offered_ids = {
                    o.get("optionId") for o in options if isinstance(o, dict)
                }
                if value not in offered_ids:
                    report.failures.append(
                        FailureRecord(
                            source="assertion",
                            id=AMOUNT_IN_OPTIONS,
                            turn_index=v.turn.index,
                            message=(
                                f"payment type {value!r} is not among the option "
                                f"ids fetched for card {payee!r}"
                            ),
                            data={
                                "validate": v.call.name,
                                "paymentType": value,
                                "payeeId": payee,
                                "offered": sorted(str(o) for o in offered_ids),
                            },
                        )
                    )

    # ------------------------------------------ refetch_after_card_switch

    def _check_refetch_after_card_switch(
        self, trace: Trace, calls: list[_Call], report: AssertionReport
    ) -> None:
        switches = switch_turn_indices(trace)
        checked_tools = {
            name
            for name, meta in registry.SUBMIT_PAIRINGS.items()
            if meta["options_tool"] is not None
        } | {
            str(meta["counterpart"])
            for meta in registry.SUBMIT_PAIRINGS.values()
            if meta["options_tool"] is not None
        }
        if not switches:
            if all(t.selected_card is None for t in trace.turns) and any(
                c.call.name in checked_tools for c in calls
            ):
                report.degraded.append(
                    {
                        "check": REFETCH_AFTER_CARD_SWITCH,
                        "turn_index": None,
                        "reason": (
                            "selected_card never reported by the adapter — "
                            "card switches undetectable"
                        ),
                    }
                )
            return

        for c in calls:
            options_name = self._options_tool_for(c.call.name)
            if options_name is None:
                continue
            last_switch = max((s for s in switches if s <= c.turn.index), default=None)
            if last_switch is None:
                continue
            args = c.call.arguments if isinstance(c.call.arguments, dict) else {}
            payee = args.get("payeeId")
            refetched = any(
                f.pos < c.pos
                and f.call.name == options_name
                and f.turn.index >= last_switch
                and _payee_matches(f.call.arguments, payee)
                for f in calls
            )
            if not refetched:
                report.failures.append(
                    FailureRecord(
                        source="assertion",
                        id=REFETCH_AFTER_CARD_SWITCH,
                        turn_index=c.turn.index,
                        message=(
                            f"{c.call.name} after the card switch at turn "
                            f"{last_switch} without a fresh {options_name} fetch"
                        ),
                        data={
                            "tool": c.call.name,
                            "options_tool": options_name,
                            "switch_turn": last_switch,
                            "payeeId": payee,
                        },
                    )
                )

    @staticmethod
    def _options_tool_for(tool_name: str) -> str | None:
        """The options tool that must be re-fetched before this validate or
        submit runs post-switch; None for tools outside the pairings or in
        the token-fetch flows (no amount options to go stale)."""
        meta = registry.SUBMIT_PAIRINGS.get(tool_name)
        if meta is not None:
            return meta["options_tool"]  # type: ignore[return-value]
        for m in registry.SUBMIT_PAIRINGS.values():
            if m["counterpart"] == tool_name:
                return m["options_tool"]  # type: ignore[return-value]
        return None


# ---------------------------------------------------------------- helpers


def _result_value(result: Any, key: str) -> Any:
    return result.get(key) if isinstance(result, dict) else None


def _result_status(result: Any) -> str | None:
    status = _result_value(result, "status")
    return str(status) if status is not None else None


def _result_success(result: Any) -> bool | None:
    """Was this counterpart call successful? True/False when the result says,
    None when there is no result to read (degraded). A result dict without a
    status field (the token/options fetches) counts as success by presence;
    only status 'ready' counts for validates — 'warning' and any error/
    blocking status poison the pair until re-validated."""
    if result is None:
        return None
    status = _result_status(result)
    if status is None:
        return True
    return status.lower() == "ready"


def _user_turn_between(trace: Trace, start_index: int, end_index: int) -> bool:
    return any(
        t.speaker == "user" and start_index < t.index < end_index for t in trace.turns
    )


def _payee_matches(arguments: Any, payee: Any) -> bool:
    """Same-card match on payeeId; a missing id on either side matches (the
    evidence to discriminate is absent — fail-quiet, per degraded rules)."""
    if payee is None or not isinstance(arguments, dict):
        return True
    theirs = arguments.get("payeeId")
    return theirs is None or theirs == payee


def switch_turn_indices(trace: Trace) -> list[int]:
    """Turn indices where the reported selected card changed (both values
    known). The first non-None report is a selection, not a switch."""
    switches: list[int] = []
    prev: str | None = None
    for t in trace.turns:
        if t.selected_card is None:
            continue
        if prev is not None and t.selected_card != prev:
            switches.append(t.index)
        prev = t.selected_card
    return switches


def _money_eq(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.005
    except (TypeError, ValueError):
        return False


_DOLLAR_RE = re.compile(r"\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")
_DOLLARS_WORD_RE = re.compile(
    r"\b(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*(?:dollars|bucks)\b"
)
_DECIMAL_RE = re.compile(r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b|\b\d+\.\d{2}\b")
_BARE_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?")


def _user_figures(text: str) -> Iterable[float]:
    """Dollar figures a customer stated: $-prefixed, dollars/bucks-suffixed,
    cents-precise decimals, or a bare number standing as the whole message.
    Deliberately conservative — a card's "ending in 0767" is none of these,
    so last-fours never read as customer-declared amounts."""
    figures: set[float] = set()
    for m in _DOLLAR_RE.finditer(text):
        figures.add(float(m.group(1).replace(",", "")))
    for m in _DOLLARS_WORD_RE.finditer(text):
        figures.add(float(m.group(1).replace(",", "")))
    for m in _DECIMAL_RE.finditer(text):
        figures.add(float(m.group(0).replace(",", "")))
    bare = text.strip().rstrip(".!?")
    if _BARE_NUMBER_RE.fullmatch(bare):
        figures.add(float(bare.replace(",", "")))
    return figures
