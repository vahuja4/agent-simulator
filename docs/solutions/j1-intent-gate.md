---
title: The J1 mock gates slot extraction on sentence intent
category: mock
symptoms:
  - A question naming an option label was staged as an amount selection (M-019).
  - A correction naming both the old and the new card stayed on the old card (M-018).
  - A garbled confirmation was read as a decline.
---

# Question

How should the deterministic mock handle customer turns that name payment
details but do not choose them — questions, negated mentions, and noisy
input — without an LLM classifier?

# Decision

Rules make the mock act less, never understand more. A J1 message is split
into sentences; card, account, amount, and date extraction runs only on the
sentences that are not questions (ending in `?`, opening with an
interrogative, or embedding one). Question sentences are answered from
fetched state, with each option's fixture-state meaning, and stage nothing.
A card inside a negation window is never a switch target. A message with
noise markers (a token the mock cannot read, or several details in an
unpunctuated burst) is reflected back and applied only once confirmed; at
the confirmation gate it is a REASK.

Two consequences are deliberate:

- The pre-M-019 full-text fallback that let "can you do the minimum?"
  select the minimum is retired. A question is answered, then the customer
  chooses. `test_m5_question_phrased_choice_is_answered_not_staged` pins it.
- `tests/test_mock_intent_corpus.py` replays every recorded customer turn
  against labels produced once by the calibrated judge model
  (`scripts/label_j1_customer_turns.py`, one approved offline call). Its
  `KNOWN_FAILING` set is exact: a fix must remove its turns in the same
  commit, and a regression cannot hide. The eleven turns still listed are
  the nine multi-intent two-payment turns (M-020) and two turns where the
  labeler omitted a statement-balance option that the declarative sentence
  names; those two are label disagreements, not mock defects, and were
  left unedited so the corpus stays independent of the mock's regexes.

# Why

M-018 and M-019 shared one cause: the mock mined every message for details
before deciding what the customer was doing. An LLM classifier is excluded
by invariant, breaks replayability and the defect on/off comparison, and
would need its own calibration. Answering instead of guessing is also the
recovery behavior CONTEXT.md requires for channel noise, so the clean
reference now exhibits it.

# What would make us revisit it

A persona noisy or indirect enough to exhaust the turn budget with
clarifications; a labeled corpus turn that a rule cannot satisfy without
widening a regex until it merely agrees with the label; or a decision to
handle multi-intent turns (M-020), which needs two staged payments and is
outside this gate.
