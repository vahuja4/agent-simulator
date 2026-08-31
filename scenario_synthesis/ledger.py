"""Append-only, hash-linked rejection evidence."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .evidence import (
    EvidenceReferenceError,
    canonical_json,
    validate_evidence_reference,
)


class LedgerError(RuntimeError):
    """The rejection ledger is invalid or cannot be appended safely."""


@contextmanager
def exclusive_lock(path: str | Path, *, command: str) -> Iterator[None]:
    lock = Path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    metadata = canonical_json(
        {
            "command": command,
            "owner_pid": os.getpid(),
            "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    )
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        raise LedgerError(f"lock already exists: {lock}") from exc
    try:
        os.write(descriptor, (metadata + "\n").encode("utf-8"))
        os.close(descriptor)
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


class RejectionLedger:
    def __init__(self, output_root: str | Path) -> None:
        self.output_root = Path(output_root)
        self.path = self.output_root / "ledger/rejections.jsonl"
        self.lock_path = self.output_root / "ledger/rejections.lock"

    def records(self, *, verify_evidence: bool = True) -> tuple[Mapping[str, Any], ...]:
        records = self._read_records(verify_evidence=verify_evidence)
        self._validate_lifecycle(records)
        return records

    def _read_records(
        self, *, verify_evidence: bool = True
    ) -> tuple[Mapping[str, Any], ...]:
        if not self.path.exists():
            return ()
        records: list[Mapping[str, Any]] = []
        previous_hash: str | None = None
        previous_timestamp = ""
        event_ids: set[str] = set()
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LedgerError(f"ledger line {line_number} is invalid JSON") from exc
            if line != canonical_json(record):
                raise LedgerError(f"ledger line {line_number} is not canonical JSON")
            required = {
                "schema_version", "event_id", "timestamp", "subject_type", "subject_id",
                "cell_id", "candidate_ordinal", "lifecycle_stage", "reason_code", "detail",
                "attribution", "n_split", "evidence", "config_snapshot_hash",
                "contract_hashes", "predecessor_candidate_id", "successor_candidate_id",
                "previous_event_hash", "event_hash",
            }
            if set(record) != required:
                raise LedgerError(f"ledger line {line_number} has incomplete attribution")
            material = dict(record)
            event_hash = material.pop("event_hash")
            from .evidence import sha256_bytes
            calculated = sha256_bytes(canonical_json(material).encode("utf-8"))
            if event_hash != calculated or record["previous_event_hash"] != previous_hash:
                raise LedgerError(f"ledger line {line_number} breaks the hash chain")
            if record["event_id"] in event_ids:
                raise LedgerError(f"duplicate ledger event_id {record['event_id']}")
            if record["timestamp"] < previous_timestamp:
                raise LedgerError("ledger timestamps are not monotonic")
            if not record["attribution"] or set(record["n_split"]) != {"defects_off", "defect_on"}:
                raise LedgerError(f"ledger line {line_number} has incomplete attribution")
            if verify_evidence:
                for reference in record["evidence"]:
                    try:
                        validate_evidence_reference(
                            reference, root=self.output_root
                        )
                    except EvidenceReferenceError as exc:
                        raise LedgerError(
                            f"ledger evidence is invalid: {exc}"
                        ) from exc
            records.append(record)
            event_ids.add(record["event_id"])
            previous_hash = event_hash
            previous_timestamp = record["timestamp"]
        return tuple(records)

    def _validate_lifecycle(self, records: Sequence[Mapping[str, Any]]) -> None:
        invalidations = {
            str(record["subject_id"]): str(record["timestamp"])
            for record in records
            if record["subject_type"] == "qualification"
            and record["lifecycle_stage"] == "admission-invalidation"
            and record["reason_code"] == "harness-fault"
        }
        candidates = self.output_root / "candidates"
        for terminal_path in candidates.glob("candidate-*/terminal.json"):
            try:
                terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise LedgerError(
                    f"candidate terminal is invalid: {terminal_path.parent.name}"
                ) from exc
            if terminal.get("status") != "admitted":
                continue
            qualification_id = str(terminal.get("qualification_id", ""))
            terminal_at = str(terminal.get("terminal_at", ""))
            conflicts = [
                record
                for record in records
                if record["subject_type"] == "qualification"
                and record["subject_id"] == qualification_id
                and record["lifecycle_stage"] != "admission-invalidation"
                and record["timestamp"] > terminal_at
            ]
            invalidated_at = invalidations.get(qualification_id)
            if conflicts and (
                invalidated_at is None
                or invalidated_at < max(str(item["timestamp"]) for item in conflicts)
            ):
                raise LedgerError(
                    "admitted candidate has a post-admission rejection event: "
                    f"{terminal_path.parent.name}"
                )

    def append(
        self,
        *,
        subject_type: str,
        subject_id: str,
        cell_id: str,
        candidate_ordinal: int | None,
        lifecycle_stage: str,
        reason_code: str,
        detail: str,
        attribution: Sequence[Mapping[str, Any]],
        n_split: Mapping[str, int],
        evidence: Sequence[Mapping[str, str]],
        config_snapshot_hash: str,
        contract_hashes: Mapping[str, str],
        predecessor_candidate_id: str | None = None,
        successor_candidate_id: str | None = None,
        timestamp: str | None = None,
        _repair_lifecycle: bool = False,
    ) -> Mapping[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.lock_path, command="append-rejection-ledger"):
            existing = (
                self._read_records()
                if _repair_lifecycle
                else self.records()
            )
            duplicate = next(
                (
                    item
                    for item in existing
                    if item["subject_type"] == subject_type
                    and item["subject_id"] == subject_id
                    and item["lifecycle_stage"] == lifecycle_stage
                ),
                None,
            )
            if duplicate is not None:
                if duplicate["reason_code"] != reason_code:
                    raise LedgerError("subject already has a different rejection event")
                return duplicate
            material: dict[str, Any] = {
                "schema_version": 1,
                "event_id": "",
                "timestamp": timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "subject_type": subject_type,
                "subject_id": subject_id,
                "cell_id": cell_id,
                "candidate_ordinal": candidate_ordinal,
                "lifecycle_stage": lifecycle_stage,
                "reason_code": reason_code,
                "detail": detail,
                "attribution": [dict(item) for item in attribution],
                "n_split": dict(n_split),
                "evidence": [dict(item) for item in evidence],
                "config_snapshot_hash": config_snapshot_hash,
                "contract_hashes": dict(contract_hashes),
                "predecessor_candidate_id": predecessor_candidate_id,
                "successor_candidate_id": successor_candidate_id,
                "previous_event_hash": existing[-1]["event_hash"] if existing else None,
            }
            from .evidence import sha256_bytes
            identity = sha256_bytes(canonical_json(material).encode("utf-8"))
            material["event_id"] = "rejection-" + identity
            event_hash = sha256_bytes(canonical_json(material).encode("utf-8"))
            record = {**material, "event_hash": event_hash}
            self._validate_lifecycle((*existing, record))
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(canonical_json(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return record


def qualification_admission_is_invalidated(
    records: Sequence[Mapping[str, Any]], qualification_id: str
) -> bool:
    return any(
        record["subject_type"] == "qualification"
        and record["subject_id"] == qualification_id
        and record["lifecycle_stage"] == "admission-invalidation"
        and record["reason_code"] == "harness-fault"
        for record in records
    )


def candidate_rejection_is_invalidated(
    records: Sequence[Mapping[str, Any]], candidate_id: str
) -> bool:
    """Whether a harness fault supersedes a Candidate rejection for accounting."""
    return any(
        record["subject_type"] == "candidate"
        and record["subject_id"] == candidate_id
        and record["lifecycle_stage"] == "qualification-invalidation"
        and record["reason_code"] == "harness-fault"
        for record in records
    )
