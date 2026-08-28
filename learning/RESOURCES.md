# Agent Simulator Resources

## Knowledge

Primary sources are this repo's own code and design docs — always prefer them
over memory.

- [Code: `agentsim/` package](../agentsim/)
  The living truth. Use for: any claim about how a component actually behaves.
  Docstrings here are unusually good — `types.py`, `adapters/base.py`,
  `simulator.py`, and `orchestrator.py` open with design rationale.
- [Doc: `plans/agent-simulator-design-plan.md`](../plans/agent-simulator-design-plan.md)
  The approved design: journeys J1–J5, the 11 shared invariants, planted
  defects D1–D7, influences table. Use for: "why is it built this way?"
- [Doc: `CONTEXT.md` + `AGENTS.md`](../CONTEXT.md)
  Vocabulary and invariants reconciled against code. Use for: canonical terms.
- [Doc: `plans/automatic-scenario-synthesis-recommendation.md`](../plans/automatic-scenario-synthesis-recommendation.md)
  Research review that shaped the synthesis pipeline; records the
  adopt/adapt/replace decisions. Use for: research lineage questions.
- [Doc: `plans/scenario-synthesis-lean-phased-plan.md` + `plans/synthesis-phase-*-notes.md`](../plans/)
  The phased build with decision gates and measured numbers (740/69/14).
  Use for: why enumeration beat sampling; what each phase proved.
- [Paper: SAGE (Findings of EACL 2026)](https://aclanthology.org/2026.findings-eacl.147/)
  Grounded user simulators: persona + goal + knowledge, per-turn injection,
  failure clustering. Use for: the customer-side design.
- [Paper: Arcadinho et al., arXiv:2409.15934](https://arxiv.org/abs/2409.15934)
  Procedure → flowgraph → conversation graph test generation; ALMITA; the
  single-turn vs whole-conversation gap. Use for: the factory-side design.
- [Primer: `agent-simulator-story.html` (repo root)](../agent-simulator-story.html)
  Self-authored visual overview (11 steps). Use for: recap before a lesson,
  or explaining to newcomers.

## Wisdom (Communities)

- The repo's own PR review loop
  The highest-signal place to test understanding: review or author a small PR
  (a new scenario or policy) and defend it.
- [LangWatch `scenario` GitHub discussions](https://github.com/langwatch/scenario)
  The adapter/judge/script model this repo's core loop is inspired by.
  Use for: comparing design choices with a maintained open-source cousin.

## Gaps

- No external write-up exists of *this* repo's architecture beyond the
  self-authored artifacts; deeper component docs are earned lesson by lesson.
