"""Deterministic clean-up of model-written Python before it is run.

Live runs showed small models emitting literal "\\n" escapes, inconsistently indented blocks and
forgotten imports of the application's own classes. These are fixed mechanically rather than by
asking the model again.
"""

import ast
import builtins
import re
import textwrap
from pathlib import Path

from .repair import collect_source_files

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.DOTALL)


def extract_code(raw) -> str:
    """The first fenced code block in a model answer, or the whole answer if there is none."""
    text = _THINK.sub("", str(raw))
    match = _FENCE.search(text)
    return match.group(1) if match else text


def normalize_code(text) -> str:
    code = str(text)
    if "\n" not in code.strip("\n") and "\\n" in code:
        code = code.replace("\\n", "\n")
    return textwrap.dedent(code).strip("\n")


def top_level_symbols(source: Path) -> dict[str, str]:
    """Map each unambiguous top-level class/function name to the module defining it."""
    seen: dict[str, set[str]] = {}
    for path, code in collect_source_files(source).items():
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue
        module = path.removesuffix(".py").removesuffix("/__init__").replace("/", ".")
        for node in tree.body:
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                seen.setdefault(node.name, set()).add(module)
    return {name: next(iter(mods)) for name, mods in seen.items() if len(mods) == 1}


def add_missing_imports(code: str, symbols: dict[str, str]) -> str:
    tree = ast.parse(code)
    bound = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            bound.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            bound.add(node.name)
            if not isinstance(node, ast.ClassDef):
                bound.update(a.arg for a in node.args.args + node.args.kwonlyargs)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    missing = sorted(name for name in used - bound if name in symbols)
    if not missing:
        return code
    lines = code.splitlines()
    last_import = max(
        (n.end_lineno for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)), default=0
    )
    added = [
        f"import {name}" if symbols[name] == name else f"from {symbols[name]} import {name}"
        for name in missing
    ]
    return "\n".join(lines[:last_import] + added + lines[last_import:]) + "\n"
