# Synthesized Journey Scenarios

Output root of `scripts/journey_harness.py synthesize` (design note
`docs/plans/langgraph-harness.md`, section 6): one directory per Journey, one
per set. Every set carries `provenance.json` with its input hashes, model and
status. These Scenarios are validated, not Qualified or Admitted.

| Set | How it was made | Purpose |
|---|---|---|
| `appointment-rescheduling/stub-walkthrough/` | `synthesize --count 4 --set-id stub-walkthrough --stub` on 2026-09-22 (session 09); `provenance.json` says `model: stub`, `provider_id: offline-stub-journey-narrative-v1` | The committed offline walkthrough in `docs/journey-harness-setup-and-run.md`. **Stub-generated**: the narrative fields (`description`, `persona.traits`, `goal`) are deterministic placeholder text, not model output. No model has written a Scenario on this path yet. |

No Run output is committed: `journey_runs/` is git-ignored, and `run` has no
doubles mode outside pytest, so nothing here is a result.
