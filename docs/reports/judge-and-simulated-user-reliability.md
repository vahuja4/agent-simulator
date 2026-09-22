# Reliability of the Judge and the Simulated user: research and recommendation

Source: web literature research and a read-only pass over this repository on 2026-09-21; the "Sequential calls" section was added on 2026-09-22. No code changed and no live LLM command was run. Each source in the last section carries a verification level: **A** — I opened the page and the claim is in the abstract or the section named; **B** — a research sub-agent opened it (through a summarising fetch tool) and reported the claim, not re-checked by me; **C** — search snippet only. Numbers from level B and C sources should be re-checked before they are quoted outside this report.

Questions asked: (1) can we run one Scenario three times with different LLM settings and keep the conversation that is truest to the Scenario; (2) how do we make the LLM Judge reliable — several judges, a judge of judges, and so on.

A note on terms used throughout:

- **Labelled Episode** — a saved Episode that a person has read and ruled on, so that a machine's ruling can be checked against it.
- **False pass** — the Judge says "pass" for a conversation a person would fail. **False fail** — the reverse.
- **Fidelity Judge** — an LLM asked whether the Simulated user played its Scenario. None exists on this path.

## Short answers

1. **Do not pick the best of three conversations.** Run the three as three Seeds, keep all three, and report a Pass rate with a margin of error. Choosing the "truest" one needs a fidelity Judge that has never been checked against human rulings; it makes the result depend on how the agent behaved; and it throws away the run-to-run variation that a Pass rate exists to show. If the Simulated user's fidelity is ever to be enforced automatically, the supported place is one Turn at a time (check a draft customer message before it is sent), and only after a fidelity Judge has been checked against Spot-check records.
2. **One Judge that has been checked against human rulings beats any number of unchecked judges.** LLM judges make the same mistakes as each other, so nine judges are worth about two independent opinions. Their shared mistake is being too lenient — passing bad conversations — and voting keeps that mistake. The only multi-judge design the evidence supports is small: at most one second Judge from another model family, where either one saying "fail" means fail, and disagreement between the two decides which Episodes a person reviews. A judge of judges, and debate between judges, are not supported.
3. **The first job is measuring, not building.** This path has no Spot-check records, a Judge whose accuracy has never been measured, one Episode per Scenario, no Pass rate and no margin of error anywhere. Every design above needs labelled Episodes before anyone can tell whether it helped.

## Where unreliability enters this harness

A Verdict depends on two LLMs. What exists for each today:

| Part | What exists | What is missing |
|---|---|---|
| Judge (`agentsim/journey/judge.py`) | One call to `gpt-5.5` that rules on all of the Scenario's Judge criteria at once; an unclear or missing ruling counts as a fail; Assertions run first and the Expected-outcome check is code, not an LLM | Any measurement of how often it is right. The module says so: "The criteria are new and uncalibrated". No repeat calls, no second Judge, no confidence score |
| Simulated user (`agentsim/journey/simulated_user.py`) | A prompt built from the Scenario; high Knowledge level customers are shown their rule; a schema for Spot-check records (`agentsim/journey/spot_check.py`) | Any record: `journey_spot_checks/` does not exist. `episode.json` records only the model name — not the reasoning effort or which prompt version was used |
| Reporting | `evaluation.json` per Episode | One Episode per Scenario (`seed=0`), no Pass rate, no margin of error. The payments calibration reported counts ("13/13", "7 of 7 planted defects"), never how well the Judge agreed with a person |

Two lessons already in `docs/ledgers/judge-findings.md` bear directly on the ideas proposed:

- **N-007 / N-007-S1.** A check on the Simulated user passed in runs 0 and 2 and failed in run 1. A person reviewed it and found the criterion's wording was wrong — this was not random noise. Taking the majority of three would have returned "pass" and hidden the wording problem. In this project, a ruling that flips between repeated runs has been a finding about the criterion, not something to vote away.
- **N-009 and N-010.** The payments path already had an LLM fidelity Judge (`scenario_synthesis/simulator_compliance.py`). When it was not shown the Scenario's facts it rejected good conversations (N-009), and it still blames the Simulated user for conversations that were cut short for some other reason (N-010, open). Any fidelity Judge here needs the Scenario's facts in its prompt and a "cannot tell" ruling for conversations that ended early.

## Question 1 — three conversations, keep the truest

### The problem is real

In published agent benchmarks, LLM user simulators make mistakes often, and which model plays the user changes the agent's score.

- tau2-bench had people read conversations run with a `gpt-4.1` user simulator. 40% (retail), 47% (airline) and 16% (telecom) contained a simulator mistake; 12%, 13% and 6% contained one that stopped the task from being completed. The authors credit telecom's lower rate to the environment limiting what the user could do, not to better prompting, and they say nothing about what to do with the affected conversations. [S1, A]
- Agent success on tau-bench retail moved by up to 9 percentage points when only the user model changed. Simulated users asked questions and used polite phrases about twice as often as real people. [S2, A for the 9 points, B for the rest]
- Between 10% and 40% of conversations drifted from the user's goal, depending on which open-weight model played the user. [S3, B]
- An agent's score fell from 74.6% to 57.4% when it faced a purpose-trained user model instead of a prompted `gpt-4o` user. [S4, B]

### Why best-of-three is the wrong remedy

1. **Picking the truest conversation needs a fidelity Judge, and none has been checked.** This is the check that was rejected on 2026-09-21 for having nothing to check it against (design note §12 item 3). Where LLM judges of role-play have been measured, they are weak: 68.8% right against 90.8% for people at telling which character is speaking [S5, B]; 85.7% agreement with people on whether a simulated user is following its goal, but only 72.7% on rules about how the user should behave [S3, B] — and Persona and Complication are rules about behaviour.
2. **How faithful the user looks depends on what the agent did.** A Pressure Persona or Vigilant Persona shows its character most when the agent gives it something to push against. So a fidelity score taken from the finished transcript is tangled up with how the agent behaved. Choosing or dropping conversations on something the agent helped produce can push the Pass rate up or down by any amount [S6, B]; a study of user simulation calls this "look-ahead bias" [S7, B].
3. **Picking the best of N against an imperfect scorer ends up gaming the scorer.** True quality first rises and then falls as you select harder [S8, S9, B]. The one direct test found of picking whole conversations this way reached a persona match of only 0.34 even at N=512, at about 1,800 model calls per conversation [S7, B].
4. **The three conversations are not comparable.** The agent varies from run to run too, so "the best Simulated user" cannot be told apart from "the luckiest agent run". If the three runs also use different user models, that alone is worth up to 9 points [S2].
5. **"Different LLM settings" means less here than it sounds.** `agentsim/llm.py` lets a caller change only the model and the reasoning effort; the `gpt-5` family does not accept a temperature setting [S10, B]. And identical settings already produce different runs: up to 15% spread in accuracy across runs that were supposed to be identical [S11, B]. Variation does not need to be manufactured.
6. **It costs three conversations with the agent and reports one**, hiding the agent's own run-to-run variation — the thing a Pass rate over Seeds exists to show.

### What to do with three conversations instead

| Option | Assessment |
|---|---|
| **Three Seeds, all kept, Pass rate reported** | Recommended now. Same cost as best-of-three, no selector needed, and it is what `CONTEXT.md` already defines as the reported unit. Keep the Simulated user's settings the same across everything being compared |
| **Drop unfaithful Episodes, report how many** | Safer than choosing a best one, because it applies a fixed bar instead of a ranking. It still depends on what the agent did, so report the Pass rate with and without the dropped Episodes, the number dropped per Persona archetype and Complication, and whether more are dropped among agent passes or agent fails. Needs a checked fidelity Judge first. The payments path was stricter: one unfaithful Episode rejected the whole Candidate |
| **Check each draft customer message before sending it** | Best supported in the literature: DuetSim's verifier [S12, B], tau-bench's `verify` and `reflection` user strategies [S13, B], and tracking the user's goal state and feeding it back before each Turn (+5.4% success without any training) [S3, B]. Every draft shares the same conversation so far, the check never sees how the Episode ends, and the agent runs once. Still an LLM check, so it also needs to be measured first |
| **Best of three whole conversations** | Not recommended, for the six reasons above |

Cheaper ways to improve fidelity that need no selector: tau2-bench's user guidelines ("Disclose information progressively. Wait for the agent to ask", never invent information, and a clear way to say "the scenario does not cover this") [S14, B]; and tau2's observation that limiting the environment did more than prompting. Any change to the Simulated user's instructions must first be checked for conflicts with existing Personas (`AGENTS.md`).

## Question 2 — making the Judge reliable

### One Judge first: measure it

- **The main documented mistake is leniency.** Across 14 judges, 96% of good items were passed but fewer than 25% of bad items were failed: the judges passed almost everything [S15, A]. On 1,302 expert-labelled web-agent runs, no judge of 12 got more than 70% of its "pass" rulings right, so about 30% of failed runs were marked successful; a common cause was believing the agent's own claim that it had succeeded [S16, B]. A judge in production for an ordering agent found 2 of 9 defect patterns that people had confirmed, and missed confirmation and stale-state defects because its rubric had no category for them [S17, B]. Fail-closed parsing does nothing about this: it handles a missing or garbled ruling, not a confident wrong "pass".
- **Report the two mistake rates separately; never report plain agreement.** When most conversations are good, a judge that passes everything agrees with people most of the time and looks accurate [S18, B]. For each criterion, report how often bad Episodes were correctly failed and how often good Episodes were correctly passed, together with an agreement score that discounts chance (Cohen's kappa), and use the agreement between two human reviewers as the ceiling [S19, S20, B].
- **How many labelled Episodes.** Practitioner guidance is about 100 per failure type, with both good and bad examples [S18, B]. My arithmetic: a rate near 80% measured on 50 labelled Episodes of one kind has a margin of error of about ±11 points; ±8 on 100; ±5.5 on 200. Failing Episodes are rare, so they must be created on purpose — the payments path did this with planted defects D1–D7.
- **Design choices with evidence.** Yes/no rulings are far more stable under rewording of the prompt than 1–5 scores [S21, B]. Clear criteria matter more than asking the judge to think step by step, which adds little once the criteria are clear [S22, B]. Giving the judge the facts to check against has the largest measured effect of any design choice (judge failures 70% → 15% on one task) [S23, B]; `JourneyJudge` already does this by supplying the Trace. LLM judges mix up criteria with one another [S24, B], which is indirect evidence against ruling on all criteria in one call, as `GeneralJudge` does; no clean comparison of one call per criterion against one call for all was found.
- **The prompt and the model are the measuring instrument.** Re-measure after any change to either [S18, B]. This matches the repository's calibration-lock rule.

### Repeating the same Judge

Rulings do flip between runs: 13.6% of the time on average in one study [S25, B]; run-to-run agreement of 0.33–0.79 (on a 0–1 scale) on a yes/no task [S26, B]; and temperature 0 does not make runs identical [S11, S27, B]. But taking the majority of three runs raised accuracy only from 79.4% to 80.6% [S26]; a judge can be perfectly consistent and consistently wrong (one study found run-to-run agreement above 0.95 alongside severe bias) [S20, B]; and voting cannot fix a lean in one direction [S15]. Together with N-007: run the Judge several times to **measure** how often each criterion flips, send any Episode that flips to a person, and when combining runs count any "fail" as a fail — never take a majority.

### Several judges

- A panel of three small judges from different families beat GPT-4 as a single judge on question-answering (agreement with people 0.763 against 0.627 on one dataset), but the paper never tested whether the gain came from using different families or just from having more opinions [S28, B].
- A larger 2026 study: nine judges from seven families carry "about 2 independent votes' worth of information", and the best single judge "matches or outperforms the full panel across all conditions" [S29, A]. From its body [B]: judges from different families were among the most alike in their mistakes; when all nine agreed, 9.1% of those rulings were still wrong; and cleverer ways of combining votes added almost nothing over a plain majority.
- When two models both get something wrong, they give the same wrong answer 60% of the time, and the more accurate the models, the more alike their mistakes [S30, S31, B].
- With 14 lenient judges, a majority vote caught 19.2% of bad outputs; letting a minority veto (a few "fail" votes fail the item) caught 30.9% while still passing 95.5% of good ones; 26% of bad items were passed by all 14. A simple statistical adjustment fitted on a small set of human-labelled items cut the largest error to 1.2%, twice as good as the best panel [S15; A for the 1.2%, B for the rest].

What this means for a fail-closed Judge: with two judges, "both must pass" is the veto the evidence favours. It can only reduce false passes and increase false fails; its benefit is capped by the mistakes both judges share; and both effects must be measured on labelled Episodes. Beyond two or three judges there is almost nothing left to gain.

### A judge of judges, and debate

- The positive results for a judge that reviews other judges depend on rubrics written by people, or use the reviewing judge to train a model rather than to grade one [S32, S33, B]. No paper was found in which an unchecked judge of judges improved pass/fail accuracy against human rulings on transcripts.
- Having judges debate makes their biases worse after the first round [S34, B], and five debate methods failed to beat simple single-judge baselines consistently, mostly losing to running one judge several times, at higher cost [S35, B].

A judge of judges is a third unchecked opinion that shares the first two's mistakes. The evidence supports one referee for disagreements: a person.

### Using disagreement, and reporting honestly

- When judges disagree, they are more often wrong: 63.1% accuracy on items with any disagreement against 90.9% when all agreed [S29, B]. Use disagreement to choose which Episodes a person reviews; never read agreement as proof.
- Methods exist that let a judge say "not sure" and give a guarantee on the accuracy of the rulings it does make, but they need about 500 human-labelled items and the guarantee covers accepted rulings, not how many defects are caught [S36, B]. A later goal.
- A Pass rate can be adjusted for the Judge's known mistake rates, with a margin of error that includes the uncertainty from the small labelled set [S37, A]. The adjustment misbehaves when the Judge is weak or the labelled set tiny, and each system under test needs its own labelled set [S38, B]. Report a margin of error in any case [S39, B].

## Staged recommendation for this repository

**Stage 0 — record and repeat (no new LLM role).**
- Record the Simulated user's reasoning effort and a hash of its prompt in `episode.json` beside `simulator_model`.
- Run N Seeds per Scenario on the Journey-definition path and report a Pass rate with a margin of error. `spot_check._episode_dir` currently refuses a Scenario with two Episodes in a Run, so an Episode's identity there must include the Seed.
- Evaluation runs on a saved Episode directory after the fact, so a set of saved, human-labelled Episodes is a reusable Judge test set that costs only Judge calls to replay.

**Stage 1 — build the labelled set.**
- Start `journey_spot_checks/`. Add a rule for which Episodes get reviewed, a second reviewer on some of them, and a separate human ruling on each of the Judge's criteria — Spot-check records cover only the Simulated user.
- Create failing Episodes on purpose (defect switches in the stand-in agent, or edited copies of saved Episodes) so that every criterion has failures to be measured on.

**Stage 2 — measure before adding anything.**
- Per criterion: how often bad Episodes are failed, how often good ones are passed, chance-corrected agreement, and how often the ruling flips over repeated runs. Expect wording problems of the N-007 kind; `JourneyJudge` has never been calibrated, so this is the cheapest moment to change wording or to try one call per criterion. Both change the instrument and need explicit approval and live verification (`AGENTS.md`).

**Stage 3 — only what Stage 2 justifies.**
- If false passes remain: a second Judge from another family, both must pass. `evaluate_episode` accepts any `EpisodeJudge`, so a two-Judge object drops in without touching the rule ladder; `record["judge"]` and `to_run_result().llm_calls` assume one call and would change. Costs: a second provider client (`LLMClient` is provider-neutral; `structured()` is OpenAI-specific), and a Simulated-user model outside **both** Judge families under the model-family separation rule.
- A fidelity Judge, first as a flag only: a separate key in `evaluation.json`, outside the Verdict, shown the Scenario's facts, able to rule "cannot tell", and scored against Spot-check records. This reopens design note §12 item 3 at the point that note itself names — when labelled data exists — and needs explicit approval.
- Only once that Judge is measured: dropping unfaithful Episodes with both Pass rates reported, or checking each draft message.

**Not recommended at any stage:** best of N whole conversations; majority-vote panels; a judge of judges; debate; statistical vote-weighting schemes at this scale.

## Sequential calls

Added 2026-09-22 in answer to: has anyone used a chain of calls, one after another, to improve the judgement or the generation? Yes, for both. The results split on one condition: **whether the later call is given something the earlier call did not have** — a reference to check against, a tool result, or a structured intermediate result. Where it is, chaining helps; where the later call only re-reads the earlier call's output, chaining does nothing or makes things worse.

### What works

- **Break the question down, then rule.** First generate a checklist or a plan, then answer each item, then combine. TICK raised exact agreement with human preferences from 46.4% to 52.2% by generating a per-task yes/no checklist before judging; its generation variant STICK gained +7.8% on one reasoning benchmark [S40, A]. EvalPlanner (plan → carry out the plan → verdict) reached 93.9 on RewardBench, but that gain came from training the judge on the plan structure, not from prompting alone [S41, A]. Separate yes/no questions beat one overall score in "Ask, Don't Judge" [S42, B] and CheckEval [S43, C].
- **List the claims, then check each one against a reference.** FActScore and SAFE split a long answer into single claims and check each separately, with a lookup step between [S44, C]. This is the pattern closest to the say/do criterion: one call lists what the assistant claimed, and a second call (or plain code) checks each claim against the Trace.
- **Draft, check against the Scenario, redraft** — the per-message check in the Question 1 table (DuetSim [S12], tau-bench `verify`/`reflection` [S13], goal-state tracking fed back each Turn [S3]). The check looks at the Scenario's facts and what has been disclosed so far, which the drafting call was not attending to.
- **Cheap judge first, expensive judge only when needed.** Trust or Escalate routes each item by confidence [S36]; see "Using disagreement" above.

### What does not

- **Asking a model to criticise and fix its own answer with no outside input.** "LLMs struggle to self-correct their responses without external feedback, and at times, their performance even degrades after self-correction" [S45, A]. A survey of self-correction reaches the same conclusion: it helps only with reliable outside feedback or when the task can be checked [S46, C]. Self-Refine reported gains on tasks with a clear objective; the reasoning-task replications did not hold [S47, C].
- **A second call that re-reads the first call's verdict** is the judge of judges from Question 2 in chained form: the same failure, with nothing new in the second call.
- **Chaining is not automatically better than running in parallel.** The best mix of sequential revision and parallel sampling depends on the problem, and choosing per problem beats best-of-N by "more than 4x" in efficiency [S48, A for the 4x; the finding that revision suits easier problems and parallel search harder ones is from the body, B].

### For this harness

The repository already has one chain of the good kind: Assertions run on the Normalized Trace first, and the Judge is called only if they pass. Two chained designs join the Stage 2/3 candidates:

1. **List claims → check each against the Trace** for say/do consistency. Call 1 lists what the assistant told the customer it looked up, offered, confirmed or changed; call 2, or plain code where a claim maps to a tool call, checks each against the Trace. The listing call is cheap to label by hand, so it can be measured on its own.
2. **One call per criterion** instead of `GeneralJudge`'s one call for all criteria. The evidence on breaking questions down [S40, S42, S24] points this way; no clean side-by-side test exists (see Gaps). This changes the instrument under `AGENTS.md`: it needs approval and live verification, but it is the cheapest chained change available.

For the Simulated user, the chained design is the per-message check already recommended: a call that tracks state (which facts have been disclosed, whether the Complication has happened yet) before drafting the next message, then a check against the Scenario before sending. Both steps compare against a reference, which is what separates them from a model criticising itself.

Not to add: a critic pass over the Judge's reasoning, or a "reflect and revise" loop on the customer's message with no state or Scenario to check against. Those are the self-correction pattern the evidence says makes things worse.

## Gaps in the evidence

- No study was found comparing a panel with a single judge on multi-turn conversations with tool calls; the multi-judge evidence comes from question answering, inference and code feedback.
- No tau-family paper says what to do with a conversation in which the simulator made a mistake; they read a sample and report the rate.
- No primary evidence was found that requiring the judge to quote evidence improves its agreement with people, nor a clean comparison of one call per criterion against one call for all.
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
| S40 | Cook et al. 2024, "TICKing All the Boxes: Generated Checklists Improve LLM Evaluation and Generation", https://arxiv.org/abs/2410.03608 | A |
| S41 | Saha et al. 2025, "Learning to Plan & Reason for Evaluation with Thinking-LLM-as-a-Judge" (EvalPlanner), ICML 2025, https://arxiv.org/abs/2501.18099 | A |
| S42 | Cho et al. 2026, "Ask, Don't Judge", https://arxiv.org/html/2606.27226v1 | B |
| S43 | Lee et al. 2024, "CheckEval" | C |
| S44 | Min et al. 2023, "FActScore"; Wei et al. 2024, "Long-form factuality in large language models" (SAFE) | C |
| S45 | Huang et al. 2023, "Large Language Models Cannot Self-Correct Reasoning Yet", https://arxiv.org/abs/2310.01798 | A |
| S46 | Kamoi et al. 2024, "When Can LLMs Actually Correct Their Own Mistakes? A Critical Survey of Self-Correction of LLMs" | C |
| S47 | Madaan et al. 2023, "Self-Refine" | C |
| S48 | Snell et al. 2024, "Scaling LLM Test-Time Compute Optimally can be More Effective than Scaling Model Parameters", https://arxiv.org/abs/2408.03314 | A (4x), B (difficulty split) |
