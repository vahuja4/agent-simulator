"""Label the recorded J1 customer turns once, offline, with the calibrated judge
model, so `tests/test_mock_intent_corpus.py` checks the mock's intent gate
against labels it did not produce itself.

Run only on explicit request (it is one live LLM call). Output:
`tests/fixtures/j1_customer_turn_labels.json`, whose header records the
model id, the corpus counts, and the label definitions.

    set -a; . .env; set +a
    .venv/bin/python scripts/label_j1_customer_turns.py
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentsim.llm import OpenAILLM  # noqa: E402

MODEL = "gpt-5.5"
CORPUS_GLOB = "synthesized_scenarios/runs/*/episodes/*-transcript.jsonl"
OUT = ROOT / "tests" / "fixtures" / "j1_customer_turn_labels.json"

LABEL_DEFINITIONS = (
    "intent: exactly one of question | correction | selection | confirm | decline. "
    "A mixed turn is labeled by the part the mock must not get wrong: a turn "
    "that asks a question while also naming details is a question (the mock "
    "must not stage the details); a turn that both accepts and changes "
    "something is a correction. "
    "actionable: the card (last four), the option label or dollar amount, and "
    "the payment date (ISO) the mock may act on from this turn; all null for "
    "any question. "
    "negated: cards (last four) or option labels the turn names but rejects."
)

SYSTEM = f"""You label customer turns from recorded conversations with a credit-card
payment assistant. The assistant is deterministic and mines each message for
payment details; your labels say what it is allowed to act on.

Fixture world: cards ending 9013 (Chase Sapphire Preferred, due 2026-06-20),
0767 (Chase Freedom Unlimited, due 2026-06-25), 4421 (Chase Freedom Flex, due
2026-06-28); funding accounts ending 5678 (Chase Total Checking) and 4321
(external). Amount option labels: "Minimum payment due", "Statement balance",
"Remaining statement balance", "Current balance", "Other amount".

Label definitions:
{LABEL_DEFINITIONS}

Rules:
- intent=question: the customer is asking the assistant something and the
  assistant must answer, not stage a payment detail. Details named inside the
  question are not actionable, so `actionable` is all null.
- intent=correction: the customer changes a detail they gave earlier (card,
  amount, date, account). `actionable` holds only the corrected value(s).
- intent=selection: the customer supplies a detail for the first time (opener,
  answer to a prompt, or "schedule it now" restating the same details).
- intent=confirm: the customer accepts the staged details. If the turn also
  names the details of the very payment being confirmed, they are actionable.
- intent=decline: the customer refuses or stops the staged action.
- negated: list every card last-four or option label the turn names but
  rejects ("not 9013", "instead of the minimum"). Use option labels exactly as
  listed above; use "$6,000.00"-style strings for dollar amounts.
- amount: an option label from the list above, or a dollar string like
  "$310.45"; when the turn names both a label and its figure, use the label.
- Output one label per turn id, in the input order, nothing else."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "integer"},
                    "intent": {
                        "type": "string",
                        "enum": ["question", "correction", "selection", "confirm", "decline"],
                    },
                    "actionable": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "card": {"type": ["string", "null"]},
                            "amount": {"type": ["string", "null"]},
                            "date": {"type": ["string", "null"]},
                        },
                        "required": ["card", "amount", "date"],
                    },
                    "negated": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "intent", "actionable", "negated"],
            },
        }
    },
    "required": ["labels"],
}


def extract_corpus() -> tuple[list[dict], dict]:
    files = sorted(glob.glob(str(ROOT / CORPUS_GLOB)))
    turns: list[dict] = []
    for path in files:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("record_type") != "episode":
                continue
            prev = ""
            for turn in rec["turns"]:
                if turn["speaker"] == "user":
                    turns.append(
                        {
                            "text": turn["text"],
                            "previous_agent": prev,
                            "source": f"{Path(path).parent.parent.name[:28]}/{Path(path).name}#{turn['index']}",
                        }
                    )
                prev = turn["text"]
    unique: dict[str, dict] = {}
    for t in turns:
        entry = unique.setdefault(
            t["text"], {"text": t["text"], "previous_agent": t["previous_agent"], "sources": []}
        )
        entry["sources"].append(t["source"])
    corpus = [dict(id=i, **e) for i, e in enumerate(unique.values())]
    counts = {
        "transcripts": len(files),
        "customer_turns": len(turns),
        "unique_customer_turns": len(corpus),
    }
    return corpus, counts


async def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set; export .env first", file=sys.stderr)
        return 1
    corpus, counts = extract_corpus()
    print(f"corpus: {counts}")
    payload = [
        {
            "id": e["id"],
            "previous_assistant_message": e["previous_agent"][:400],
            "customer_turn": e["text"],
        }
        for e in corpus
    ]
    llm = OpenAILLM(MODEL)
    out = await llm.structured(
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=0)}],
        schema=SCHEMA,
        effort="high",
        max_tokens=32768,
    )
    labels = {l["id"]: l for l in out["labels"]}
    missing = [e["id"] for e in corpus if e["id"] not in labels]
    if missing:
        print(f"model omitted ids {missing}", file=sys.stderr)
        return 1
    for e in corpus:
        l = labels[e["id"]]
        e["intent"] = l["intent"]
        e["actionable"] = l["actionable"]
        e["negated"] = l["negated"]
        e.pop("previous_agent")
    document = {
        "header": {
            "purpose": "Intent labels for every unique recorded J1 customer turn; consumed by tests/test_mock_intent_corpus.py",
            "labeled_by_model": MODEL,
            "labeled_on": date.today().isoformat(),
            "corpus_glob": CORPUS_GLOB,
            "counts": counts,
            "label_definitions": LABEL_DEFINITIONS,
            "usage": llm.usage_records,
        },
        "turns": corpus,
    }
    OUT.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} with {len(corpus)} labeled turns")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
