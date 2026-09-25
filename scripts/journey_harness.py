#!/usr/bin/env python3
"""The Journey harness commands (design note section 9, ADR 0008):

    synthesize  a small set of Scenarios from a Journey definition and Fixture state
    run         the saved Scenarios against the agent service, one after another,
                then evaluate each saved Episode
    probe       one realized Ladder against the agent service, Rung by Rung,
                stopping at the first Rung not survived
    summarize   a Run: cluster its failures and write report.md

``run`` measures and ``probe`` goes looking; they share everything below the
mode — the same Episodes, the same evaluation, the same Verdicts — and differ
only in what is played and what is reported. A Probe reports how far the agent
climbed and its suspected findings, never a Pass rate, and it keeps its Episodes
out of ``journey_runs/`` so a Run never contains one.

This script is the composition root: it is the only place that joins
``scenario_synthesis`` (provenance, Ladders) to ``agentsim.journey`` (Episodes,
evaluation, the climb, report). ``run`` and ``probe`` have no doubles mode;
tests pass doubles to ``run_command`` and ``probe_command`` directly.

Exit status, every command: 0 done; 1 the command started writing and then
aborted (what it wrote is kept, and a record says so) or, for ``synthesize``,
fell short; 2 the request or its configuration is unusable — always before the
first write. A Scenario that fails, or an Episode that ends in ``error``, is a
result, not a command failure: ``run`` still exits 0.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence, TextIO

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agentsim._io import _atomic_json  # noqa: E402
from agentsim.adapters.conversation import AdapterError, ConversationAdapter  # noqa: E402
from agentsim.adapters.journey_service import (  # noqa: E402
    DEFAULT_REQUEST_TIMEOUT_S,
    JourneyServiceAdapter,
)
from agentsim.batch import BatchRunner, BatchRunSpec  # noqa: E402
from agentsim.journey.climb import SeedResult, climb, summarize  # noqa: E402
from agentsim.journey.definition import (  # noqa: E402
    JOURNEY_FILE,
    FixtureState,
    JourneyDefinition,
    load_journey_inputs,
)
from agentsim.journey.episode import (  # noqa: E402
    DEFAULT_TIME_LIMIT_S,
    SCENARIO_FILE,
    SimulatedUser,
    run_episode,
)
from agentsim.journey.evaluation import EpisodeJudge, evaluate_episode  # noqa: E402
from agentsim.journey.judge import live_journey_judge  # noqa: E402
from agentsim.journey.report import (  # noqa: E402
    RUN_RECORD_FILE,
    RUN_RECORD_SCHEMA_VERSION,
    RUN_STATUS_ABORTED,
    RUN_STATUS_COMPLETE,
    RUN_STATUS_RUNNING,
    clustering_view,
    load_run_record,
    summarize_run,
)
from agentsim.journey.scenario import (  # noqa: E402
    JourneyScenario,
    check_against_inputs,
    load_journey_scenario,
)
from agentsim.journey.simulated_user import (  # noqa: E402
    SimulatorConfigError,
    live_simulated_user,
)
from agentsim.orchestrator import RunResult  # noqa: E402
from agentsim.types import BatchManifest, FailureRecord  # noqa: E402
from scenario_synthesis import journey_synthesis  # noqa: E402
from scenario_synthesis._async import run as run_on_the_process_loop  # noqa: E402
from scenario_synthesis.evidence import sha256_file, utc_timestamp  # noqa: E402
from scenario_synthesis.ladder import (  # noqa: E402
    LADDERS,
    Ladder,
    LadderError,
    ladder_and_rung_for,
)

DEFAULT_RUN_ROOT = "journey_runs"
DEFAULT_PROBE_ROOT = "journey_probes"
_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

SimulatedUserFactory = Callable[[JourneyScenario], SimulatedUser]


# ---------------------------------------------------------------------- run


def run_command(
    *,
    journey_dir: str | Path,
    scenarios_dir: str | Path,
    service_url: str,
    run_id: str,
    output_root: str | Path = DEFAULT_RUN_ROOT,
    simulator_model: str | None = None,
    enforce_model_family_separation: bool = False,
    request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
    episode_timeout_s: float = DEFAULT_TIME_LIMIT_S,
    out: TextIO,
    adapter: ConversationAdapter | None = None,
    simulated_user_factory: SimulatedUserFactory | None = None,
    judge: EpisodeJudge | None = None,
) -> int:
    """The body of ``journey_harness.py run``: one Episode per saved Scenario,
    strictly one after another, each evaluated as soon as it is saved.
    ``adapter``, ``simulated_user_factory`` and ``judge`` are for tests."""
    journey_dir, scenarios_dir = Path(journey_dir), Path(scenarios_dir)
    run_dir = Path(output_root) / run_id
    try:
        if not _RUN_ID.match(run_id):
            raise ValueError(f"run id {run_id!r} must match {_RUN_ID.pattern}")
        journey, fixture_state = load_journey_inputs(journey_dir)
        scenarios = _load_verified_set(scenarios_dir, journey_dir, journey, fixture_state)
        if run_dir.exists():
            raise ValueError(f"{run_dir} already exists; a Run is never overwritten")
        if simulated_user_factory is None:
            def simulated_user_factory(scenario: JourneyScenario) -> SimulatedUser:
                return live_simulated_user(scenario, journey, model=simulator_model)
        simulator = _simulator_model(simulated_user_factory, scenarios[0])
        if judge is None:
            judge = live_journey_judge(
                journey,
                simulator_model=simulator,
                enforce_model_family_separation=enforce_model_family_separation,
            )
        if adapter is None:
            adapter = JourneyServiceAdapter(service_url, request_timeout_s=request_timeout_s)
        agent = _probe_agent(adapter, fixture_state)
    except (OSError, ValueError, KeyError, TypeError, AdapterError) as error:
        return _unusable("run", error, out)

    print(
        f"Run {run_id!r}: {len(scenarios)} Scenario(s) from {scenarios_dir}, one Episode "
        f"each, sequentially\nagent: {agent} (service {service_url})\n"
        f"Simulated-user model: {simulator}; Judge model: {getattr(judge, 'model', None)}",
        file=out,
    )
    try:
        run_dir.mkdir(parents=True)
    except OSError as error:
        return _unusable("run", error, out)
    record = {
        "schema_version": RUN_RECORD_SCHEMA_VERSION,
        "run_id": run_id,
        "status": RUN_STATUS_RUNNING,
        "journey_id": journey.journey_id,
        "journey_dir": str(journey_dir),
        "journey_sha256": sha256_file(journey_dir / JOURNEY_FILE),
        "fixture_state_sha256": fixture_state.sha256,
        "scenario_set": str(scenarios_dir),
        "scenario_ids": [scenario.scenario_id for scenario in scenarios],
        "service_url": service_url,
        "agent": agent,
        "simulator_model": simulator,
        "judge_model": getattr(judge, "model", None),
        "enforce_model_family_separation": enforce_model_family_separation,
        "request_timeout_s": request_timeout_s,
        "episode_timeout_s": episode_timeout_s,
        "started_at": utc_timestamp(),
        "ended_at": None,
        "re_evaluation": None,
        "error": None,
    }
    _atomic_json(run_dir / RUN_RECORD_FILE, record)

    async def execute(spec: BatchRunSpec) -> RunResult:
        episode_dir = run_dir / "runs" / spec.run_key
        await run_episode(
            spec.scenario,
            fixture_state=fixture_state,
            adapter=adapter,
            simulated_user=simulated_user_factory(spec.scenario),
            episode_dir=episode_dir,
            service_url=service_url,
            time_limit_s=episode_timeout_s,
        )
        return await _evaluate(episode_dir, judge, journey)

    specs = [_spec(scenario, run_id, simulator or "") for scenario in scenarios]
    status = _play(run_dir, record, record, specs, execute, out)
    if status == 0:
        print(
            f"Run complete: {run_dir}\nnext: scripts/journey_harness.py summarize {run_dir}",
            file=out,
        )
    return status


def re_evaluate_command(
    *,
    journey_dir: str | Path,
    run_dir: str | Path,
    enforce_model_family_separation: bool = False,
    out: TextIO,
    judge: EpisodeJudge | None = None,
) -> int:
    """The body of ``run --re-evaluate``: evaluate every saved Episode of an
    existing Run again. No conversation is replayed; ``evaluation.json`` is
    derived from the rest of the Episode directory and is replaced."""
    journey_dir, run_dir = Path(journey_dir), Path(run_dir)
    try:
        journey, fixture_state = load_journey_inputs(journey_dir)
        record = load_run_record(run_dir)
        manifest_path = run_dir / "manifest.json"
        manifest = BatchManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
        journey_sha256 = sha256_file(journey_dir / JOURNEY_FILE)
        specs, problems = [], []
        for run_key, run_record in sorted(manifest.runs.items()):
            scenario_file = run_dir / "runs" / run_key / SCENARIO_FILE
            if not scenario_file.is_file():
                continue  # never started: nothing to evaluate
            scenario = load_journey_scenario(scenario_file)
            problems += _hash_problems(scenario, journey_sha256, fixture_state)
            spec = _spec(scenario, run_record.run_id, run_record.model)
            if spec.run_key != run_key:
                problems.append(f"{scenario_file}: is not the Scenario of Episode {run_key}")
            specs.append(spec)
        if problems:
            raise ValueError("; ".join(problems))
        if not specs:
            raise ValueError(f"{run_dir} holds no saved Episode to evaluate")
        if judge is None:
            judge = live_journey_judge(
                journey,
                simulator_model=record.get("simulator_model"),
                enforce_model_family_separation=enforce_model_family_separation,
            )
    except (OSError, ValueError, KeyError, TypeError) as error:
        return _unusable("run --re-evaluate", error, out)

    # BatchRunner skips a completed record, so the ones to evaluate are reset.
    for spec in specs:
        manifest.runs[spec.run_key].status = "pending"
        manifest.runs[spec.run_key].outcome = None
    _atomic_json(manifest_path, manifest.to_dict())
    # Whether the conversations finished (``status``) and whether this
    # re-evaluation finished are two facts, kept apart: the Run's own status,
    # end and error are never touched here.
    record["re_evaluation"] = {
        "status": RUN_STATUS_RUNNING,
        "started_at": utc_timestamp(),
        "ended_at": None,
        "error": None,
    }
    _atomic_json(run_dir / RUN_RECORD_FILE, record)
    print(f"Re-evaluating {len(specs)} saved Episode(s) of {run_dir}", file=out)

    async def execute(spec: BatchRunSpec) -> RunResult:
        return await _evaluate(run_dir / "runs" / spec.run_key, judge, journey)

    return _play(run_dir, record, record["re_evaluation"], specs, execute, out)


def _play(
    run_dir: Path,
    record: dict[str, Any],
    progress: dict[str, Any],
    specs: Sequence[BatchRunSpec],
    execute: Callable[[BatchRunSpec], Awaitable[RunResult]],
    out: TextIO,
) -> int:
    """One spec at a time, so nothing runs alongside anything else and an
    interrupt leaves no half-started sibling. ``BatchRunner`` never retries:
    ``run_episode`` refuses a directory that already holds an Episode. It
    records an ``execute`` that raises as ``error`` and the loop goes on; what
    escapes it (an interrupt, a failed write) aborts the Run, keeping what was
    written. ``progress`` is where ``status``, ``ended_at`` and ``error`` are
    written: the Run record itself for ``run``, its ``re_evaluation`` entry for
    ``run --re-evaluate``."""
    runner = BatchRunner(
        run_dir,
        concurrency=1,
        batch_id=str(record["run_id"]),
        configuration={"journey_id": record.get("journey_id"), "agent": record.get("agent")},
    )

    async def play_all() -> None:
        for number, spec in enumerate(specs, start=1):
            manifest = await runner.run([spec], execute)
            result = manifest.runs[spec.run_key]
            print(
                f"[{number}/{len(specs)}] {spec.scenario.name}: {result.outcome} — "
                f"{' '.join(result.final_reasoning.split())}",
                file=out,
            )

    try:
        run_on_the_process_loop(play_all())
    except BaseException as error:
        progress.update(
            status=RUN_STATUS_ABORTED,
            ended_at=utc_timestamp(),
            error={"type": type(error).__name__, "message": str(error)},
        )
        _atomic_json(run_dir / RUN_RECORD_FILE, record)
        print(
            f"ABORTED: {type(error).__name__}: {' '.join(str(error).split())} — what was "
            f"written is kept in {run_dir}",
            file=out,
        )
        if not isinstance(error, Exception):
            raise  # an interrupt stays an interrupt
        return 1
    progress.update(status=RUN_STATUS_COMPLETE, ended_at=utc_timestamp(), error=None)
    _atomic_json(run_dir / RUN_RECORD_FILE, record)
    return 0


async def _evaluate(
    episode_dir: Path, judge: EpisodeJudge, journey: JourneyDefinition
) -> RunResult:
    """Evaluate a saved Episode. The manifest record — what clustering reads —
    gets each failure without its per-Episode ids; ``evaluation.json`` keeps
    the full record."""
    result = (await evaluate_episode(episode_dir, judge, journey)).to_run_result()
    result.failures = [clustering_view(failure) for failure in result.failures]
    return result


def _spec(scenario: JourneyScenario, run_id: str, model: str) -> BatchRunSpec:
    return BatchRunSpec(scenario=scenario, run_id=run_id, model=model)  # type: ignore[arg-type]


def _load_verified_set(
    scenarios_dir: Path,
    journey_dir: Path,
    journey: JourneyDefinition,
    fixture_state: FixtureState,
) -> list[JourneyScenario]:
    """The set's accepted Scenarios, or ``ValueError`` naming every reason the
    set may not run against this Journey directory."""
    if not (scenarios_dir / "provenance.json").is_file():
        raise ValueError(f"{scenarios_dir} is not a synthesized set: no provenance.json")
    problems = journey_synthesis.verify_provenance(scenarios_dir, journey_dir)
    if problems:
        raise ValueError(f"{scenarios_dir} fails its provenance check: " + "; ".join(problems))
    journey_sha256 = sha256_file(journey_dir / JOURNEY_FILE)
    scenarios = [
        load_journey_scenario(path) for path in sorted((scenarios_dir / "accepted").glob("*.yaml"))
    ]
    if not scenarios:
        raise ValueError(f"{scenarios_dir} holds no accepted Scenario")
    for scenario in scenarios:
        problems += _hash_problems(scenario, journey_sha256, fixture_state)
        try:
            check_against_inputs(scenario, journey, fixture_state)
        except ValueError as error:
            problems.append(str(error))
    if problems:
        raise ValueError("; ".join(problems))
    return scenarios


def _hash_problems(
    scenario: JourneyScenario, journey_sha256: str, fixture_state: FixtureState
) -> list[str]:
    """``--journey`` must be the directory the Scenario was written from:
    criterion wording lives in ``journey.yaml``, so another file would be
    judged with other wording."""
    where = Path(scenario.source)
    expected = {
        "journey_sha256": journey_sha256,
        "fixture_state_sha256": fixture_state.sha256,
    }
    return [
        f"{where}: synthesis.{key} does not match the --journey directory"
        for key, value in expected.items()
        if getattr(scenario.synthesis, key) != value
    ]


def _simulator_model(factory: SimulatedUserFactory, scenario: JourneyScenario) -> str | None:
    """Build one Simulated user before any write, only to surface missing
    configuration. Any other failure belongs to the Episode it happens in,
    where it is recorded as ``error`` and the next Scenario still runs."""
    try:
        return getattr(factory(scenario), "model", None)
    except SimulatorConfigError:
        raise
    except Exception:
        return None


def _probe_agent(adapter: ConversationAdapter, fixture_state: FixtureState) -> str:
    """Which agent answers, learned before anything is written: a Run or a Probe
    against the stub must never be mistaken for one against the LangGraph
    agent."""
    handle = adapter.start_conversation(fixture_state=fixture_state)
    adapter.release(handle)
    return handle.agent


def _unusable(command: str, error: BaseException, out: TextIO) -> int:
    print(f"{command}: {' '.join(str(error).split())}", file=out)
    return 2


# -------------------------------------------------------------------- probe


def probe_command(
    *,
    journey_dir: str | Path,
    scenarios_dir: str | Path,
    service_url: str,
    probe_id: str,
    output_root: str | Path = DEFAULT_PROBE_ROOT,
    seeds: Sequence[int] = (0,),
    simulator_model: str | None = None,
    enforce_model_family_separation: bool = False,
    request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
    episode_timeout_s: float = DEFAULT_TIME_LIMIT_S,
    out: TextIO,
    adapter: ConversationAdapter | None = None,
    simulated_user_factory: SimulatedUserFactory | None = None,
    judge: EpisodeJudge | None = None,
) -> int:
    """The body of ``journey_harness.py probe``: climb one realized Ladder
    against the agent service (ADR 0008).

    This is the plumbing ``climb`` deliberately does not hold. ``climb`` owns
    the decision — go up while a Rung is survived, stop at the first that is not
    — and is handed a ``play`` that turns one (Rung, Seed) into a Verdict. Here
    that ``play`` is an ordinary Episode followed by ordinary evaluation:
    nothing about a Rung reaches ``run_episode`` or ``evaluate_episode``, which
    see a Synthesized Journey Scenario like any other.

    Every Rung of the Ladder must be realized in ``scenarios_dir`` before
    anything is played: a Ladder missing a Rung is not a shorter Ladder.
    ``adapter``, ``simulated_user_factory`` and ``judge`` are for tests."""
    journey_dir, scenarios_dir = Path(journey_dir), Path(scenarios_dir)
    probe_dir = Path(output_root) / probe_id
    try:
        if not _RUN_ID.match(probe_id):
            raise ValueError(f"probe id {probe_id!r} must match {_RUN_ID.pattern}")
        seeds = tuple(seeds)
        if not seeds:
            raise ValueError("a Probe needs at least one Seed")
        if len(set(seeds)) != len(seeds):
            raise ValueError(f"Seeds must be distinct, got {list(seeds)}")
        journey, fixture_state = load_journey_inputs(journey_dir)
        scenarios = _load_verified_set(scenarios_dir, journey_dir, journey, fixture_state)
        ladder, by_rung = _ladder_set(scenarios, scenarios_dir)
        if probe_dir.exists():
            raise ValueError(f"{probe_dir} already exists; a Probe is never overwritten")
        if simulated_user_factory is None:
            def simulated_user_factory(scenario: JourneyScenario) -> SimulatedUser:
                return live_simulated_user(scenario, journey, model=simulator_model)
        simulator = _simulator_model(simulated_user_factory, by_rung[1])
        if judge is None:
            judge = live_journey_judge(
                journey,
                simulator_model=simulator,
                enforce_model_family_separation=enforce_model_family_separation,
            )
        if adapter is None:
            adapter = JourneyServiceAdapter(service_url, request_timeout_s=request_timeout_s)
        agent = _probe_agent(adapter, fixture_state)
    except (OSError, ValueError, KeyError, TypeError, AdapterError) as error:
        return _unusable("probe", error, out)

    print(
        f"Probe {probe_id!r}: Ladder {ladder.set_id!r} against required rule "
        f"{ladder.rule_id!r} of Journey {ladder.journey_id}\n"
        f"{len(ladder.rungs)} Rung(s) x {len(seeds)} Seed(s), easiest first, stopping at "
        "the first Rung not survived\n"
        f"agent: {agent} (service {service_url})\n"
        f"Simulated-user model: {simulator}; Judge model: {getattr(judge, 'model', None)}\n"
        "This reports how far the agent climbed and any SUSPECTED finding, never a Pass "
        "rate. Nothing here is confirmed: a human rules on a break.",
        file=out,
    )

    async def play(rung: int, seed: int) -> SeedResult:
        """One Seed of one Rung: an Episode, then its Verdict. Whatever this
        raises aborts the climb, which keeps every Rung already finished."""
        scenario = by_rung[rung]
        where = Path("rungs") / f"rung-{rung}" / f"seed-{seed}"
        episode_dir = probe_dir / where
        await run_episode(
            scenario,
            fixture_state=fixture_state,
            adapter=adapter,
            simulated_user=simulated_user_factory(scenario),
            episode_dir=episode_dir,
            service_url=service_url,
            time_limit_s=episode_timeout_s,
        )
        result = await evaluate_episode(episode_dir, judge, journey)
        print(
            f"[Rung {rung}/{len(ladder.rungs)} Seed {seed}] {scenario.scenario_id}: "
            f"{result.outcome} — {' '.join(result.explanation.split())}",
            file=out,
        )
        return SeedResult(
            seed=seed,
            episode_dir=where.as_posix(),
            outcome=result.outcome,
            failures=tuple(_probe_failure(failure) for failure in result.failures),
        )

    try:
        record = run_on_the_process_loop(
            climb(ladder, play=play, climb_dir=probe_dir, agent=agent, seeds=seeds)
        )
    except BaseException as error:
        print(
            f"ABORTED: {type(error).__name__}: {' '.join(str(error).split())} — what was "
            f"written is kept in {probe_dir}",
            file=out,
        )
        if not isinstance(error, Exception):
            raise  # an interrupt stays an interrupt
        return 1
    print(f"{summarize(record)}\nProbe complete: {probe_dir}", file=out)
    return 0


def _ladder_set(
    scenarios: Sequence[JourneyScenario], scenarios_dir: Path
) -> tuple[Ladder, dict[int, JourneyScenario]]:
    """The one Ladder a synthesized set realizes, and its Scenario per Rung.

    A Rung is resolved by its number, never by what its Scenario says: Rungs 3
    and 4 of the committed Ladder share two difficulty directions, so matching
    on prose would silently select the wrong one."""
    problems: list[str] = []
    set_ids: set[str] = set()
    by_rung: dict[int, JourneyScenario] = {}
    for scenario in scenarios:
        synthesis = scenario.synthesis
        try:
            ladder, spec = ladder_and_rung_for(
                {"set_id": synthesis.set_id, "spec_id": synthesis.spec_id}
            )
        except LadderError as error:
            problems.append(f"{Path(scenario.source).name}: {error}")
            continue
        set_ids.add(ladder.set_id)
        if spec.rung in by_rung:
            problems.append(f"Rung {spec.rung} is realized by more than one Scenario")
        by_rung[spec.rung] = scenario
    if problems:
        raise ValueError(f"{scenarios_dir} is not a Ladder set: " + "; ".join(problems))
    if len(set_ids) != 1:
        raise ValueError(
            f"{scenarios_dir} realizes Ladders {sorted(set_ids)}; a Probe climbs one"
        )
    ladder = LADDERS[set_ids.pop()]
    missing = [spec.rung for spec in ladder.rungs if spec.rung not in by_rung]
    if missing:
        raise ValueError(
            f"{scenarios_dir} is missing Rung(s) {missing} of Ladder {ladder.set_id!r}: "
            "a Ladder missing a Rung is not a shorter Ladder"
        )
    return ladder, by_rung


def _probe_failure(failure: FailureRecord) -> dict[str, Any]:
    """What a Seed's entry in the climb record says about one failure: which
    check failed and what it said, so the record names the break without
    restating it. The full record with its evidence stays in the Episode's
    ``evaluation.json``, which ``episode_dir`` points at."""
    return {
        "source": failure.source,
        "id": failure.id,
        "turn_index": failure.turn_index,
        "message": failure.message,
    }


# ---------------------------------------------------------------- summarize


def summarize_command(run_dir: str | Path, *, out: TextIO) -> int:
    """The body of ``journey_harness.py summarize``."""
    try:
        summary = summarize_run(run_dir)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return _unusable("summarize", error, out)
    counts = ", ".join(f"{outcome} {n}" for outcome, n in summary.outcomes.items())
    print(f"Run {summary.run_dir}: {counts}, not finished {summary.not_finished}", file=out)
    if summary.aborted:
        print(
            f"NOTE: this Run was ABORTED (status {summary.status!r}); the summary covers "
            "only what ran",
            file=out,
        )
    if summary.re_evaluation_aborted:
        print(
            f"NOTE: the last re-evaluation was ABORTED (status "
            f"{summary.re_evaluation_status!r}); Episodes it did not reach are counted as "
            "not finished — run --re-evaluate again",
            file=out,
        )
    failures = sum(cluster.size for cluster in summary.clusters)
    print(
        f"{failures} failure(s) in {len(summary.clusters)} cluster(s) of similar symptoms "
        f"(not proven common root causes)\nreport: {summary.report_path}",
        file=out,
    )
    return 0


# --------------------------------------------------------------------- main


def _positive_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        seconds = 0.0
    if seconds <= 0:
        raise argparse.ArgumentTypeError(f"{value!r} is not a positive number of seconds")
    return seconds


def _seeds(value: str) -> tuple[int, ...]:
    try:
        seeds = tuple(int(part) for part in value.split(",") if part.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a comma-separated list of Seeds"
        ) from None
    if not seeds:
        raise argparse.ArgumentTypeError("a Probe needs at least one Seed")
    if len(set(seeds)) != len(seeds):
        raise argparse.ArgumentTypeError(f"Seeds must be distinct, got {value!r}")
    return seeds


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="journey_harness.py",
        description="Synthesize Scenarios for a Journey, run them against the agent "
        "service, and summarize the Run. Nothing here establishes Judge accuracy, "
        "test quality or coverage.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    synthesize = commands.add_parser(
        "synthesize",
        help="write a small set of validated Scenarios",
        description="Synthesize Scenarios from a Journey definition and Fixture state "
        "into <output-root>/<journey_id>/<set-id>/. Validation is not Qualification. "
        "Exit 0 ok, 1 shortfall or aborted after writing, 2 unusable request.",
    )
    synthesize.add_argument("--journey", required=True, metavar="DIR",
                            help="directory holding journey.yaml and fixture_state.yaml")
    synthesize.add_argument("--count", required=True, type=int, help="Scenarios wanted")
    synthesize.add_argument("--set-id", required=True, help="new set id; never overwritten")
    synthesize.add_argument("--seed", type=int, default=0, help="planning seed (default 0)")
    synthesize.add_argument("--stub", action="store_true",
                            help="deterministic offline narrative, no model call")
    synthesize.add_argument("--model", default=None,
                            help=f"generator model (or {journey_synthesis.SYNTHESIS_MODEL_ENV})")
    synthesize.add_argument("--output-root", default=journey_synthesis.DEFAULT_OUTPUT_ROOT,
                            help="default: %(default)s")

    run = commands.add_parser(
        "run",
        help="run a saved set against the agent service, sequentially, and evaluate it",
        description="Play one Episode per accepted Scenario of a synthesized set against "
        "the agent service, one after another, and evaluate each. The set must pass its "
        "provenance check against --journey. Makes live model calls (Simulated user, "
        "Judge). With --re-evaluate, evaluates the saved Episodes of an existing Run "
        "again instead; no conversation is replayed. Exit 0 done (whatever the "
        "outcomes), 1 aborted after writing, 2 unusable request.",
    )
    run.add_argument("--journey", required=True, metavar="DIR",
                     help="the Journey directory the Scenarios were synthesized from")
    run.add_argument("--scenarios", metavar="SET_DIR",
                     help="a synthesized set directory (holds provenance.json)")
    run.add_argument("--service-url", help="the agent service, e.g. http://127.0.0.1:8765")
    run.add_argument("--run-id", help="new Run id; never overwritten")
    run.add_argument("--output-root", default=DEFAULT_RUN_ROOT, help="default: %(default)s")
    run.add_argument("--simulator-model", default=None,
                     help="Simulated-user model (or AGENTSIM_SIMULATOR_MODEL)")
    run.add_argument("--enforce-model-family-separation", action="store_true",
                     help="refuse a Simulated-user model of the Judge's family")
    run.add_argument("--request-timeout", type=_positive_seconds,
                     default=DEFAULT_REQUEST_TIMEOUT_S, metavar="SECONDS",
                     help="per request to the agent service (default %(default)s)")
    run.add_argument("--episode-timeout", type=_positive_seconds,
                     default=DEFAULT_TIME_LIMIT_S, metavar="SECONDS",
                     help="per Episode, checked between Turns (default %(default)s)")
    run.add_argument("--re-evaluate", metavar="RUN_DIR", default=None,
                     help="evaluate an existing Run's saved Episodes again")

    probe = commands.add_parser(
        "probe",
        help="climb one realized Ladder against the agent service and report how far "
        "the agent got",
        description="Play the Rungs of one realized Ladder against the agent service, "
        "easiest first, every Seed of a Rung before the next, stopping at the first Rung "
        "not survived, and write climb.json. Reports the highest Rung survived, the Rung "
        "that broke and its evidence — never a Pass rate, and nothing it reports is "
        "confirmed: a break is a suspected finding a human rules on. The set must hold "
        "every Rung of one Ladder and pass its provenance check against --journey. Makes "
        "live model calls (Simulated user, Judge). Exit 0 done (whatever the outcomes), "
        "1 aborted after writing, 2 unusable request.",
    )
    probe.add_argument("--journey", required=True, metavar="DIR",
                       help="the Journey directory the Rungs were realized from")
    probe.add_argument("--scenarios", required=True, metavar="SET_DIR",
                       help="a realized Ladder set (holds provenance.json)")
    probe.add_argument("--service-url", required=True,
                       help="the agent service, e.g. http://127.0.0.1:8765")
    probe.add_argument("--probe-id", required=True, help="new Probe id; never overwritten")
    probe.add_argument("--output-root", default=DEFAULT_PROBE_ROOT, help="default: %(default)s")
    probe.add_argument("--seeds", type=_seeds, default=(0,), metavar="N[,N...]",
                       help="Seeds played per Rung; a Rung is survived only when every "
                       "one of them is clean (default 0)")
    probe.add_argument("--simulator-model", default=None,
                       help="Simulated-user model (or AGENTSIM_SIMULATOR_MODEL)")
    probe.add_argument("--enforce-model-family-separation", action="store_true",
                       help="refuse a Simulated-user model of the Judge's family")
    probe.add_argument("--request-timeout", type=_positive_seconds,
                       default=DEFAULT_REQUEST_TIMEOUT_S, metavar="SECONDS",
                       help="per request to the agent service (default %(default)s)")
    probe.add_argument("--episode-timeout", type=_positive_seconds,
                       default=DEFAULT_TIME_LIMIT_S, metavar="SECONDS",
                       help="per Episode, checked between Turns (default %(default)s)")

    summarize = commands.add_parser(
        "summarize",
        help="cluster a Run's failures and write report.md",
        description="Write clusters.json and report.md into a Run directory: outcome "
        "counts, clusters of similar failure symptoms (not proven root causes), and "
        "links to each Episode's evidence. Says plainly when the Run was aborted.",
    )
    summarize.add_argument("run_dir", metavar="RUN_DIR", help="e.g. journey_runs/<run_id>")
    return parser


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "synthesize":
        return journey_synthesis.synthesize_command(
            journey_dir=args.journey, count=args.count, set_id=args.set_id,
            seed=args.seed, stub=args.stub, model=args.model,
            output_root=args.output_root, out=out,
        )
    if args.command == "probe":
        return probe_command(
            journey_dir=args.journey, scenarios_dir=args.scenarios,
            service_url=args.service_url, probe_id=args.probe_id,
            output_root=args.output_root, seeds=args.seeds,
            simulator_model=args.simulator_model,
            enforce_model_family_separation=args.enforce_model_family_separation,
            request_timeout_s=args.request_timeout, episode_timeout_s=args.episode_timeout,
            out=out,
        )
    if args.command == "summarize":
        return summarize_command(args.run_dir, out=out)
    fresh = {"--scenarios": args.scenarios, "--service-url": args.service_url,
             "--run-id": args.run_id}
    if args.re_evaluate is not None:
        given = [flag for flag, value in fresh.items() if value is not None]
        if given:
            parser.error(f"--re-evaluate replays nothing; it cannot take {', '.join(given)}")
        return re_evaluate_command(
            journey_dir=args.journey, run_dir=args.re_evaluate,
            enforce_model_family_separation=args.enforce_model_family_separation, out=out,
        )
    missing = [flag for flag, value in fresh.items() if value is None]
    if missing:
        parser.error(f"run needs {', '.join(missing)}")
    return run_command(
        journey_dir=args.journey, scenarios_dir=args.scenarios,
        service_url=args.service_url, run_id=args.run_id, output_root=args.output_root,
        simulator_model=args.simulator_model,
        enforce_model_family_separation=args.enforce_model_family_separation,
        request_timeout_s=args.request_timeout, episode_timeout_s=args.episode_timeout,
        out=out,
    )


if __name__ == "__main__":
    raise SystemExit(main())
