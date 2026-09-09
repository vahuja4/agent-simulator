"""Deterministic text parsing for the mock: card/account/amount/date
matching, confirm/decline/pressure phrase detection, and the journey router.
Pure functions over fixture data — no state, no LLM.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from fixtures.paycard import Card, FundingAccount

CONFIRM_RE = re.compile(
    r"\b(yes|yep|yeah|confirm|confirmed|correct|go ahead|do it|sounds good|"
    r"schedule it|sure|please do|proceed|looks good|that works)\b"
)
DECLINE_RE = re.compile(
    r"\b(no|don'?t|do not|cancel|stop|wait|hold on|nevermind|never mind|actually)\b"
)
PAY_INTENT_RE = re.compile(r"\b(pay|payment|bill|balance due|owe)\b")

# Pressure phrases used by the J1 confirmation gate to separate interaction
# pressure from a clean confirmation or decline. D1 modes are keyed to the
# gate outcome itself, not to this wording detector.
# M7 calibration fix: "stop <gerund>" resolves by the gerund's CLASS, not by
# what follows it. Process gerunds ("stop asking", "stop repeating", "stop
# making this take forever", "stop taking/wasting my time") are pressure
# about the interaction; payment-action gerunds (_PAYMENT_ACTION_GERUNDS)
# are genuine declines regardless of trailing object — "stop paying", "stop
# processing the payment" — left intact so the gate classifier sees the
# decline. An
# unknown gerund defaults to pressure (strip → re-ask, the fallback that
# errs toward holding). The old payments-noun carve-out is now a consequence
# of the rule: "stop processing the payment" declines because of its gerund,
# not its object. Deliberate residual: a bare pronoun object flips a
# payment-action gerund back to pressure ("stop processing it" strips),
# because a pronoun after a stop-gerund routinely names the interaction, not
# the payment — "stop making this take forever" — so a pronoun object can
# never be a decline signal. A bare "stop" or "stop the payment" still
# declines through the gate-local decline allowlist.
# M6 calibration fix: a proceed-imperative conjoined to the stop-gerund —
# "stop asking and (just) schedule it" — strips as ONE pressure phrase. M9
# then applies J1's finite, full-utterance affirmation allowlist to whatever
# remains. Shared CONFIRM_RE deliberately remains broad for non-gate,
# mid-flow assents in every journey. The M7 gerund-class rule above is
# untouched.
_PAYMENT_ACTION_GERUNDS = r"(?:paying|processing|scheduling|submitting|sending|charging)"
PRESSURE_RE = re.compile(
    r"just (pay|do|submit|send|schedule)|"
    r"stop (?:"
    + _PAYMENT_ACTION_GERUNDS
    + r"\s+(?:it|this|that)\b(?!\s+payments?\b)"
    r"|(?!" + _PAYMENT_ACTION_GERUNDS + r"\b)\w+ing\b"
    r")"
    r"(?:\s+and\s+(?:just\s+)?(?:pay|do|submit|send|schedule)\b"
    r"(?:\s+(?:it|this|that|(?:the|this|that|my)\s+payments?))?)?|"
    r"hurry|right now|skip the|come on|already\b|no more questions"
)

# Live-agent requests, honored only after the mock itself has offered the
# handoff (M2 calibration fix).
LIVE_AGENT_RE = re.compile(r"live agent|\bhuman\b|\brepresentative\b|real person")


def strip_pressure(text: str) -> str:
    """Remove pressure phrasing before J1's gate-local classifier runs.

    Pressure is neither a decline nor a confirmation, so the "stop" in
    "stop asking" must not cancel and a proceed-demand such as "schedule it"
    must not become an affirmation. The strict M9 classifier owns the final
    confirm/decline/re-ask decision; this helper only removes pressure idioms.
    """
    return PRESSURE_RE.sub(" ", text)

# Journey routing vocabulary.
_AUTOPAY_RE = re.compile(r"\bauto[- ]?pay\b|\bautomatic payments?\b|\brecurring\b")
_CANCELISH_RE = re.compile(r"\b(cancel|turn off|switch off|stop|remove|disable|end)\b")
_MODIFYISH_RE = re.compile(r"\b(change|update|modify|edit|adjust)\b")
_PAYMENTISH_RE = re.compile(r"\bpayments?\b|\bscheduled\b")

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        "january february march april may june july august september october november december".split()
    )
}


def route_journey(text: str) -> str | None:
    """Map an opening message to a journey. Deterministic keyword precedence:

        1. AutoPay mention + cancel-ish wording        → J4
        2. AutoPay mention + change/update wording     → J3
        3. AutoPay mention                             → J2
        4. cancel-ish wording + a payment referent     → J5
        5. pay intent                                  → J1

    Returns None when nothing matches (greet and wait). A conversation stays
    in its journey once routed.

    Known limitation, deliberately kept: "cancel my autopay payment on
    June 20" routes to J4 (rule 1) even though the customer means a specific
    pending payment, which is J5's territory (where the mock correctly says
    AutoPay pendings can't be cancelled). Routing cancel + autopay + a
    specific-payment referent to J5 is a candidate refinement deferred with
    the cross-journey mind-change work; scenario openers that need J5 (the D6
    scenario) must avoid "autopay" phrasing — see
    scenarios/j5_cancel_autopay_pending.yaml.
    """
    if _AUTOPAY_RE.search(text):
        if _CANCELISH_RE.search(text):
            return "J4"
        if _MODIFYISH_RE.search(text):
            return "J3"
        return "J2"
    if _CANCELISH_RE.search(text) and _PAYMENTISH_RE.search(text):
        return "J5"
    if PAY_INTENT_RE.search(text):
        return "J1"
    return None


def fmt_money(amount: float) -> str:
    return f"${amount:,.2f}"


def fmt_date(d: date) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def find_cards(text: str, cards: tuple[Card, ...]) -> list[Card]:
    """Cards the message refers to. Last-four digits are definite; name
    tokens score fuzzily, and a tie (e.g. "freedom" with two Freedom cards)
    returns multiple → the caller must disambiguate by last four
    (invariant 5)."""
    definite = [c for c in cards if c.last_four in text]
    if definite:
        return definite
    scores: dict[str, int] = {}
    for c in cards:
        tokens = [t for t in c.name.lower().split() if t != "chase"]
        scores[c.card_id] = sum(1 for t in tokens if re.search(rf"\b{t}\b", text))
    best = max(scores.values())
    if best == 0:
        return []
    return [c for c in cards if scores[c.card_id] == best]


# Negation window (M-018): a card named right after "not", "instead of",
# "rather than", or "no longer" is being rejected, not chosen. The window
# runs to the next clause boundary, so in "the 0767, not 9013. Please ..."
# only "9013" is negated.
_NEGATION_RE = re.compile(r"\b(?:not|instead of|rather than|no longer)\b")
_CLAUSE_END_RE = re.compile(r"[.,;:!?]|\b(?:and|but|so)\b")


def negated_windows(text: str) -> list[tuple[int, int]]:
    """Character spans of the message that sit inside a negation window."""
    windows: list[tuple[int, int]] = []
    for match in _NEGATION_RE.finditer(text):
        start = match.end()
        boundary = _CLAUSE_END_RE.search(text, start)
        windows.append((start, boundary.start() if boundary else len(text)))
    return windows


def card_mentions(text: str, cards: tuple[Card, ...]) -> tuple[list[Card], list[Card]]:
    """Cards the message names, split into (affirmed, negated). A card inside
    a negation window is excluded from the affirmed set, so "I meant the card
    ending in 0767, not 9013" affirms 0767 alone and negates 9013 (M-018).
    Affirmed ties keep ``find_cards`` semantics for the caller to resolve."""
    windows = negated_windows(text)
    if not windows:
        return find_cards(text, cards), []
    negated_text = " ".join(text[start:end] for start, end in windows)
    affirmed_text = list(text)
    for start, end in windows:
        affirmed_text[start:end] = " " * (end - start)
    negated = find_cards(negated_text, cards) if negated_text.strip() else []
    return find_cards("".join(affirmed_text), cards), negated


def find_account(text: str, accounts: tuple[FundingAccount, ...]) -> FundingAccount | None:
    definite = [a for a in accounts if a.last_four in text]
    if len(definite) == 1:
        return definite[0]
    scored: list[FundingAccount] = []
    for a in accounts:
        # The brand token "chase" is excluded, as in find_cards, so naming a
        # Chase card ("Chase Freedom Flex") never silently selects the Chase
        # funding account (M4 calibration fix).
        tokens = [t for t in a.name.lower().split() if t != "chase"]
        if any(re.search(rf"\b{t}\b", text) for t in tokens):
            scored.append(a)
    return scored[0] if len(scored) == 1 else None


def extract_money(text: str, strip_last_fours: list[str]) -> float | None:
    """An explicit dollar figure in the message. Known last-four digits are
    stripped first so "ending in 0767" is never read as $767."""
    cleaned = text
    for four in strip_last_fours:
        cleaned = cleaned.replace(four, " ")
    m = re.search(r"\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)", cleaned)
    if m is None:
        m = re.search(
            r"\b(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*(?:dollars|bucks)\b",
            cleaned,
        )
    if m is None:
        bare = cleaned.strip().rstrip(".!")
        if re.fullmatch(r"\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?", bare):
            return float(bare.replace(",", ""))
        return None
    return float(m.group(1).replace(",", ""))


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_CLOSING_QUOTES = "\"'’”)"
# Sentence intent (M-019): a sentence is a question when it ends in "?",
# opens with an interrogative, or embeds one ("I'm not sure which option
# that is", "please explain which named option means the full bill").
_INTERROGATIVE_OPENER_RE = re.compile(
    r"^(?:which|what|why|how|when|where|who|whom|whose)\b|"
    r"^(?:is|are|was|were|does|do|did|can|could|would|will|should|may|might|am)"
    r"\s+(?:i|you|it|that|this|those|these|there|we|they)\b"
)
_EMBEDDED_INTERROGATIVE_RE = re.compile(
    r"\b(?:not sure|unsure|explain|tell me|clarify|confirm|know|asked|asking|wondering)\b"
    r"[^.!?]*\b(?:which|what|whether|how)\b"
)


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]


def is_question(sentence: str) -> bool:
    body = sentence.strip().rstrip(_CLOSING_QUOTES)
    if body.endswith("?"):
        return True
    opener = body.lstrip("\"'‘“(").strip()
    return bool(
        _INTERROGATIVE_OPENER_RE.match(opener) or _EMBEDDED_INTERROGATIVE_RE.search(opener)
    )


def declarative_text(text: str) -> str:
    """The message minus its question sentences. Slot extraction runs on
    this alone (M-019): a question is answered, never mined for a card,
    amount, or date."""
    return " ".join(s for s in split_sentences(text) if not is_question(s))


def question_text(text: str) -> str:
    """The message's question sentences, joined — the answering path's input."""
    return " ".join(s for s in split_sentences(text) if is_question(s))


def match_amount_text(
    text: str, options: list[dict[str, object]], strip_last_fours: list[str]
) -> tuple[str, float] | None:
    """Match a J1 message against the fetched amount options: option
    keywords first, then an explicit dollar figure as "Other amount".

    Only the non-question sentences are read (M5, then M-019): "why does it
    say remaining statement balance is $210.45? I want to pay the statement
    balance" resolves to the declared choice, and a question that names a
    label ("the statement balance or the remaining statement balance?")
    matches nothing — the answering path handles it. The old full-text
    fallback that let "can you do the minimum?" select the minimum is gone;
    a question is answered, not staged."""

    def option(option_id: str) -> tuple[str, float]:
        o = next(o for o in options if o["optionId"] == option_id)
        return str(o["label"]), float(o["amount"])  # type: ignore[arg-type]

    def match_in(candidate: str) -> tuple[str, float] | None:
        # An explicitly stated amount wins over a displayed option label.
        # Use the last non-negated figure so a correction retains the amount
        # the customer actually requested.
        cleaned = candidate
        for four in strip_last_fours:
            cleaned = cleaned.replace(four, " ")
        stated: list[float] = []
        for match in re.finditer(
            r"\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)",
            cleaned,
        ):
            if not re.search(r"\bnot\s*$", cleaned[: match.start()]):
                stated.append(float(match.group(1).replace(",", "")))
        if stated:
            return ("Other amount", stated[-1])
        if "remaining statement" in candidate:
            return option("remaining_statement_balance")
        if "statement" in candidate:
            return option("statement_balance")
        if "minimum" in candidate:
            return option("minimum_due")
        if (
            re.search(r"\b(current|full|entire|whole)\s+balance\b", candidate)
            or "pay it off" in candidate
        ):
            return option("current_balance")

        figure = extract_money(candidate, strip_last_fours)
        if figure is None:
            return None
        return ("Other amount", figure)

    return match_in(declarative_text(text))


def match_autopay_type(
    text: str, strip_last_fours: list[str]
) -> tuple[str, str, float | None] | None:
    """Match a message against the AutoPay amount types (J2/J3):
    (optionId, label, fixed_amount|None). A bare dollar figure counts as
    choosing a fixed amount of that figure."""
    if "minimum" in text:
        return ("minimum_due", "Minimum payment due", None)
    if "statement" in text:
        return ("statement_balance", "Statement balance", None)
    figure = extract_money(text, strip_last_fours)
    if "fixed" in text:
        return ("fixed", "Fixed amount", figure)
    if figure is not None:
        return ("fixed", "Fixed amount", figure)
    return None


def match_date(text: str, card: Card, today: date) -> date | None:
    if "due date" in text or "the due" in text:
        return card.due_date
    if "today" in text:
        return today
    if "tomorrow" in text:
        return today + timedelta(days=1)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", text)
    if m is None:
        m = re.search(
            r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + "|".join(_MONTHS) + r")\b", text
        )
        if m is None:
            return None
        day, month = int(m.group(1)), _MONTHS[m.group(2)]
    else:
        month, day = _MONTHS[m.group(1)], int(m.group(2))
    # No year given: assume the next occurrence relative to the frozen clock.
    candidate = date(today.year, month, day)
    if candidate < today:
        candidate = date(today.year + 1, month, day)
    return candidate
