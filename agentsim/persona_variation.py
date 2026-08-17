"""Explicit, semantics-preserving persona overlays for batch variation.

An overlay can change only the persona's display name and append traits. It
returns a dataclass copy of the Scenario; the committed scenario object and
all goal/knowledge/evaluation fields remain untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

import yaml

from .scenario import Scenario


class PersonaOverlayError(ValueError):
    pass


@dataclass(frozen=True)
class PersonaOverlay:
    id: str
    traits_append: str
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "traits_append": self.traits_append, "name": self.name}


def load_persona_overlay(path: str | Path) -> PersonaOverlay:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise PersonaOverlayError(f"{path.name}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise PersonaOverlayError(f"{path.name}: top level must be a mapping")
    unknown = set(raw) - {"id", "name", "traits_append"}
    if unknown:
        raise PersonaOverlayError(
            f"{path.name}: persona overlay cannot change {sorted(unknown)}"
        )
    overlay_id = raw.get("id")
    traits = raw.get("traits_append")
    name = raw.get("name")
    if not isinstance(overlay_id, str) or not overlay_id.strip():
        raise PersonaOverlayError(f"{path.name}: id must be a non-empty string")
    if not isinstance(traits, str) or not traits.strip():
        raise PersonaOverlayError(
            f"{path.name}: traits_append must be a non-empty string"
        )
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise PersonaOverlayError(f"{path.name}: name must be a non-empty string")
    return PersonaOverlay(
        id=overlay_id.strip(),
        traits_append=traits.strip(),
        name=name.strip() if isinstance(name, str) else None,
    )


def load_persona_overlays(directory: str | Path) -> tuple[PersonaOverlay, ...]:
    overlays = tuple(
        load_persona_overlay(path) for path in sorted(Path(directory).glob("*.yaml"))
    )
    ids = [overlay.id for overlay in overlays]
    if len(ids) != len(set(ids)):
        raise PersonaOverlayError("persona overlay ids must be unique")
    return overlays


def apply_persona_overlay(scenario: Scenario, overlay: PersonaOverlay) -> Scenario:
    persona = replace(
        scenario.persona,
        name=overlay.name or scenario.persona.name,
        traits=f"{scenario.persona.traits}; {overlay.traits_append}",
    )
    return replace(scenario, persona=persona)


def overlay_for_run(
    overlays: Sequence[PersonaOverlay], *, seed: int, run_index: int
) -> PersonaOverlay | None:
    """Choose from base + explicit overlays by a stable, recorded schedule."""
    choices: tuple[PersonaOverlay | None, ...] = (None, *sorted(overlays, key=lambda o: o.id))
    return choices[(seed + run_index) % len(choices)]
