# Synthesized Journey Scenarios

Output root of `scripts/journey_harness.py synthesize` (design note
`docs/plans/langgraph-harness.md`, section 6): one directory per Journey, one
per set. Every set carries `provenance.json` with its input hashes, model and
status. These Scenarios are validated, not Qualified or Admitted.

| Set | How it was made | Purpose |
|---|---|---|
| `appointment-rescheduling/stub-walkthrough/` | `synthesize --count 4 --set-id stub-walkthrough --stub` on 2026-09-22 (session 09); `provenance.json` says `model: stub`, `provider_id: offline-stub-journey-narrative-v1` | The committed offline walkthrough in `docs/journey-harness-setup-and-run.md`. **Stub-generated**: the narrative fields (`description`, `persona.traits`, `goal`) are deterministic placeholder text, not model output. |
| `appointment-rescheduling/live-dev-01/` | `synthesize --count 4 --set-id live-dev-01 --model gpt-5.5` on 2026-09-22 (session 10), seed 0; `provenance.json` says `model: gpt-5.5`, `provider_id: openai-structured-journey-narrative:gpt-5.5`; 4 accepted, 0 rejected attempts | **Live-generated** by the model: the first Scenarios a model wrote on this path. The input to the development Run recorded in `docs/reports/live-runs/live-dev-01/` — a development Run, not a result. Validated only; nothing about their quality or coverage is established. |

Run output under `journey_runs/` is git-ignored, and `run` has no doubles mode
outside pytest, so nothing here is a result. The one Run kept for reading is
the development Run copied to `docs/reports/live-runs/live-dev-01/`, labelled
there as not reportable.
