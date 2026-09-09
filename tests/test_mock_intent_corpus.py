"""Corpus test for the mock's J1 intent gate (recovery plan Phase 1 step 1).

Every recorded customer turn under
`synthesized_scenarios/runs/*/episodes/*-transcript.jsonl` is replayed, in
transcript order, through a fresh `MockPayCardAgent()`. The turns were
labeled once, offline, by the calibrated judge model (see
`scripts/label_j1_customer_turns.py` and the fixture header), so the rules
below are checked against labels the mock's own regexes did not produce.

Rules, per labeled turn:

- question: stages nothing — no amount, date, or pending payment takes a new
  value, the card does not switch, and no validate or submit tool call fires.
- correction: selects only its labeled slot(s); every other slot is unchanged
  or cleared, never set to something new.
- every turn: no negated card or option is ever acted on.

`KNOWN_FAILING` is the exact set of turn ids that still break a rule, each
with the reason. The test fails on drift in either direction, so a fix must
shrink the set in the same commit and a regression cannot hide.
"""

from __future__ import annotations

import glob
import json
from datetime import date
from pathlib import Path

import pytest

from agentsim import registry
from agentsim.adapters import MockPayCardAgent
from conftest import MockDriver

ROOT = Path(__file__).resolve().parent.parent
LABELS_PATH = ROOT / "tests" / "fixtures" / "j1_customer_turn_labels.json"
CORPUS_GLOB = "synthesized_scenarios/runs/*/episodes/*-transcript.jsonl"

_DOC = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
LABELS_BY_TEXT: dict[str, dict] = {t["text"]: t for t in _DOC["turns"]}

# Turn ids (see the fixture) whose rule cannot hold in the current mock, with
# the reason. Multi-intent two-payment turns are the untriaged mock behavior
# the recovery plan leaves out of step 1.
MULTI_INTENT = "multi-intent two-payment turn; untriaged, outside recovery plan step 1"
KNOWN_FAILING: dict[int, str] = {
    6: 'M-019: question sentence is mined for an amount',
    7: 'M-019: question sentence is mined for an amount',
    14: 'label disagreement: the labeler omitted the statement-balance option the declarative sentence names',
    17: 'label disagreement: the labeler omitted the statement-balance option the declarative sentence names',
    19: 'M-018: two-card correction naming the current card does not switch',
    24: 'M-018: two-card correction naming the current card does not switch',
    25: MULTI_INTENT,
    26: MULTI_INTENT,
    27: MULTI_INTENT,
    28: MULTI_INTENT,
    30: MULTI_INTENT,
    31: MULTI_INTENT,
    32: MULTI_INTENT,
    33: MULTI_INTENT,
    34: MULTI_INTENT,
    52: 'M-019: question sentence is mined for an amount',
    57: 'M-019: question sentence is mined for an amount',
    91: 'M-019: question sentence is mined for an amount',
    94: 'M-019: question sentence is mined for an amount',
    117: 'M-019: question sentence is mined for an amount',
    118: 'M-019: date staged onto an amount mined from a question',
    121: 'M-019: question sentence is mined for an amount',
    122: 'M-019: date staged onto an amount mined from a question',
    126: 'M-019: question sentence is mined for an amount',
    130: 'M-019: question sentence is mined for an amount',
    134: 'M-019: question sentence is mined for an amount',
}


def transcripts() -> list[tuple[str, list[str]]]:
    out = []
    for path in sorted(glob.glob(str(ROOT / CORPUS_GLOB))):
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("record_type") != "episode":
                continue
            turns = [t["text"] for t in rec["turns"] if t["speaker"] == "user"]
            if turns:
                name = f"{Path(path).parent.parent.name[14:22]}/{Path(path).stem}"
                out.append((name, turns))
    return out


def snapshot(state) -> dict:
    return {
        "card": state.selected_card.last_four if state.selected_card else None,
        "amount": state.amount,
        "amount_label": state.amount_label,
        "date": state.payment_date,
        "pending": (state.pending.card_label, state.pending.amount, state.pending.payment_date)
        if state.pending
        else None,
    }


def _took_new_value(before, after) -> bool:
    return after is not None and after != before


def _amount_matches(label: dict, after: dict, options) -> bool:
    want = label["actionable"]["amount"]
    if want.startswith("$"):
        return after["amount"] == float(want[1:].replace(",", ""))
    figure = next((o["amount"] for o in options or [] if str(o["label"]).lower() == want.lower()), None)
    return (after["amount_label"] or "").lower() == want.lower() or (
        figure is not None and after["amount"] == figure
    )


def violations(label: dict, before: dict, after: dict, calls: list[str], options) -> list[str]:
    out: list[str] = []
    intent = label["intent"]
    staging_calls = {registry.ADD_VALIDATE_ONE_TIME_PAYMENT, registry.ADD_ONE_TIME_PAYMENT}
    if intent == "question":
        for slot in ("amount", "date", "pending"):
            if _took_new_value(before[slot], after[slot]):
                out.append(f"question staged {slot}={after[slot]!r}")
        if before["card"] is not None and _took_new_value(before["card"], after["card"]):
            out.append(f"question switched card to {after['card']}")
        if staging_calls & set(calls):
            out.append(f"question fired {sorted(staging_calls & set(calls))}")
    elif intent == "correction":
        want = label["actionable"]
        if want["card"] is not None and after["card"] != want["card"]:
            out.append(f"correction wanted card {want['card']}, got {after['card']}")
        if want["card"] is None and _took_new_value(before["card"], after["card"]):
            out.append(f"correction switched card to {after['card']} unasked")
        if want["amount"] is not None and not _amount_matches(label, after, options):
            out.append(f"correction wanted amount {want['amount']}, got {after['amount_label']} {after['amount']}")
        if want["amount"] is None and _took_new_value(before["amount"], after["amount"]):
            out.append(f"correction set amount {after['amount']} unasked")
        if want["date"] is not None and after["date"] != date.fromisoformat(want["date"]):
            out.append(f"correction wanted date {want['date']}, got {after['date']}")
        if want["date"] is None and _took_new_value(before["date"], after["date"]):
            out.append(f"correction set date {after['date']} unasked")
    for negated in label["negated"]:
        if negated.isdigit():
            if after["card"] == negated or (after["pending"] and negated in after["pending"][0]):
                out.append(f"acted on negated card {negated}")
        elif negated.startswith("$"):
            figure = float(negated[1:].replace(",", ""))
            if after["amount"] == figure or (after["pending"] and after["pending"][1] == figure):
                out.append(f"acted on negated amount {negated}")
        elif (after["amount_label"] or "").lower() == negated.lower():
            out.append(f"acted on negated option {negated}")
    return out


async def replay(turns: list[str]) -> list[tuple[int, str]]:
    driver = MockDriver(MockPayCardAgent())
    found: list[tuple[int, str]] = []
    for text in turns:
        label = LABELS_BY_TEXT[text]
        before = snapshot(driver.state) if driver.conversation_id in driver.agent._states else snapshot_empty()
        response = await driver.say(text)
        after = snapshot(driver.state)
        calls = [c.name for c in response.tool_calls]
        for v in violations(label, before, after, calls, driver.state.options):
            found.append((label["id"], v))
    return found


def snapshot_empty() -> dict:
    return {"card": None, "amount": None, "amount_label": None, "date": None, "pending": None}


async def test_every_recorded_turn_is_labeled():
    for _, turns in transcripts():
        for text in turns:
            assert text in LABELS_BY_TEXT
    assert len(LABELS_BY_TEXT) == _DOC["header"]["counts"]["unique_customer_turns"] == 136


async def test_intent_gate_over_recorded_customer_turns():
    failing: dict[int, set[str]] = {}
    for _, turns in transcripts():
        for turn_id, reason in await replay(turns):
            failing.setdefault(turn_id, set()).add(reason)
    unexpected = {k: sorted(v) for k, v in failing.items() if k not in KNOWN_FAILING}
    assert not unexpected, f"turns newly breaking a rule: {unexpected}"
    fixed = sorted(set(KNOWN_FAILING) - set(failing))
    assert not fixed, f"turns in KNOWN_FAILING now pass; remove them: {fixed}"
