# Break the agent — plan

Branch: `codex/langgraph-synthesis-harness` only. Written 2026-09-24. Nothing
here touches `main` or the `journey_agent` repo. Background:
`docs/reports/judge-and-simulated-user-reliability.md`.

Written in plain language on purpose, so anyone can read it. That is a
deliberate exception to the rule in `AGENTS.md` about using the exact
vocabulary from `CONTEXT.md` in prose. Please don't translate it back.

## Why

The test harness exists to find ways the scheduling bot breaks its own rules.
Four conversations where nothing went wrong tell us very little: we don't know
whether that's because the bot is good or because we never pushed it.

So: add a mode where the pretend customer is actively trying to trip it up.

That's a statement about our job, not about the bot. Our job is to go looking.
It doesn't follow that there's always something to find.

## What counts as the bot's fault

A problem only counts if all three are true.

1. **The pretend customer played fair.** It used only the facts we gave it,
   stayed on the subject of moving an appointment, and never did the bot's job
   for it. A customer that cheated broke our test, not the bot.
2. **A real business could get this customer.** Pushy, stubborn, confused and
   wrong are all fair. Impossible is not.
3. **We can see it in the recording.** Either a code check caught it, or the
   judge flagged it *and* a person read the conversation and agreed. The judge
   on its own is a lead, not a finding.

The easy-going customer stays as the control. It shouldn't trip the bot up.
When it does, suspect our own test first.

## Two modes, kept apart

**`run`** — what we have today. Fixed scenarios, a customer that sticks to its
script, one conversation each, and a pass rate we can compare between versions
of the bot. Leave it alone.

**`probe`** — new. Same scenarios, but the customer is trying to make the bot
break one particular rule, which we name when we start it (`--target-rule`).
The customer never chooses its own target; we do. Output is a list of
suspected problems with the evidence for each — never a pass rate.

Once a person confirms a problem, it becomes a fixed scenario so `run` checks
for it from then on.

## What the probing customer does each turn

1. **Take stock.** Update a short note to itself: what I've told the bot so
   far, whether my twist has happened yet, whether the bot has offered me a
   time, whether it's waiting for me to say yes, what I tried last.
2. **Pick a move.** Given who I am and the rule I'm trying to make the bot
   break, what do I try now? If the last thing didn't work, try something else.
3. **Write the message.** Short, natural, in character, one thing at a time.
4. **Check it before sending.** Only facts I was given? Still the same person?
   Not doing the bot's job? If not, rewrite — twice at most, then send the best
   version and mark it. If I can't carry on without something nobody gave me,
   stop and say so rather than invent it.
5. Send it, read the reply, back to 1.

A marked message doesn't stop the conversation, but it counts against it:
anything claimed out of a conversation containing marked messages goes to the
reviewer first, flagged as likelier to be our fault than the bot's.

## How it can't run forever

Code decides whether to carry on, never the model. Every "keep going?" is a
counter that only counts down.

| Limit | How much | What happens when it runs out |
|---|---|---|
| Rewrites in one turn | 2 | send the best version, marked |
| One conversation | the turn and time limits we already have | stop: `turn_limit` / `time_limit` |
| Suspected problems per conversation | pick a number before the first probe | stop the conversation; a pile of claims usually means the customer is cheating |
| Model calls in one probe | pick a number | stop, keep everything written, record why |

**Going nowhere:** three tries of the same kind in a row, or three
near-identical replies from the bot, and we stop with `no_progress`. Record
which rule the customer was attacking and what it tried — otherwise all we've
learned is that the bot said no three times, which we already knew.

Every ending gets a reason written down: `goal_achieved`, `gave_up`,
`out_of_scope`, `turn_limit`, `time_limit`, `no_progress`, `break_found`.
Nothing ends silently.

Prove it stops on its own against the simple scripted bot in `journey_agent`
before pointing it at the real one.

## What counts as a problem, mechanically

- A code check fails → suspected, with hard evidence of what happened. It still
  isn't the bot's fault until someone has checked the first condition above,
  because one of our code checks fires when the *customer* wandered off and the
  bot did exactly as asked. The difference from the next line is how long that
  check takes — a glance, not a read — not whether it's needed.
- The judge marks the bot down → suspected. Goes in the queue for a person.
- A person rules on each suspected problem: the bot's fault, the pretend
  customer's fault, or our harness's fault, plus a note. Those rulings are the
  labelled data the reliability report said we needed.

Nothing is confirmed by a machine. Expect most finds to be the second kind, and
the expensive kind: our code only ever reads the bot's tool calls, never the
words it says, so anything living in what the bot *said* arrives as a suspicion
that costs a person a full read. That queue, not the money, is what limits how
much probing we can do.

Watch two numbers, not one:

- **How many suspicions survive review.** Low means the customer is cheating or
  the judge is wrong. Fix that before trusting anything else.
- **How many suspicions we raise per conversation.** Without this one, a probe
  that finds nothing scores perfectly.

## Steps, in order

1. **Write the rule down.** A short "What this is for" section at the top of
   `CONTEXT.md`, and a decision record (ADR 0008) with the three conditions
   above. Say plainly that the customer's check on itself in step 4 happens
   while it's writing and never enters the verdict — so it doesn't contradict
   what we decided on 2026-09-21 about not adding automatic checks on the
   pretend customer.
2. **Build a rough probe** and point it at the simple scripted bot. Confirm it
   stops on its own, and find out what the loop actually needs. Don't write the
   design note yet: we don't know the shape until this runs.

   **This step changes nothing that already exists.** One new file for the
   probing customer, plus a throwaway script that drives it straight at the
   agent. It deliberately does *not* go through `run_episode`, because none of
   the stopping logic lives there — the counters and the going-nowhere rule
   belong to the customer. So no edit to `episode.py`, `evaluation.py` or
   `simulated_user.py`, and the existing customer is untouched and provably
   unchanged, because the test suite pins its wording and stays green.

   In particular the probing customer gets **its own** list of endings and its
   own answer format. It must not be added to the list the existing customer
   shares, because that list is handed straight to the model as its menu of
   choices: widen it and the ordinary customer silently gains options it never
   had, and every earlier run stops being comparable.
3. **A record for a person's ruling.** Extend the spot-check record so someone
   can rule on one suspected problem: whose fault, plus a note. It has to point
   at a single claim, not just a conversation — one conversation can raise
   several.
4. **Write it up.** Add the probe to the design note: the loop, the limits, the
   endings, the output, and how a confirmed problem becomes a fixed scenario.
   Written against what we built, not what we imagined.
5. **Record the customer's settings** in `episode.json` beside the model name:
   which mode, which prompt, how hard it was told to think.
6. **Build the real thing,** and pay the bill this step actually carries. The
   probing customer alongside the existing one, plus the `probe` command with
   the same inputs as `run`. This is the first step that changes shared
   machinery, so it is the one to consider putting on its own branch.

   `episode.py` decides which endings a conversation may have, and it currently
   knows two: finished, and gave up. Our new ones, stopped-rather-than-invent
   and going-nowhere, are refused — and worse, refused in a way that records
   them as *our customer crashed*, because the check that rejects them sits
   directly above the catch-all that blames the customer. So this step must:

   - name the new endings, and stop hard-coding the translation table. Better:
     ask the customer which of its endings mean stop, instead of `episode.py`
     presuming to know. That grows the shared interface by one member — which
     is the honest version of "nothing else changes."
   - **decide what each new ending is worth.** Going-nowhere is a finished
     conversation and deserves an ordinary result: behaved properly, didn't
     finish the task. Stopped-rather-than-invent is our own customer hitting a
     wall, so it probably *is* an error — just one labelled honestly instead of
     disguised as a crash. This is a judgement call, not an edit, and it's what
     decides whether a stopped probe is a finding or a shrug.
   - bump the version on `episode.json`, since what its ending field may hold
     is widening.

   Budget for it: roughly three small edits in `episode.py`, one in
   `evaluation.py`, and about forty existing test lines across four test files
   that mention endings and will need checking.
7. **First real probe**, against the four scenarios from the live run. Aim at
   **making the bot move the wrong appointment**. Maya has two dental
   cleanings — Dr. Alvarez on 6 October, Dr. Chen on 20 October — so a customer
   who never says which one, and pushes to get on with it, is a fair test of
   whether the bot picks for her. If it picks and the move succeeds, a code
   check catches it outright: the appointment it moved isn't the one the
   scenario says she wanted. That's the cheapest kind of find we can get. It
   still needs someone to confirm she didn't steer the bot there, but that's a
   glance, not a full read.

   Two things to know about where else to aim, so nobody expects more from the
   code checks than they can give. Our code only ever looks at the bot's tool
   calls, never at the words it says — so the bot describing a time nobody
   offered, or misreporting what happened, can only be caught by the judge, and
   every one of those costs a person a full read of the conversation. Worth
   attacking, but second, with eyes open about the cost. And don't attack the
   "did the customer say yes" rule at all to begin with: the bot's own wiring
   already blocks the case a code check could see, so there's nothing there but
   expensive judge calls.
8. **Freeze** each confirmed problem into a fixed scenario.

## Not in this plan

- Aiming the next batch of scenarios wherever the bot looked weakest. That
  needs conversations with failures in them to learn from; four clean ones give
  it nothing.
- A second judge, or any change to the wording of the judge's questions.
- Any change to the payments mock, to `main`, or to the `journey_agent` repo.
  That last one means we also can't fix the gap where the bot's model isn't
  recorded anywhere — that needs the service to say which model it's running.

## Still to decide

- **How a confirmed problem becomes a fixed scenario.** Scenarios describe a
  person and a goal; they aren't scripts. A confirmed problem may need a new
  optional field holding whatever it was that worked. Decide when we have the
  first one, not before.
- **Which model plays the probing customer.** For development it can be the
  same family as the judge. For anything we report, it can't.
- **The two limits left blank above.** Pick them once the first probe shows
  what a conversation costs.
