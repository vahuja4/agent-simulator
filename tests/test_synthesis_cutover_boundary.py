"""The legacy scenario-synthesis modules awaiting cutover may be imported only by
each other and by the one documented production edge, ``planner`` ->
``compatibility``. A new production import onto the legacy set would silently
make the cutover in ``docs/synthesis-cutover.md`` harder; the removed modules
must stay removed. See docs/solutions/synthesis-legacy-cutover-boundary.md.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "scenario_synthesis"
LEGACY = {"compatibility", "enumerate", "sample"}
ALLOWED_PRODUCTION_EDGES = {("planner", "compatibility")}
REMOVED = (
    "scenario_synthesis/realize.py",
    "scenario_synthesis/dryrun.py",
    "scripts/realize_scenarios.py",
    "scripts/dryrun_scenarios.py",
)


def _legacy_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            if node.level:
                module = f"{PACKAGE}.{module}"
            name = module.removeprefix(f"{PACKAGE}.")
            if module.startswith(PACKAGE) and name in LEGACY:
                found.add(name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.removeprefix(f"{PACKAGE}.")
                if alias.name.startswith(PACKAGE) and name in LEGACY:
                    found.add(name)
    return found


def test_removed_legacy_modules_stay_removed() -> None:
    present = [rel for rel in REMOVED if (ROOT / rel).exists()]
    assert present == [], f"removed at cutover, must not return: {present}"


def test_legacy_modules_are_imported_only_along_documented_edges() -> None:
    edges: set[tuple[str, str]] = set()
    for directory in ("agentsim", "scenario_synthesis", "scripts", "fixtures"):
        for path in (ROOT / directory).rglob("*.py"):
            importer = path.stem
            if directory == PACKAGE and importer in LEGACY:
                continue
            for target in _legacy_imports(path):
                edges.add((importer, target))
    assert edges == ALLOWED_PRODUCTION_EDGES, (
        "production code imports a legacy synthesis module outside the documented "
        f"planner -> compatibility edge: {sorted(edges - ALLOWED_PRODUCTION_EDGES)}"
    )
