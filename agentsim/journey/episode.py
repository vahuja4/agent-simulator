"""One Episode on the conversation lifecycle (design note sections 8 and 9):

    start → {Simulated user turn → save → send_message → save reply}* →
    retrieve → release

The conversation talks to the agent only through ``ConversationAdapter``.
Nothing is judged or asserted here and no outcome or Verdict is assigned: the
agent claiming completion establishes nothing, and the Trace — retrieved once,
after the conversation — is what evaluation reads.

Retrieval then release are attempted on every path, in that order: after a
request timeout the agent may still have finished the Turn server-side, and
the adapter's fallback record is dropped at release. Every message is on disk
before the next operation that can fail, so a crash leaves what happened.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml

from ..adapters.conversation import (
    AdapterError,
    ConversationAdapter,
    ConversationHandle,
    RetrievedTrace,
)
from ..types import Message
from .definition import FixtureState
from .normalized_trace import Evidence, NormalizedTrace
from .scenario import JourneyScenario
from .simulated_user import (
    STOP_REASON_GAVE_UP,
    STOP_REASON_GOAL_ACHIEVED,
    JourneySimTurn,
)

EPISODE_SCHEMA_VERSION = "1.0"
DEFAULT_TIME_LIMIT_S = 600.0

STOP_USER_FINISHED = "user_finished"
STOP_USER_GAVE_UP = "user_gave_up"
STOP_TURN_LIMIT = "turn_limit"
STOP_TIME_LIMIT = "time_limit"
STOP_ADAPTER_ERROR = "adapter_error"
STOP_SIMULATOR_ERROR = "simulator_error"
EPISODE_STOP_REASONS: tuple[str, ...] = (
    STOP_USER_FINISHED, STOP_USER_GAVE_UP, STOP_TURN_LIMIT, STOP_TIME_LIMIT,
    STOP_ADAPTER_ERROR, STOP_SIMULATOR_ERROR,
)
_USER_STOPS = {
    STOP_REASON_GOAL_ACHIEVED: STOP_USER_FINISHED,
    STOP_REASON_GAVE_UP: STOP_USER_GAVE_UP,
}

SCENARIO_FILE = "scenario.yaml"
TRANSCRIPT_FILE = "transcript.jsonl"
EPISODE_FILE = "episode.json"
RAW_TRACE_FILE = "raw_trace.json"
NORMALIZED_TRACE_FILE = "normalized_trace.json"


class EpisodeError(ValueError):
    """The Episode cannot be run as requested; nothing was written."""


class SimulatedUser(Protocol):
    async def next_turn(self, history: list[Message]) -> JourneySimTurn: ...


@dataclass(frozen=True)
class EpisodeRecord:
    """What ``episode.json`` holds, and where the Episode directory is."""

    episode_dir: Path
    record: dict[str, Any]

    @property
    def stop_reason(self) -> str:
        return self.record["stop_reason"]


async def run_episode(
    scenario: JourneyScenario,
    *,
    fixture_state: FixtureState,
    adapter: ConversationAdapter,
    simulated_user: SimulatedUser,
    episode_dir: str | Path,
    service_url: str,
    time_limit_s: float = DEFAULT_TIME_LIMIT_S,
    clock: Callable[[], float] = time.monotonic,
) -> EpisodeRecord:
    """Play one Scenario and leave its Episode directory. The adapter is
    blocking; with sequential execution that is acceptable (section 8).

    An adapter or Simulated-user failure is a stop reason, not an exception.
    Anything else (a harness bug, an interrupt) still gets retrieval, release
    and an ``episode.json`` marked ``aborted`` before it propagates."""
    episode_dir = Path(episode_dir)
    if (episode_dir / TRANSCRIPT_FILE).exists() or (episode_dir / EPISODE_FILE).exists():
        raise EpisodeError(f"{episode_dir} already holds an Episode; it is never overwritten")
    if time_limit_s <= 0:
        raise EpisodeError(f"time_limit_s must be positive, got {time_limit_s!r}")
    episode_dir.mkdir(parents=True, exist_ok=True)
    _write_text(episode_dir / SCENARIO_FILE, _scenario_yaml(scenario))
    transcript = episode_dir / TRANSCRIPT_FILE
    transcript.touch()

    record: dict[str, Any] = {
        "schema_version": EPISODE_SCHEMA_VERSION,
        "status": "aborted",
        "scenario_id": scenario.scenario_id,
        "journey": scenario.journey,
        "service_url": service_url,
        "agent": None,
        "conversation_id": None,
        "fixture_state_sha256": fixture_state.sha256,
        "simulator_model": getattr(simulated_user, "model", None),
        "stop_reason": None,
        "turns_completed": 0,
        "max_turns": scenario.max_turns,
        "time_limit_s": time_limit_s,
        "started_at": _utc_now(),
        "ended_at": None,
        "duration_s": None,
        "error": None,
        "retrieval": {"attempted": False, "raw_trace_saved": False, "error": None,
                      "evidence": None},
        "release": {"attempted": False, "error": None},
    }
    started = clock()
    handle: ConversationHandle | None = None
    try:
        try:
            handle = adapter.start_conversation(
                fixture_state=fixture_state, tool_failures=scenario.fixture.tool_failures
            )
        except AdapterError as error:
            record["stop_reason"] = STOP_ADAPTER_ERROR
            record["error"] = _adapter_failure("start_conversation", error)
        else:
            record["agent"] = handle.agent
            record["conversation_id"] = handle.conversation_id
            record["stop_reason"] = await _converse(
                scenario, adapter, handle, simulated_user, transcript, record,
                time_limit_s=time_limit_s, clock=clock, started=started,
            )
        record["status"] = "complete"
    except BaseException as error:
        record["error"] = {
            "source": "harness", "type": type(error).__name__, "message": str(error),
        }
        raise
    finally:
        # Every path ends here: retrieve, then release, then the record.
        _retrieve_and_release(adapter, handle, scenario, fixture_state, episode_dir, record)
        record["ended_at"] = _utc_now()
        record["duration_s"] = round(clock() - started, 3)
        _write_json(episode_dir / EPISODE_FILE, record)
    return EpisodeRecord(episode_dir, record)


async def _converse(
    scenario: JourneyScenario,
    adapter: ConversationAdapter,
    handle: ConversationHandle,
    simulated_user: SimulatedUser,
    transcript: Path,
    record: dict[str, Any],
    *,
    time_limit_s: float,
    clock: Callable[[], float],
    started: float,
) -> str:
    """The Turn loop. Returns the stop reason; limits are checked between Turns."""
    history: list[Message] = []
    while True:
        turn = record["turns_completed"] + 1
        if turn > scenario.max_turns:
            return STOP_TURN_LIMIT
        if clock() - started >= time_limit_s:
            return STOP_TIME_LIMIT
        try:
            sim_turn = await simulated_user.next_turn(history)
            if sim_turn.stop != (sim_turn.stop_reason in _USER_STOPS) or not (
                sim_turn.text or sim_turn.stop
            ):
                raise ValueError(
                    f"unusable Simulated-user turn: text={sim_turn.text!r}, "
                    f"stop={sim_turn.stop!r}, stop_reason={sim_turn.stop_reason!r}"
                )
        except Exception as error:  # LLMError, or a broken double: the Episode is an error
            record["error"] = {
                "source": "simulated_user", "turn": turn,
                "type": type(error).__name__, "message": str(error),
            }
            return STOP_SIMULATOR_ERROR

        if sim_turn.text:
            # On disk before the send: a send that fails is not in the
            # adapter's record, so the Transcript is where this message survives.
            _append(transcript, {
                "turn": turn, "role": "user", "text": sim_turn.text,
                "intent": sim_turn.intent, "stop_reason": sim_turn.stop_reason,
                "at": _utc_now(),
            })
            try:
                reply = adapter.send_message(handle, sim_turn.text)
            except AdapterError as error:
                record["error"] = _adapter_failure("send_message", error, turn=turn)
                return STOP_ADAPTER_ERROR
            _append(transcript, {
                "turn": turn, "role": "agent", "text": reply.text,
                "message_id": reply.message_id,
                "user_message_id": reply.user_message_id, "at": _utc_now(),
            })
            history.append(Message("user", sim_turn.text))
            history.append(Message("assistant", reply.text))
            record["turns_completed"] = turn
        if sim_turn.stop:
            return _USER_STOPS[sim_turn.stop_reason]


def _retrieve_and_release(
    adapter: ConversationAdapter,
    handle: ConversationHandle | None,
    scenario: JourneyScenario,
    fixture_state: FixtureState,
    episode_dir: Path,
    record: dict[str, Any],
) -> None:
    """Retrieve, save, release — in that order, each attempted whatever the
    one before it did. Never raises: this runs while another error may be
    propagating, and that error is the one to report."""
    retrieval, release = record["retrieval"], record["release"]
    if handle is None:
        reason = "no conversation was started"
        retrieval["error"] = reason
        normalized = NormalizedTrace(
            conversation_id="",
            platform="unknown",
            fixture_state_sha256=fixture_state.sha256,
            tool_failures=scenario.fixture.tool_failures,
            evidence=Evidence("unavailable", "unavailable", (reason,)),
        )
        try:
            _save_trace(RetrievedTrace(None, normalized, reason), episode_dir, retrieval)
        except Exception as error:
            retrieval["error"] = f"saving the Trace failed: {type(error).__name__}: {error}"
        return

    retrieval["attempted"] = True
    try:
        retrieved = adapter.retrieve_trace(handle)
    except Exception as error:  # the contract says it never raises; keep going if it does
        retrieval["error"] = f"retrieve_trace raised {type(error).__name__}: {error}"
    else:
        retrieval["error"] = retrieved.error
        try:
            _save_trace(retrieved, episode_dir, retrieval)
        except Exception as error:
            retrieval["error"] = f"saving the Trace failed: {type(error).__name__}: {error}"

    release["attempted"] = True
    try:
        adapter.release(handle)
    except AdapterError as error:
        release["error"] = error.to_dict()
    except Exception as error:
        release["error"] = {"type": type(error).__name__, "message": str(error)}


def _save_trace(retrieved: RetrievedTrace, episode_dir: Path, retrieval: dict[str, Any]) -> None:
    if retrieved.raw is not None:
        # The platform's payload, untouched — an unusable one included.
        _write_json(episode_dir / RAW_TRACE_FILE, retrieved.raw)
        retrieval["raw_trace_saved"] = True
    _write_text(
        episode_dir / NORMALIZED_TRACE_FILE, retrieved.normalized.to_json(indent=2) + "\n"
    )
    retrieval["evidence"] = retrieved.normalized.evidence.to_dict()


def _adapter_failure(operation: str, error: AdapterError, **where: Any) -> dict[str, Any]:
    """``AdapterError.to_dict()`` as it is: kind, status, code and
    ``agent_fault`` tell an agent crash from a transport or timeout problem."""
    return {"source": "adapter", "operation": operation, **where,
            "adapter_error": error.to_dict()}


# ------------------------------------------------------------------ files


def _scenario_yaml(scenario: JourneyScenario) -> str:
    """The Scenario as it was run, in the form ``load_journey_scenario`` reads."""
    synthesis = scenario.synthesis
    evidence = scenario.knowledge_evidence
    document = {
        "schema_version": 1,
        "scenario_id": scenario.scenario_id,
        "journey": scenario.journey,
        "description": scenario.description,
        "persona": {
            "archetype": scenario.persona.archetype,
            "name": scenario.persona.name,
            "traits": scenario.persona.traits,
        },
        "goal": scenario.goal,
        "knowledge_level": scenario.knowledge_level,
        "knowledge_evidence": {
            "kind": evidence.kind,
            **({"rule": evidence.rule} if evidence.rule is not None else {}),
            **({"referent": evidence.referent} if evidence.referent is not None else {}),
        },
        "complication": scenario.complication,
        "fixture": {
            "customer_id": scenario.fixture.customer_id,
            "appointment_id": scenario.fixture.appointment_id,
            "target_slot_ids": list(scenario.fixture.target_slot_ids),
            "tool_failures": list(scenario.fixture.tool_failures),
        },
        "grounded_facts": [
            {"path": fact.path, "value": fact.value} for fact in scenario.grounded_facts
        ],
        "max_turns": scenario.max_turns,
        "expected_outcome": scenario.expected_outcome,
        "criteria": {
            "assertions": list(scenario.assertion_ids),
            "judge": list(scenario.judge_criterion_ids),
        },
        "synthesis": {
            "origin": synthesis.origin,
            "qualification": synthesis.qualification,
            "set_id": synthesis.set_id,
            "spec_id": synthesis.spec_id,
            "journey_sha256": synthesis.journey_sha256,
            "fixture_state_sha256": synthesis.fixture_state_sha256,
            "generation_config_sha256": synthesis.generation_config_sha256,
            "generator_version": synthesis.generator_version,
            "model": synthesis.model,
            "generated_at": synthesis.generated_at,
        },
    }
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def _append(path: Path, line: dict[str, Any]) -> None:
    """One Transcript line, on disk before this returns."""
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(line, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _write_text(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _write_json(path: Path, value: Any) -> None:
    _write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
