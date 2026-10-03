"""Failure scenarios: executable pytest files that use the fault kit."""

import ast
from pathlib import Path

from .models import Scenario

FAULT_CLASSES = {
    "Timeout": "timeout",
    "RateLimit": "rate_limit",
    "Malformed": "malformed",
    "DuplicateDelivery": "duplicate_delivery",
}


def scenario_from_file(path: Path) -> Scenario:
    code = path.read_text()
    tree = ast.parse(code)
    docstring = (ast.get_docstring(tree) or path.stem).strip().splitlines()[0]
    title = docstring.split(":", 1)[-1].strip()
    used = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "faultkit"
        for alias in node.names
    }
    faults = [fault for name, fault in FAULT_CLASSES.items() if name in used]
    return Scenario(
        id=path.stem, title=title, fault=faults[0] if faults else "unknown", test_code=code
    )
