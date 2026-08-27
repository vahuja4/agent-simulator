"""Deterministic FailureRecord clustering; optional labels never assign members."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Awaitable, Callable

from ._io import _atomic_json
from .types import BatchManifest, FailureCluster

CLUSTER_SCHEMA_VERSION = "1.0"
ClusterLabeler = Callable[[FailureCluster], Awaitable[str]]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _tokens(value: Any, path: str = "$") -> frozenset[str]:
    tokens: set[str] = set()
    if isinstance(value, dict):
        if not value:
            tokens.add(f"{path}=dict:empty")
        for key in sorted(value):
            tokens.update(_tokens(value[key], f"{path}.{key}"))
    elif isinstance(value, list):
        if not value:
            tokens.add(f"{path}=list:empty")
        for index, item in enumerate(value):
            tokens.update(_tokens(item, f"{path}[{index}]"))
    else:
        tokens.add(f"{path}={type(value).__name__}:{_canonical(value)}")
    return frozenset(tokens)


def data_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _existing_labels(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return {
            str(item["membership_hash"]): str(item["label"])
            for item in data.get("clusters", [])
            if item.get("label") is not None
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def cluster_failures(
    batch_dir: str | Path, *, similarity_threshold: float = 0.6
) -> list[FailureCluster]:
    if not 0.0 <= similarity_threshold <= 1.0:
        raise ValueError("similarity_threshold must be between 0 and 1")
    batch_dir = Path(batch_dir)
    manifest = BatchManifest.from_dict(
        json.loads((batch_dir / "manifest.json").read_text())
    )
    labels = _existing_labels(batch_dir / "clusters.json")
    partitions: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for run_key in sorted(manifest.runs):
        record = manifest.runs[run_key]
        if record.status != "completed" or record.outcome != "fail":
            continue
        for index, failure in enumerate(record.failures):
            member = {
                "member_key": f"{run_key}:{index}",
                "run_key": run_key,
                "failure_index": index,
                "scenario": record.scenario,
                "persona_variant": record.persona_variant,
                "turn_index": failure.turn_index,
                "message": failure.message,
                "data": failure.data,
                "trace_path": record.trace_path,
                "transcript_path": record.transcript_path,
                "replay_path": record.replay_path,
            }
            partitions[(failure.source, failure.id)].append(member)

    clusters: list[FailureCluster] = []
    for (source, failure_id), members in sorted(partitions.items()):
        members.sort(key=lambda item: item["member_key"])
        parent = list(range(len(members)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            a, b = find(left), find(right)
            if a != b:
                parent[max(a, b)] = min(a, b)

        for left in range(len(members)):
            for right in range(left + 1, len(members)):
                if data_similarity(members[left]["data"], members[right]["data"]) >= similarity_threshold:
                    union(left, right)

        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for index, member in enumerate(members):
            grouped[find(index)].append(member)
        for group in grouped.values():
            keys = sorted(member["member_key"] for member in group)
            membership_hash = hashlib.sha256(_canonical(keys).encode()).hexdigest()
            cluster_id = f"{source}-{failure_id}-{membership_hash[:10]}"
            clusters.append(
                FailureCluster(
                    cluster_id=cluster_id,
                    source=source,
                    id=failure_id,
                    membership_hash=membership_hash,
                    members=sorted(group, key=lambda item: item["member_key"]),
                    label=labels.get(membership_hash),
                )
            )

    clusters.sort(key=lambda c: (-c.size, c.source, c.id, c.cluster_id))
    _atomic_json(
        batch_dir / "clusters.json",
        {
            "schema_version": CLUSTER_SCHEMA_VERSION,
            "similarity_threshold": similarity_threshold,
            "clusters": [cluster.to_dict() for cluster in clusters],
        },
    )
    return clusters


async def label_clusters(
    batch_dir: str | Path, labeler: ClusterLabeler
) -> list[FailureCluster]:
    batch_dir = Path(batch_dir)
    clusters_path = batch_dir / "clusters.json"
    data = json.loads(clusters_path.read_text())
    clusters = [FailureCluster.from_dict(item) for item in data.get("clusters", [])]
    calls = 0
    for cluster in clusters:
        if cluster.label is not None:
            continue
        label = (await labeler(cluster)).strip()
        if not label:
            raise ValueError(f"empty label for cluster {cluster.cluster_id}")
        cluster.label = label
        calls += 1
    data["clusters"] = [cluster.to_dict() for cluster in clusters]
    _atomic_json(clusters_path, data)

    manifest_path = batch_dir / "manifest.json"
    manifest = BatchManifest.from_dict(json.loads(manifest_path.read_text()))
    manifest.label_llm_calls += calls
    _atomic_json(manifest_path, manifest.to_dict())
    return clusters
