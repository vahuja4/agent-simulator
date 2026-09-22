# Reliability of the Judge and the Simulated user: research and recommendation

Source: web literature research and a read-only pass over this repository on 2026-09-21. No code changed and no live LLM command was run. Each source in the last section carries a verification level: **A** — I opened the page and the claim is in the abstract or the section named; **B** — a research sub-agent opened it (through a summarising fetch tool) and reported the claim, not re-checked by me; **C** — search snippet only. Numbers from level B and C sources should be re-checked before they are quoted outside this report.

Questions asked: (1) can we run one Scenario three times with different LLM settings and keep the conversation truest to the Scenario; (2) how do we make the LLM Judge reliable — several judges, a judge of judges, and so on.

## Short answers

1. **Do not pick the best of three conversations.** Run the three as three Seeds, keep all three, and report a Pass rate with an interval. Choosing the "truest" one needs a fidelity Judge that has no labelled data yet, conditions the result on something the agent helped produce, and throws away the run-to-run variation a Pass rate exists to show. If Simulated-user fidelity is to be enforced automatically, the supported place is per Turn (check a candidate customer message before it is sent), and only after a fidelity Judge has been measured against Spot-check records.
2. **One Judge measured against human labels beats any number of unmeasured judges.** Panels of LLM judges share their errors, so nine judges carry about two votes of independent information, and their shared error is leniency — passing bad conversations — which voting preserves. The supported multi-judge design is small: at most one second Judge from another model family, combined as a veto (either fail is a fail, which is what fail-closed already means), with disagreement used to choose which Episodes a human reviews. A judge of judges and debate between judges are not supported by the evidence.
3. **The first work is measurement, not architecture.** This path has zero Spot-check records, an uncalibrated `JourneyJudge`, one Episode per Scenario, no Pass rate and no interval anywhere. Every design above needs labelled Episodes to know whether it helped.

## Where unreliability enters this harness

A Verdict depends on two LLM instruments. The repository's current state for each:

| Instrument | What exists | What is missing |
|---|---|---|
| Judge (`agentsim/journey/judge.py`) | One call to `gpt-5.5` ruling on all of the Scenario's Judge criteria at once; `_fail_closed`; Assertions gate it and the Expected-outcome gate is deterministic | Any measurement of accuracy. The module says so: "The criteria are new and uncalibrated". No repeat calls, no second Judge, no confidence |
| Simulated user (`agentsim/journey/simulated_user.py`) | Scenario-driven prompt; high Knowledge level customers are shown their rule; Spot-check record schema (`agentsim/journey/spot_check.py`) | Any record: `journey_spot_checks/` does not exist. `episode.json` records only `simulator_model` — not reasoning effort or a prompt hash |
| Reporting | `evaluation.json` per Episode | One Episode per Scenario (`seed=0`), no Pass rate, no confidence interval. Payments calibration reported counts ("13/13", "7 of 7 planted defects"), never an agreement statistic |

Two lessons already in `docs/ledgers/judge-findings.md` bear directly on the ideas proposed:

- **N-007 / N-007-S1.** A Simulated-user compliance criterion passed in repetitions 0 and 2 and failed in repetition 1. Human review found a systematic wording defect, not noise. A majority of three would have returned "pass" and hidden the defect. In this project a flip between repeated rulings has been a finding about the criterion, not something to vote away.
- **N-009 and N-010.** The payments path already had an LLM fidelity Judge (`scenario_synthesis/simulator_compliance.py`). Run without the Scenario's evidence it produced false rejections (N-009), and it still blames the Simulated user for conversations that were cut short for another reason (N-010, open). Any fidelity Judge here needs the Scenario evidence in its prompt and a "not evaluable" ruling for truncated Episodes.

## Question 1 — three conversations, keep the truest

### The problem is real

User simulators in published agent benchmarks err often, and the choice of simulator model moves the agent's measured score.

- tau2-bench annotated conversations run with a `gpt-4.1` user simulator: 40% (retail), 47% (airline) and 16% (telecom) contained a simulator error; 12%, 13% and 6% contained one that prevented task completion. The paper credits telecom's lower rate to the environment constraining the user, not to prompting, and states no protocol for the affected Episodes. [S1, A]
- Agent success on tau-bench retail moved by up to 9 percentage points when only the user LLM changed, and simulated users asked questions and used politeness markers about twice as often as humans. [S2, A for the 9 points, B for the rest]
- Goal-alignment failures of 10–40% across open-weight simulators. [S3, B]
- An agent's measured task score fell from 74.6% to 57.4% when it faced a trained user model instead of a prompted `gpt-4o` user. [S4, B]

### Why best-of-three is the wrong remedy

1. **The selector is a fidelity Judge, and it is unmeasured.** This is the check rejected on 2026-09-21 for having no labelled data (design note §12 item 3). LLM judges of role-play are weak where measured: 68.8% against 90.8% for humans at telling which character is speaking [S5, B]; 85.7% agreement with humans on goal-state tracking overall but 72.7% on behaviour-rule items [S3, B] — and Persona and Complication are behaviour rules.
2. **Selecting on fidelity conditions on something the agent co-produced.** A Pressure Persona or Vigilant Persona shows its character most when the agent gives it something to push against. Fidelity scored on the finished transcript is therefore correlated with how the agent behaved. Dropping or choosing observations on a post-treatment variable can bias the estimate in either direction, without bound [S6, B]; a study of controllable user simulation names the same effect "look-ahead bias" [S7, B].
3. **Best-of-N against an imperfect scorer over-optimises the scorer.** The true quality first rises and then falls as selection pressure grows [S8, S9, B]. The one direct test found of whole-conversation rejection sampling for user simulation reached a persona match of 0.34 at N=512 and about 1,800 model calls per conversation [S7, B].
4. **The three conversations are not comparable candidates.** The agent is stochastic too, so "best Simulated user" is confounded with "which agent run". If the three differ in Simulated-user model, the model effect alone is worth up to 9 points [S2].
5. **"Different LLM settings" is narrower here than it sounds.** `agentsim/llm.py` exposes model and reasoning effort only; the `gpt-5` family does not accept temperature [S10, B]. Identical settings already vary run to run: up to 15% accuracy spread across nominally deterministic runs [S11, B]. Variation does not need to be manufactured.
6. **It costs three conversations with the agent and reports one**, hiding the agent's own run-to-run variation — the thing a Pass rate over Seeds exists to expose.

### What to do with three conversations instead

| Option | Assessment |
|---|---|
| **Three Seeds, all kept, Pass rate reported** | Recommended now. Same cost as best-of-three, no selector needed, and it is what `CONTEXT.md` already defines as the reported unit. Hold the Simulated-user configuration fixed across everything being compared |
| **Filter unfaithful Episodes, report the count** | Safer than choosing a best one, because it applies a fixed threshold instead of a ranking. Still post-treatment conditioning, so report the Pass rate with and without the dropped Episodes, the drop count per Persona archetype and Complication, and the drop rate split by agent pass and fail. Needs a measured fidelity Judge first. Payments precedent was stricter still: a non-compliant Episode rejected the whole Candidate |
| **Per-Turn check of the candidate customer message** | Best supported in the literature: DuetSim's verifier [S12, B], tau-bench's `verify` and `reflection` user strategies [S13, B], goal-state tracking fed back each Turn (+5.4% success without training) [S3, B]. Candidates share the same conversation so far, the check never sees the outcome, and the agent is run once. Still an LLM check, so it also needs measuring first |
| **Best of three whole conversations** | Not recommended, for the six reasons above |

Cheaper fidelity gains that need no selector: tau2-bench's user guidelines ("Disclose information progressively. Wait for the agent to ask", never invent information, and an explicit out-of-scope stop signal) [S14, B]; and tau2's observation that environment constraints did more than prompting. Any instruction change must first be checked for conflicts with existing Personas (`AGENTS.md`).

## Question 2 — making the Judge reliable

### One Judge first: measure it

- **The dominant documented error is leniency.** Across 14 judges, true positive rate was 96% and true negative rate below 25%: they passed almost everything [S15, A]. No judge of 12 exceeded 70% precision on 1,302 expert-labelled web-agent trajectories, so about 30% of failed runs were marked successful; a common cause was believing the agent's own claim of success [S16, B]. A production judge for an ordering agent surfaced 2 of 9 human-confirmed defect patterns and missed confirmation-gate and stale-state defects because its rubric had no category for them [S17, B]. `_fail_closed` does nothing about this: it handles a missing or malformed ruling, not a confident wrong "pass".
- **Report the two error rates separately, never raw agreement.** On imbalanced data a judge that always passes scores high agreement [S18, B]. Use the rate of correctly failed bad Episodes and correctly passed good Episodes per criterion, with Cohen's kappa, and the agreement between two human reviewers as the ceiling [S19, S20, B].
- **How many labels.** Practitioner guidance is about 100 labelled examples per failure mode with both classes present [S18, B]. My arithmetic (normal approximation): a rate near 0.8 measured on 50 labelled Episodes of one class has a 95% interval of about ±11 points, ±8 on 100, ±5.5 on 200. Failing Episodes are rare, so they must be seeded — the payments path did this with planted defects D1–D7.
- **Design choices with evidence.** Binary verdicts are far more stable under paraphrase than graded scales [S21, B]. Clear criteria matter more than chain-of-thought, whose gains are small once criteria are clear [S22, B]. Giving the judge ground truth to check against is the largest measured effect (failures 70% → 15% on one task) [S23, B]; `JourneyJudge` already does this by supplying the Trace. LLM evaluators confuse criteria with one another [S24, B], which is indirect evidence against ruling on all criteria in one call, as `GeneralJudge` does; no clean comparison of one call per criterion against a batched call was found.
- **The prompt and model are the instrument.** Re-measure on any change to either [S18, B]. This matches the repository's calibration-lock rule.

### Repeating the same Judge

Rulings do flip: 13.6% average flip rate on pairwise verdicts [S25, B]; agreement across runs of 0.33–0.79 (Krippendorff's alpha) on a binary task [S26, B]; temperature 0 does not give determinism [S11, S27, B]. But a majority of three raised balanced accuracy only from 79.4 to 80.6 [S26], stability says nothing about validity (test-retest above 0.95 coexisted with severe bias) [S20, B], and voting cannot correct a lean in one direction [S15]. Combined with N-007: run the Judge k times to **measure** the flip rate per criterion, treat a flipping Episode as a finding for human review, and under fail-closed combine as "any fail in k", never as a majority.

### Several judges

- A panel of three small judges from different families beat GPT-4 as a single judge on question-answering tasks (kappa 0.763 vs 0.627 on Natural Questions), but the paper has no comparison of different families against repeated samples of one model [S28, B].
- A larger 2026 study: nine judges from seven families carry "about 2 independent votes' worth of information"; the best single judge "matches or outperforms the full panel across all conditions" [S29, A]. From its body [B]: cross-family pairs were among the most correlated, when all nine agreed 9.1% of those items were still wrong, and accuracy-weighted voting and Dawid-Skene added almost nothing over majority vote.
- Errors are correlated across providers — when two models both err they agree 60% of the time — and more so for more accurate models [S30, S31, B].
- Majority vote caught 19.2% of bad outputs with 14 lenient judges; a minority veto caught 30.9% while keeping a 95.5% true positive rate; 26% of bad items were passed by all 14. A regression calibrated on a small human-labelled set cut maximum error to 1.2%, twice as good as the best ensemble [S15; A for the 1.2%, B for the rest].

Reading for a fail-closed Judge: a unanimous-pass rule across two judges is the veto the evidence favours. It can only lower false passes and raise false fails, its benefit is capped by the errors both judges share, and both effects must be measured on labelled Episodes. Beyond two or three judges there is almost nothing left to gain.

### A judge of judges, and debate

- Meta-judge results that look positive depend on human-written rubrics or use the meta-judge as a training signal, not as a validated evaluator [S32, S33, B]. No paper was found showing an unvalidated meta-judge improving binary pass/fail accuracy against human labels on transcripts.
- Debate amplifies position, verbosity and bandwagon bias after the first round [S34, B], and five debate frameworks failed to beat simple baselines consistently, mostly losing to resampling one model at higher cost [S35, B].

A judge of judges is a third unmeasured opinion correlated with the first two. The adjudicator the evidence supports for disagreements is a human.

### Disagreement as a routing signal, and honest reporting

- Panel disagreement predicts error weakly but usefully: 63.1% accuracy on items with any disagreement against 90.9% on unanimous ones [S29, B]. Use it to choose Episodes for human review; never read agreement as certification.
- Selective evaluation with a provable human-agreement guarantee exists, but needs about 500 human labels and guarantees agreement among accepted rulings, not recall of defects [S36, B]. A later goal.
- A Pass rate can be corrected for known Judge error using its two measured error rates, with an interval that includes the uncertainty of the human-labelled set [S37, A]. The correction becomes unstable when the Judge is weak or the labelled set tiny, and calibration should not be shared across the systems being compared [S38, B]. Report standard errors in any case [S39, B].

## Staged recommendation for this repository

**Stage 0 — record and repeat (no new LLM role).**
- Record the Simulated user's reasoning effort and a prompt hash in `episode.json` beside `simulator_model`.
- Run N Seeds per Scenario on the Journey-definition path and report a Pass rate with an interval. `spot_check._episode_dir` currently refuses a Scenario with two Episodes in a Run, so Episode identity there must gain the Seed.
- Evaluation is post-hoc on a saved Episode directory, so a set of saved, human-labelled Episodes is a reusable Judge test set costing only Judge calls to replay.

**Stage 1 — build the labelled set.**
- Start `journey_spot_checks/`. Add a sampling rule (which Episodes are reviewed), a second reviewer on a subset, and a separate human label for the Judge's ruling per criterion — Spot-check records cover Simulated-user fidelity only.
- Seed failing Episodes (defect switches in the stand-in agent, or edited copies of saved Episodes) so each criterion has failures to be measured on.

**Stage 2 — measure before adding anything.**
- Per criterion: correct-fail rate, correct-pass rate, kappa, flip rate over k replays. Expect wording findings of the N-007 kind; `JourneyJudge` is uncalibrated, so this is the cheapest moment to change wording or to test one call per criterion. Both are instrument changes needing explicit approval and live verification (`AGENTS.md`).

**Stage 3 — only what Stage 2 justifies.**
- If false passes remain: a second Judge from another family as a veto. `evaluate_episode` accepts any `EpisodeJudge`, so a two-Judge object drops in without touching the rule ladder; `record["judge"]` and `to_run_result().llm_calls` assume one call and would change. Costs: a second provider client (`LLMClient` is provider-neutral; `structured()` is OpenAI-specific), and a Simulated-user family outside **both** Judge families under the model-family separation invariant.
- A fidelity Judge, first as a flag only: a sibling key in `evaluation.json`, outside the Verdict, shown the Scenario evidence, with a "not evaluable" ruling, scored against Spot-check records. This reopens design note §12 item 3 at the point that note itself names — when labelled data exists — and needs explicit approval.
- Only once that Judge is measured: filtering with both Pass rates reported, or per-Turn checking.

**Not recommended at any stage:** best-of-N whole conversations; majority-vote panels; a judge of judges; debate; learned or Dawid-Skene aggregation at this scale.

## Gaps in the evidence

- No study was found comparing a panel with a single judge on multi-turn tool-use transcripts; the multi-judge evidence is from question answering, inference and code feedback.
- No tau-family paper states what to do with an Episode whose simulator erred; they annotate a sample and report the rate.
- No primary evidence was found that requiring quoted evidence improves a judge's agreement with humans, nor a clean comparison of one call per criterion against batched criteria.
- Several central sources are 2026 preprints, one single-author [S29]. Its conclusions agree with two 2025 papers [S30, S31].

## Sources

| Id | Source | Level |
|---|---|---|
| S1 | Barres et al. 2025, "tau2-bench", https://arxiv.org/html/2506.07982v1 | A |
| S2 | Seshadri et al. 2026, "Lost in Simulation: LLM-Simulated Users are Unreliable Proxies for Human Users in Agentic Evaluations", https://arxiv.org/abs/2601.17087 | A (9 points), B (rest) |
| S3 | Mehri et al. 2025, "Goal Alignment in LLM-Based User Simulators for Conversational AI" (UGST), https://arxiv.org/abs/2507.20152 | B |
| S4 | Naous et al. 2025, "UserLM-8b", https://arxiv.org/abs/2510.06552 | B |
| S5 | Zhou et al. 2025, "PersonaEval", https://arxiv.org/abs/2508.10014 | B |
| S6 | Montgomery et al. 2018, "How Conditioning on Posttreatment Variables Can Ruin Your Experiment", AJPS | B |
| S7 | Tennenholtz et al. 2026, "Controllable User Simulation", https://arxiv.org/html/2605.11519 | B |
| S8 | Gao et al. 2022, "Scaling Laws for Reward Model Overoptimization", https://arxiv.org/abs/2210.10760 | B |
| S9 | Khalaf et al. 2025, "Inference-Time Reward Hacking in LLMs", https://arxiv.org/abs/2506.19248 | B |
| S10 | OpenAI latest-model and reasoning guides, https://developers.openai.com/api/docs/guides/reasoning | B |
| S11 | Atil et al. 2024, "Non-Determinism of 'Deterministic' LLM Settings", https://arxiv.org/abs/2408.04667 | B |
| S12 | Luo et al. 2024, "DuetSim", https://arxiv.org/abs/2405.13028 | B |
| S13 | tau-bench user strategies, https://github.com/sierra-research/tau-bench | B |
| S14 | tau2-bench user simulation guidelines (Hugging Face dataset `PICO2/tau2-bench-data`) | B |
| S15 | Jain et al. 2025, "Beyond Consensus: Mitigating the Agreeableness Bias in LLM Judge Evaluations", https://arxiv.org/abs/2510.11822 | A (abstract numbers), B (voting comparison) |
| S16 | Lù et al. 2025, "AgentRewardBench", https://arxiv.org/abs/2504.08942 | B |
| S17 | Zhang et al. 2026, "Catching One in Five", https://arxiv.org/abs/2606.10315 | B |
| S18 | Husain, "Using LLM-as-a-Judge", https://hamel.dev/blog/posts/llm-judge/ | B |
| S19 | Thakur et al. 2024, "Judging the Judges", https://arxiv.org/abs/2406.12624 | B (abstract), C (kappa numbers) |
| S20 | Norman et al. 2026, "Reliability without Validity", https://arxiv.org/abs/2606.19544 | B |
| S21 | Bellibatlu et al. 2026, "JudgeSense", https://arxiv.org/html/2604.23478v2 | B |
| S22 | Yamauchi et al. 2025, https://arxiv.org/abs/2506.13639 | B |
| S23 | Zheng et al. 2023, "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena", https://arxiv.org/abs/2306.05685 | B |
| S24 | Hu et al. 2024, https://arxiv.org/abs/2402.12055 | B |
| S25 | Yagubyan et al. 2026, "The Coin Flip Judge?", https://arxiv.org/abs/2606.13685 | B |
| S26 | Haldar et al. 2025, "Rating Roulette", https://arxiv.org/html/2510.27106 | B |
| S27 | He (Thinking Machines) 2025, "Defeating Nondeterminism in LLM Inference" | B |
| S28 | Verga et al. 2024, "Replacing Judges with Juries" (PoLL), https://arxiv.org/abs/2404.18796 | B |
| S29 | Kohli 2026, "Nine Judges, Two Effective Votes: Correlated Errors Undermine LLM Evaluation Panels", https://arxiv.org/abs/2605.29800 | A (abstract claims), B (body numbers) |
| S30 | Kim et al. 2025, "Correlated Errors in Large Language Models", https://arxiv.org/abs/2506.07962 | B |
| S31 | Goel et al. 2025, "Great Models Think Alike and this Undermines AI Oversight", https://arxiv.org/abs/2502.04313 | B |
| S32 | Wu et al. 2024, "Meta-Rewarding Language Models", https://arxiv.org/abs/2407.19594 | B |
| S33 | Li et al. 2025, "Leveraging LLMs as Meta-Judges", https://arxiv.org/abs/2504.17087 | B |
| S34 | Ma et al. 2025, "Judging with Many Minds", https://arxiv.org/abs/2505.19477 | B |
| S35 | ICLR Blogposts 2025, "Multi-LLM-Agents Debate"; Chen et al. 2025, https://arxiv.org/abs/2510.20963 | B |
| S36 | Jung et al. 2024, "Trust or Escalate", https://arxiv.org/abs/2407.18370 | B |
| S37 | Lee et al. 2025, "How to Correctly Report LLM-as-a-Judge Evaluations", https://arxiv.org/abs/2511.21140 | A (abstract), B (formulae) |
| S38 | Fiedler et al. 2026, https://arxiv.org/html/2605.06939v1 | B |
| S39 | Miller 2024, "Adding Error Bars to Evals", https://arxiv.org/abs/2411.00640 | B |
