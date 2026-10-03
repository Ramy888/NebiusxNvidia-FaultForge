"""Find outbound HTTP calls statically, then let the reasoning model name what is at risk."""

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .events import EventLog
from .llm import LLM, LLMError, parse_json
from .repair import collect_source_files

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "request", "send", "stream"}

ANALYSIS_SYSTEM = """You review a Python backend for reliability against HTTP dependency failures.
You get the application source and a list of outbound HTTP call sites found statically.
For each external dependency, name it, pick the call site, and name the user-facing operation
whose correctness depends on it (module:Class.method or module:function).
Respond with JSON only:
{"dependencies": [{"name": "...", "call_site": "path.py:Qualified.name",
  "operation": "module:Class.method", "notes": "existing retry/timeout/error handling"}]}"""


@dataclass(frozen=True)
class CallSite:
    path: str
    line: int
    function: str
    method: str
    target: str

    @property
    def ref(self) -> str:
        return f"{self.path}:{self.function}"


@dataclass(frozen=True)
class Dependency:
    name: str
    operation: str
    notes: str
    call_sites: list[CallSite] = field(default_factory=list)


def find_http_call_sites(source: Path) -> list[CallSite]:
    sites = []
    for path, code in collect_source_files(source).items():
        tree = ast.parse(code)
        if not _imports_httpx(tree):
            continue
        sites.extend(_Visitor(path).collect(tree))
    return sites


def discover(llm: LLM, source: Path, events: EventLog) -> list[Dependency]:
    sites = find_http_call_sites(source)
    if not sites:
        events.emit("no_dependencies", reason="no outbound httpx calls found")
        return []
    events.emit("call_sites_found", sites=[s.ref for s in sites])
    listing = "\n".join(f"- {s.ref} (line {s.line}): {s.method.upper()} {s.target}" for s in sites)
    sources = "\n\n".join(
        f"### {p}\n```python\n{c}```" for p, c in collect_source_files(source).items()
    )
    try:
        data = parse_json(
            llm.complete(
                "plan", ANALYSIS_SYSTEM, f"## Call sites\n{listing}\n\n## Source\n{sources}"
            )
        )
    except LLMError as error:
        events.emit("discovery_failed", reason=str(error))
        return []

    by_ref = {s.ref: s for s in sites}
    dependencies = []
    for item in data.get("dependencies", []):
        site = by_ref.get(str(item.get("call_site", "")))
        if site is None:
            continue
        dependencies.append(
            Dependency(
                name=str(item.get("name", "dependency")),
                operation=str(item.get("operation", "")),
                notes=str(item.get("notes", "")),
                call_sites=[site],
            )
        )
    events.emit("dependencies_found", dependencies=[d.name for d in dependencies])
    return dependencies


def _imports_httpx(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name == "httpx" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "httpx":
            return True
    return False


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path, self.scope, self.sites = path, [], []

    def collect(self, tree: ast.Module) -> list[CallSite]:
        self.visit(tree)
        return self.sites

    def _scoped(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _scoped

    def visit_Call(self, node: ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in HTTP_METHODS and self.scope:
            target = ast.unparse(node.args[0]) if node.args else ""
            if _looks_like_http(func, target):
                self.sites.append(
                    CallSite(self.path, node.lineno, ".".join(self.scope), func.attr, target)
                )
        self.generic_visit(node)


def _looks_like_http(func: ast.Attribute, target: str) -> bool:
    """Filter out dict.get() and friends: require httpx.<m>(), a URL-ish target, or a client."""
    receiver = ast.unparse(func.value)
    if receiver == "httpx":
        return True
    if any(token in target for token in ("http", "url", "/", "base")):
        return True
    return any(token in receiver.lower() for token in ("http", "client", "session"))
