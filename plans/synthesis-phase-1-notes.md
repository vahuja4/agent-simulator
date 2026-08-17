# Scenario Synthesis Phase 1 Notes

**Date:** 2026-08-17
**Scope:** Phase 1 only; no enumeration, sampling, realization, or dry-run work.

## Decisions

- The J1 procedure graph is derived from the approved J1 journey definition, not
  from the mock. Its success path is `disclose → select_card → fetch_options →
  validate → confirm → submit → terminate`; it also models a card-switch/refetch
  loop, validation retry, and truthful submission-failure termination.
- Edge costs price the conversational worst case rather than tool-call count. The
  normal path costs 10 turns, the card-switch path 13, and the failure path 11, so
  the existing 12/14-turn scenario budgets remain valid and partial disclosure is
  not treated as a zero-cost variation.
- Fixture bindings use only card/account last-fours. Predicates cover non-empty
  bindings, multiple cards, distinguishable card amounts, and the shared
  “Freedom” name that requires last-four disambiguation.
- Policies are a closed, explicit catalog. Each has journey applicability,
  fixture predicates, assertion and/or judge-hook mappings, and declared
  compatibility. No judge wording was changed.
- Both source hashes are recorded in the graph, while each blueprint records the
  graph hash and fixture hash. Validation fails on source or provenance drift.
- Five hand-written YAML blueprints capture the existing J1 semantic shapes:
  full disclosure, partial disclosure, card switch/refetch, last-four
  disambiguation, and truthful submission failure.

## Gate results

- Accepted hand-written J1 blueprints: **5/5**.
- Rejection coverage: bad tool, unsatisfiable binding, unknown orphan policy,
  catalog policy without an enforcement hook, turn overflow, misplaced
  perturbation, disconnected path, and registry drift (**8 invalid classes**).
- Focused tests: **14 passed**.
- Full offline suite: **268 passed, 1 deselected** via
  `.venv/bin/python -m pytest` on Python 3.12.12.
- Live LLM calls: **none**.
- Phase 2: **not started**.
