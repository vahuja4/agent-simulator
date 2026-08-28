# Teaching notes

## User preferences (observed so far)

- Workspace lives in `./learning/` (user's explicit request) — never scatter
  teaching files into the repo root.
- Strong preference for **visual-first explanations**: big diagrams, few words,
  one concrete example per visual. (Established across five HTML artifacts
  built together before this course started.)
- Wants examples grounded in the *real* repo — real card numbers from fixtures
  (…0767, …4421, …9013), real file paths, real scenario names — not invented
  toys.
- Asks sharp follow-up questions and notices inconsistencies (caught a
  "4 vs 6 curveballs" display bug; questioned scenario-generation independence;
  asked for provenance traces). Don't hand-wave; keep claims verifiable.
- Prior exposure: has already absorbed visual overviews of the SAGE persona
  recipe, the scenario factory, curveballs, and the ALMITA lineage. Lessons
  should go *deeper* than those overviews, not repeat them.

## Working notes

- Existing self-authored primers (published artifacts + `agent-simulator-story.html`
  in repo root) can serve as pre-reading / recap, freeing lessons to focus on
  code-level components.
- Candidate core components for the syllabus: types/messages, adapters
  (MockPayCardAgent, HTTP), UserSimulator, orchestrator loop, Scenario schema,
  GeneralJudge, assertions engine, scripting DSL, clustering/report,
  scenario_synthesis pipeline, fixtures, registry.
- Mission not yet captured — interview pending.
