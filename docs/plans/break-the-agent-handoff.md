# Break the agent — handoff for a fresh session

Written 2026-09-25 at the end of the planning session. Read this, then
`docs/plans/break-the-agent.md` (the plan) and
`docs/reports/break-the-agent-plan-review.md` (a review of it). Nothing has
been built yet.

Work in `/Users/vishal/Desktop/agent_simulator-langgraph`, branch
`codex/langgraph-synthesis-harness`. Read `AGENTS.md` and `CONTEXT.md` and
follow them. Never touch `main` or `/Users/vishal/Desktop/agent_simulator`.

**A note on language.** The plan and this file are written in plain English on
purpose — that is a deliberate exception, recorded in the plan, to the rule in
`AGENTS.md` about using `CONTEXT.md`'s vocabulary in prose. Don't translate
them back. Anything you write *into the repo proper* — `CONTEXT.md`, ADR 0008,
the design note, code, commit messages — uses the house vocabulary as normal.

## Where things stand

- Offline tests: **931 passing**, confirmed 2026-09-24. `ENVIRONMENT.md` holds
  that number and `make test` fails on any drift. Run it before you change
  code, and never edit a tracked file while it is running — the tests read
  them mid-run.
- The plan is committed. The review is committed. **No code has been written.**
- The four conversations the plan refers to are in
  `docs/reports/live-runs/live-dev-01/`, from a development run on 2026-09-22.
  Same model family on both sides, so nothing in there is reportable. The
  scenarios that produced them are in
  `synthesized_journey_scenarios/appointment-rescheduling/live-dev-01/`.

## Decisions already made — don't reopen these

- **The probe may pile on difficulties.** Ambiguity and impatience and a
  garbled message in one conversation is fine. The one-difficulty-per-scenario
  rule serves the measuring mode's coverage counts; the probe counts nothing.
  Fairness is the plan's three conditions, not the taxonomy. (User's call,
  2026-09-25.)
- **But** the probe never edits a committed scenario file — it takes its
  variant as its own input or an overlay — and the easy-going customer stays
  easy-going, because she is the control.
- **Nothing is confirmed by a machine.** Even a failed code check needs a
  person to rule out that our own customer caused it. The difference from a
  judge claim is a glance versus a full read, not whether the check is needed.
- **The ending never implies a verdict.** Why the conversation stopped is
  metadata. Findings come only from evaluating the saved evidence afterwards.

## The one open question — ask before writing ADR 0008

Step 4 of the loop has the customer check her own draft and mark it if it
fails. The decision recorded in
`docs/solutions/journey-simulated-user-fidelity-is-a-human-record.md` rejected
exactly that mechanism on 2026-09-21 — a self-report field, deviation flags —
because it is the same model grading itself and a quiet check gets mistaken
for evidence. Calling it a write-time guard does not resolve the conflict.

So either it goes in as an explicit, limited reversal (a marked message only
ever *lowers* what we trust from that conversation; an unmarked message proves
nothing), or it comes out and the loop keeps only its hard counters. **The
user had not answered when this session ended. Ask.**

## What to do next

Step 1 of the plan: write the rule down. A "what this is for" section at the
top of `CONTEXT.md`, and ADR 0008 carrying the three fairness conditions.
Documents only, no code, so the baseline does not move. Existing ADRs are
flowing prose with a decision-shaped title — match `docs/adrs/0005-*.md`.

Then step 2: a rough probe pointed at the scripted bot in
`/Users/vishal/Desktop/journey_agent`, to prove it stops on its own. It must
change nothing that exists — one new file plus a throwaway driver — and it
must still go through the agent adapter and still retrieve-then-release, both
of which `AGENTS.md` requires and neither of which `run_episode` will be doing
for you.

## Landmines — each of these cost this session time

- **`episode.py` allows exactly two endings from the customer** (`_USER_STOPS`,
  line 58). A third one fails the check at line 193, which is caught by the
  `except` directly below it and recorded as **`simulator_error` — our customer
  crashed**. So the probe's honest endings currently get filed as our own bug.
- **Do not widen `SIMULATED_USER_STOP_REASONS`.** That tuple is handed to the
  model as its menu of choices (`simulated_user.py:105`). Widen it and the
  *existing* customer silently gains options it never had, and every earlier
  run stops being comparable. The probe needs its own list and its own schema.
- **Evaluation's rule 1 returns `error` before it reads the evidence**
  (`evaluation.py:274`). So labelling a new ending an error throws away any
  real break that happened earlier in that conversation.
- **The code checks only ever read tool calls, never the bot's words.** So
  anything living in what the bot *said* can only be caught by the judge, and
  costs a person a full read.
- **Of the four code checks: one can never fire** (the bot's own wiring blocks
  the case), **two only fire if the bot invents an id from nothing**, and one
  is realistically reachable.
- **That last one is a coin flip.** `update_matches_goal` compares a successful
  update against the scenario's goal. If the bot guesses which appointment the
  customer meant and guesses *right*, the check passes and the "customer
  chooses" violation is visible only to the judge. The wrong-appointment target
  is still the best first target; it is not the sure thing an earlier draft of
  the plan claimed.
- **Nothing detects a break while the conversation is running.** The recording
  of what the bot did arrives afterwards. Any cap or ending that assumes
  online detection cannot be built.

## Housekeeping

- The ignored `.env` is already copied into both repositories. Export it with
  `set -a; . ./.env; set +a`; never print a key.
- **No live model calls** without the user explicitly asking for them. Steps 1
  and 2 need none.
- This is a git worktree sharing a stash stack with other checkouts. Never use
  bare `git stash` / `git stash pop`; prefer a temporary commit.
- Run the `compound` skill before ending a session that implemented, debugged
  or reviewed anything, and commit its outputs.
