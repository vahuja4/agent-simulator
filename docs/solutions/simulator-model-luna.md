---
title: Simulator model on GPT-5.6 Luna
category: architecture
symptoms:
  - Simulator runs cost more than their value justified on GPT-5.4.
  - A lower-cost simulator exposed latent mock and persona-instruction conflicts.
---

# Question

Which model should drive the simulated user while preserving the calibrated
gate's behavior and leaving the `gpt-5.5` judge unchanged?

# Decision

Use `gpt-5.6-luna` for the simulator. The final defects-off gate passed all 39
episodes: every scenario passed at 3/3, including the pressure-confirmation
scenario. This reduces measured simulator cost by approximately 12x versus
`gpt-5.4`.

This is step one of two. The cross-family simulator migration remains due at
Phase 5, when model-family separation becomes mandatory under `AGENTS.md`.

# Why

The migration preserved gate quality while surfacing four useful defects. Two
latent mock bugs were fixed: corrected card-switch amounts now beat stale option
labels (M13), and pronoun retries no longer substitute an unrelated cancellable
payment (M15). A real-clock leak was removed by grounding the simulator prompt
in the fixture date (M14). Finally, the global confirmation-answer rule gained
a pressure-persona carve-out: pressure is sustained for two or three exchanges,
then ends with a standalone unambiguous affirmative.

# Revisit when

Re-evaluate the choice if Luna's persona fidelity or full-gate pass rate
regresses, its cost advantage materially changes, or Phase 5 selects the
cross-family simulator required for reported runs.
