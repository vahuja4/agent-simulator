from __future__ import annotations

import json
from pathlib import Path

import yaml

from scenario_synthesis import planner
from scenario_synthesis.planner import (
    build_obligation_inventory,
    build_plan,
    write_plan_report,
)


def test_current_obligation_inventory_never_reads_historical_quarantine(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        planner,
        "read_historical_quarantine",
        lambda: (_ for _ in ()).throw(AssertionError("Historical quarantine read")),
    )

    inventory = build_obligation_inventory()

    assert len(inventory.eligible_cell_specs) == 4368
    assert inventory.obligations


def test_default_eligibility_and_all_obligation_kinds_are_reported() -> None:
    plan = build_plan()
    kinds = {record.kind for record in plan.obligations}
    assert kinds == {"axis", "pair", "journey-edge", "known-defect", "eligible-cell"}
    assert plan.eligible_cell_count == 4368
    assert not [record for record in plan.obligations if record.status == "covered"]
    blocked_journeys = {
        record.axes["journey"]
        for record in plan.obligations
        if record.obligation_id.endswith("graph-not-authored")
    }
    assert blocked_journeys == {"J2", "J3", "J4", "J5"}


def test_blocked_and_uncovered_are_never_pooled() -> None:
    plan = build_plan()
    blocked = {record.obligation_id for record in plan.obligations if record.status == "BLOCKED"}
    uncovered = {record.obligation_id for record in plan.obligations if record.status == "UNCOVERED"}
    assert blocked
    assert uncovered
    assert blocked.isdisjoint(uncovered)
    assert plan.counts["BLOCKED"] == len(blocked)
    assert plan.counts["UNCOVERED"] == len(uncovered)


def test_reviewed_exclusions_are_honored_and_not_in_eligible_totals() -> None:
    plan = build_plan()
    assert plan.counts["excluded"] == 32
    assert len([record for record in plan.obligations if record.exclusion]) == 32


def test_prototype_reconciliation_is_complete_and_single_classified() -> None:
    records = build_plan().prototype_reconciliation
    assert len(records) == 10
    assert len({record.pair_id for record in records}) == len(records)
    assert {record.classification for record in records} == {"excluded-with-adr-0004-code"}
    assert {record.reason_code for record in records} == {
        "approved-contract-contradiction"
    }


def test_historical_quarantine_supplies_no_coverage_or_fitness_evidence() -> None:
    plan = build_plan()
    assert plan.historical_quarantine["candidate_count"] == 0
    assert plan.historical_quarantine["admission_count"] == 0
    assert plan.historical_quarantine["fitness_evidence_count"] == 0
    assert not [record for record in plan.obligations if record.status == "covered"]


def test_planner_and_report_bundle_are_deterministic(tmp_path: Path) -> None:
    first = build_plan(generated_at="2026-08-26T00:00:00Z")
    second = build_plan(generated_at="2026-08-26T00:00:00Z")
    assert first.to_dict() == second.to_dict()

    bundle = write_plan_report(
        tmp_path,
        report_id="test-plan",
        generated_at="2026-08-26T00:00:00Z",
    )
    coverage = json.loads((bundle / "coverage.json").read_text())
    markdown = (bundle / "coverage.md").read_text()
    snapshot = yaml.safe_load((bundle / "config-snapshot.yaml").read_text())
    assert coverage["eligible_cell_count"] == 4368
    assert coverage["snapshot_hash"] == snapshot["snapshot_hash"]
    assert "Prototype eligibility reconciliation" in markdown
    assert "4368" in markdown
