import ast
import re
from pathlib import Path


MODULES = (
    "acceptance.py",
    "batch.py",
    "clustering.py",
    "persona_variation.py",
    "replay.py",
    "report.py",
)
ALLOWED_INTERNAL = {"_io", "trace", "types", "scenario", "script", "orchestrator"}
FORBIDDEN_LITERALS = (
    "selected_card",
    "PayeeList",
    "FundingAccountPicker",
    "AddOneTimePayment",
    "AddAutoPay",
    "UpdateAutoPay",
    "CancelAutoPay",
    "CancelPayment",
)


def test_phase4_modules_import_only_generic_seams_and_have_no_domain_literals():
    root = Path("agentsim")
    for name in MODULES:
        path = root / name
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                top = (node.module or "").split(".")[0]
                assert top in ALLOWED_INTERNAL, f"{name}: forbidden internal import {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("agentsim."), (
                        f"{name}: absolute internal import {alias.name}"
                    )
        for literal in FORBIDDEN_LITERALS:
            assert literal not in source, f"{name}: forbidden domain literal {literal}"
        assert not re.search(r"(?<![A-Za-z0-9_])J[1-5](?![A-Za-z0-9_])", source), (
            f"{name}: closed journey id literal"
        )
