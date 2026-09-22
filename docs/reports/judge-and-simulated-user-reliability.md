# Reliability of the Judge and the Simulated user

Source: web literature research and a read-only pass over this repository, 2026-09-21 and 2026-09-22. No code changed and no live LLM command was run. In the source list, **A** means I opened the page and the claim is there; **B** means a research sub-agent opened it and reported the claim; **C** means a search snippet only.

**The Simulated user.** LLM user simulators do make mistakes often — people found a simulator mistake in 16–47% of tau2-bench conversations, and 6–13% had one that blocked the task [S1] — and which model plays the user moves the agent's score by up to 9 points [S2]. But running a Scenario three times and keeping the conversation that looks truest is the wrong fix. Picking the truest one needs an LLM to score truthfulness, and no such scorer has been checked against human rulings; where similar scorers have been measured they are weak (69% right against 91% for people at telling who is speaking [S5]). How faithful the customer looks also depends on what the agent did — a pushy customer looks pushiest when the agent gives it something to push against — so picking on faithfulness quietly picks on agent behaviour and can move the Pass rate either way [S6, S7]. And it pays for three conversations and reports one, hiding the agent's own run-to-run variation. Instead: run the three as Seeds, keep them all, and report a Pass rate with a margin of error; record the simulator's model, reasoning effort and prompt version in each Episode; tighten its instructions the way tau2-bench did (reveal facts only when asked, never invent, say when the scenario does not cover something) [S14]; and start writing Spot-check records, since there are none and they are the only way to later test any automatic check. If an automatic check is ever added, the supported place is per message — check each draft customer message against the Scenario before it is sent, so the agent runs once and the check never sees how the conversation ends [S3, S12, S13].

**The Judge.** The Judge on this path has never been measured, and the main mistake LLM judges make is leniency: in one study 14 judges passed 96% of good items but failed fewer than a quarter of the bad ones [S15], and on 1,302 expert-labelled agent runs about 30% of failures were marked as successes [S16]. Adding judges does not fix this, because judges make the same mistakes as each other — nine judges from seven families were worth about two independent opinions, the best single judge matched the whole panel, and 26% of bad items were passed by all 14 judges in the study above [S29, S30, S15]. A judge of judges is a third unchecked opinion sharing the first two's blind spots [S32, S33]; debate makes biases worse [S34, S35]; and a model asked to criticise its own ruling with no outside input tends to get worse [S45]. What does help is giving the Judge something to check against (the Trace, which it already gets — the largest measured gain of any design choice [S23]), asking yes/no questions one at a time rather than one overall ruling [S40, S21, S24], and measuring. So: build a set of Episodes a person has ruled on, including failing ones made on purpose by editing saved passing Episodes (delete a confirmation, change a stated amount so it no longer matches the Trace) since real failures are rare and `live-dev-01`'s four Episodes are all passes; for each criterion report separately how often bad Episodes are failed and good ones passed, never plain agreement; run the Judge several times and send any Episode whose ruling flips to a person, as N-007 showed a flip was a wording defect, not noise; and, when a second provider client exists, add one Judge from another family where either "fail" means fail, using disagreements between them as the list of what a person reads next [S29] — remembering that agreement proves nothing and the shared blind spots only show up through the planted failures.

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
