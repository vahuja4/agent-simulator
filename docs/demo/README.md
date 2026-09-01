# Offline evidence demo

This demo replays committed evidence only. It never runs a Scenario, invokes a
provider, regenerates a report, or loads `.env`. Run `./demo preflight` first;
then use one command per step. The exact output of every step is captured in
[`expected/`](expected/).

The evidence is pinned in [`manifest.json`](manifest.json) to commit
`7cffe484e4ca129d490b060729803972560b17a0` and to a SHA-256 for every file.
The latest chronologically committed curated calibration gate is rejected as
landing evidence, so A and B use the latest successful full curated acceptance
gate, `phase4_acceptance_baseline_v2`.

## Step list

- A — `./demo A` — A defects-off curated Scenario links its YAML, Transcript, Trace, and passing two-layer Verdict in the accepted gate.
- B — `./demo B` — The D2 defect-on Run fires two structured Assertions, and the hard gate attributes the failure to the deterministic layer before any Judge call.
- C — `./demo C` — The current report separates covered, BLOCKED, UNCOVERED, and excluded obligations and records a fresh 56-Scenario pairwise-covering target.
- D — `./demo D` — Hashes link the low-Knowledge Blueprint to its Candidate, three passing Episodes and Judge rulings, detection-unproven Admission, and byte-identical library Scenario.
- E — `./demo E` — The ordinal-0 Candidate rejection is preserved, then append-only evidence reattributes it to a Judge criterion-scope harness fault.
- F — `./demo F` — The current committed fail-closed completion check sees the Rejection ledger and ordinal-1 Admission and names the remaining roadmap.

Use `./demo all` to replay A–F in order. Step F prints the committed output; it
does not run `scenario_synthesis check-completion`, because that command writes
a new report and would violate the committed-artifacts-only boundary.
