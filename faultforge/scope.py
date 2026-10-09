"""Keeps repairs on the dependency path.

A repair should change how the application handles the dependency: the operation at risk, the
call sites, and the code they reach. A live run once accepted a patch that also made
`OrderBook.status` return "unknown" for missing orders, code no part of the payment path uses,
only to make a broken generated test pass. Every check was green, so verification alone could not
tell. This check rejects repairs that change existing functions the dependency path never reaches.

How the path is found:
- From the original code only, so a patch cannot put its own change on the path by adding a
  reference to it.
- By name, and deliberately generous: any referenced name or attribute reaches every repo function
  of that name, and import aliases resolve to what they import. A genuine fix should not be
  rejected for touching a helper the path really uses. The cost is that a common method name on
  the path (`get`, `run`) also reaches unrelated methods of that name.
- A referenced class reaches its dunder methods (`__init__`, `__exit__`, `__call__`...), which
  Python calls implicitly, but not its other methods: an annotation such as `orders: OrderBook`
  must not put every method of `OrderBook` on the path.
New functions, module-level code and docstrings are never counted as changes.
"""

import ast
from pathlib import Path

from .repair import is_app_source


def changed_functions(original: dict[str, str], patched: dict[str, str]) -> set[str]:
    """Existing functions whose code a patch changes or removes, as "path:Qual.name"."""
    changed = set()
    for path, new in patched.items():
        old = original.get(path)
        if old is None:
            continue
        before, after = _functions(old), _functions(new)
        for qual, nodes in before.items():
            if qual not in after or _code(nodes) != _code(after[qual]):
                changed.add(f"{path}:{qual}")
    return changed


def off_path_changes(
    original: dict[str, str], patched: dict[str, str], dependency, repo: Path
) -> list[str]:
    """Changed existing functions the dependency path does not reach (empty if it cannot tell)."""
    return classify_changes(original, patched, dependency, repo)[0]


def classify_changes(
    original: dict[str, str], patched: dict[str, str], dependency, repo: Path
) -> tuple[list[str], bool]:
    """(changed functions off the dependency path, whether anything on the path changed too).

    When the path is unknown nothing counts as off-path, and any change counts as on-path."""
    changed = changed_functions(original, patched)
    off_path = _off_path(changed, dependency, repo)
    return off_path, bool(changed - set(off_path))


def _off_path(changed: set[str], dependency, repo: Path) -> list[str]:
    if not changed:
        return []
    files = _source_files(repo)
    index = {
        f"{path}:{qual}": nodes
        for path, code in files.items()
        for qual, nodes in _functions(code).items()
    }
    roots = _roots(dependency, index)
    if not roots:
        return []  # the path is unknown, so the guard cannot judge; never reject on a guess
    on_path = _reachable(roots, index, _aliases(files))
    return sorted(changed - on_path)


def _roots(dependency, index: dict[str, list[ast.AST]]) -> list[str]:
    roots = [f"{site.path}:{site.function}" for site in dependency.call_sites]
    module, _, qual = dependency.operation.partition(":")
    if module and qual:
        base = module.replace(".", "/")
        for ref in index:
            path, _, ref_qual = ref.partition(":")
            if ref_qual == qual and _is_module_file(path, base):
                roots.append(ref)
    return [r for r in roots if r in index]


def _is_module_file(path: str, base: str) -> bool:
    # "a.b" is a/b.py or a/b/__init__.py, also under a source folder such as src/
    return any(
        path == name or path.endswith(f"/{name}") for name in (f"{base}.py", f"{base}/__init__.py")
    )


def _reachable(
    roots: list[str], index: dict[str, list[ast.AST]], aliases: dict[str, set[str]]
) -> set[str]:
    by_name: dict[str, set[str]] = {}
    dunders: dict[str, set[str]] = {}  # "path:Class" -> its dunder methods
    for ref in index:
        path, _, qual = ref.partition(":")
        *owner, name = qual.split(".")
        by_name.setdefault(name, set()).add(ref)
        if owner and name.startswith("__") and name.endswith("__"):
            cls = f"{path}:{'.'.join(owner)}"
            dunders.setdefault(cls, set()).add(ref)
            by_name.setdefault(owner[-1], set()).add(ref)  # naming a class reaches its dunders

    seen, queue = set(), list(roots)
    while queue:
        ref = queue.pop()
        if ref in seen:
            continue
        seen.add(ref)
        path, _, qual = ref.partition(":")
        if "." in qual:  # a reached method brings in its class's implicit methods
            queue.extend(dunders.get(f"{path}:{qual.rsplit('.', 1)[0]}", ()))
        for node in index[ref]:
            for name in _referenced_names(node):
                for target in (name, *aliases.get(name, ())):
                    queue.extend(by_name.get(target, ()))
    return seen


def _referenced_names(node: ast.AST) -> set[str]:
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def _aliases(files: dict[str, str]) -> dict[str, set[str]]:
    """Local name -> imported name, for `from x import f as g` and `import m as n`."""
    aliases: dict[str, set[str]] = {}
    for code in files.values():
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.asname:
                        aliases.setdefault(alias.asname, set()).add(alias.name.rsplit(".", 1)[-1])
    return aliases


def _functions(code: str) -> dict[str, list[ast.AST]]:
    """Every function and method, nested ones too, by qualified name. A name can hold several
    definitions (a property getter and setter, overloads), so each maps to a list."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    found: dict[str, list[ast.AST]] = {}

    def visit(body, prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.setdefault(prefix + node.name, []).append(node)
                visit(node.body, f"{prefix}{node.name}.")
            elif isinstance(node, ast.ClassDef):
                visit(node.body, f"{prefix}{node.name}.")

    visit(tree.body, "")
    return found


def _code(nodes: list[ast.AST]) -> list[str]:
    """What a definition does, ignoring its docstring, comments and formatting."""
    dumped = []
    for node in nodes:
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            if isinstance(body[0].value.value, str):
                body = body[1:]
        parts = [node.args, *node.decorator_list, *body]
        if node.returns is not None:
            parts.append(node.returns)
        dumped.append("|".join(ast.dump(p) for p in parts))
    return dumped


def _source_files(repo: Path) -> dict[str, str]:
    files = {}
    for path in sorted(repo.rglob("*.py")):
        relative = path.relative_to(repo).as_posix()
        if not is_app_source(relative):
            continue
        try:
            files[relative] = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
    return files
