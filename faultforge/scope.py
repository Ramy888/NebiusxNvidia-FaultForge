"""Keeps repairs on the dependency path.

A repair should change how the application handles the dependency: the operation at risk, the
call sites, and the code they reach. A live run once accepted a patch that also made
`OrderBook.status` return "unknown" for missing orders, code no part of the payment path uses,
only to make a broken generated test pass. Every check was green, so verification alone could not
tell. This check rejects repairs that change existing functions the dependency path never reaches.

Reachability is by name and deliberately generous (any referenced name or attribute counts), so a
genuine fix is not rejected for touching a helper the path really uses. A referenced class only
brings in its constructor: an annotation such as `orders: OrderBook` must not put every method of
`OrderBook` on the path. New functions and module-level code are always allowed.
"""

import ast
from pathlib import Path

SKIPPED_DIRS = ("tests/", ".venv/", "faultkit/")


def changed_functions(original: dict[str, str], patched: dict[str, str]) -> set[str]:
    """Existing functions whose code a patch changes or removes, as "path:Qual.name"."""
    changed = set()
    for path, new in patched.items():
        old = original.get(path)
        if old is None:
            continue
        before, after = _functions(old), _functions(new)
        for qual, node in before.items():
            if qual not in after or ast.dump(node) != ast.dump(after[qual]):
                changed.add(f"{path}:{qual}")
    return changed


def off_path_changes(
    original: dict[str, str], patched: dict[str, str], dependency, repo: Path
) -> list[str]:
    """Changed existing functions the dependency path does not reach (empty if it cannot tell)."""
    changed = changed_functions(original, patched)
    if not changed:
        return []
    versions = [_source_files(repo), patched]  # names referenced before or after the patch count
    index: dict[str, list[ast.AST]] = {}
    for files in versions:
        for path, code in files.items():
            for qual, node in _functions(code).items():
                index.setdefault(f"{path}:{qual}", []).append(node)
    roots = [r for r in _roots(dependency) if r in index]
    if not roots:
        return []  # the path is unknown, so the guard cannot judge; never reject on a guess
    on_path = _reachable(roots, index)
    return sorted(changed - on_path)


def _roots(dependency) -> list[str]:
    roots = [f"{site.path}:{site.function}" for site in dependency.call_sites]
    module, _, qual = dependency.operation.partition(":")
    if module and qual:
        base = module.replace(".", "/")
        roots += [f"{base}.py:{qual}", f"{base}/__init__.py:{qual}"]
    return roots


def _reachable(roots: list[str], index: dict[str, list[ast.AST]]) -> set[str]:
    by_name: dict[str, set[str]] = {}
    for ref in index:
        qual = ref.split(":", 1)[1]
        parts = qual.split(".")
        by_name.setdefault(parts[-1], set()).add(ref)
        if len(parts) >= 2 and parts[-1] == "__init__":
            by_name.setdefault(parts[-2], set()).add(ref)  # a class name reaches its constructor
    seen, queue = set(roots), list(roots)
    while queue:
        for node in index[queue.pop()]:
            for name in _referenced_names(node):
                for ref in by_name.get(name, ()):
                    if ref not in seen:
                        seen.add(ref)
                        queue.append(ref)
    return seen


def _referenced_names(node: ast.AST) -> set[str]:
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def _functions(code: str) -> dict[str, ast.AST]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    found: dict[str, ast.AST] = {}

    def visit(body, prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[prefix + node.name] = node
            elif isinstance(node, ast.ClassDef):
                visit(node.body, f"{prefix}{node.name}.")

    visit(tree.body, "")
    return found


def _source_files(repo: Path) -> dict[str, str]:
    files = {}
    for path in sorted(repo.rglob("*.py")):
        relative = path.relative_to(repo).as_posix()
        if relative.startswith(SKIPPED_DIRS) or "/." in f"/{relative}":
            continue
        try:
            files[relative] = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
    return files
