# Mission: Core components of the agent simulator

## Why
Vishal needs to *own* this codebase — able to defend its design in reviews and
explain it to teammates and stakeholders — and to *extend* it hands-on:
adding scenarios, policies, curveballs, and eventually whole journey graphs
without help.

## Success looks like
- Can draw the full pipeline from memory (fixtures → scenario → simulator ⇄
  adapter → judge/assertions → clustering → report) and answer "why is it
  built this way?" for each box.
- Given a failing run or a weird verdict, can name the responsible component
  and the file it lives in.
- Can add a new scenario YAML, a new policy, or a new curveball declaration
  end-to-end, including the validator and dry-run steps.
- Can explain the system to a newcomer using the visual story
  (`agent-simulator-story.html`) and then go one level deeper in code.

## Constraints
- Visual-first learner: big diagrams, few words, one concrete example per
  visual — grounded in real repo data (cards …0767/…4421/…9013), never toys.
- Already fluent in the big-picture overviews (SAGE recipe, scenario factory,
  curveballs, ALMITA lineage) — lessons must go deeper than those, into code.
- Short lessons; one tangible win each.

## Out of scope
- Prompt-engineering the LLMs themselves (judge/simulator prompt tuning).
- The deprecated/experimental plans not reflected in current code.
- General LLM-agent theory beyond what this repo's design decisions need.
