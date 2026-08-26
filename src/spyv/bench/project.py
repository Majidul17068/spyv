"""A whole-repository index, so a callee in another file can be followed.

The module-local headroom analysis left 86.5% of opaque prompt sites
undetermined, and the two dominant causes were simply that the callee or the
name lived in a different file. Answering the objection that our visibility
number measures our analyzer rather than static analysis requires following
those edges, which is what this builds: a dotted-module index plus import
resolution, in the spirit of the string-analysis work the objection points at,
scoped to what a repository-local analysis can see.

Deliberate boundaries, stated because they bound every number derived from this:

  * Attribute calls on a value whose type is unknown (`obj.method()`) are not
    resolved. Doing so needs type inference, which is out of scope, so they stay
    undetermined rather than being guessed.
  * Star imports are not expanded.
  * Resolution is bounded in depth; a longer chain is reported as such rather
    than followed until it happens to terminate.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from ..discovery import _SKIP_DIRS

MAX_DEPTH = 3


@dataclass
class ModuleInfo:
    dotted: str
    path: Path
    tree: ast.AST
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(default_factory=dict)
    assigns: dict[str, ast.expr] = field(default_factory=dict)
    attributes: dict[str, list[ast.expr]] = field(default_factory=dict)
    # local name -> (module dotted path, original name). An empty name means the
    # local name refers to the module itself.
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)


def _dotted_name(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_relative(current: str, module: str | None, level: int) -> str:
    """Turn `from ..pkg import x` inside a.b.c into an absolute dotted path."""
    base = current.split(".")
    # level 1 means the current package, so drop the module's own name first.
    drop = level if level > 0 else 0
    base = base[: max(0, len(base) - drop)]
    if module:
        base = [*base, *module.split(".")]
    return ".".join(p for p in base if p)


def _collect(module: ModuleInfo) -> None:
    for node in ast.walk(module.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module.functions.setdefault(node.name, node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    module.assigns.setdefault(t.id, node.value)
                elif isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                    module.attributes.setdefault(t.attr, []).append(node.value)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                module.imports[local] = (alias.name, "")
        elif isinstance(node, ast.ImportFrom):
            target = (
                _resolve_relative(module.dotted, node.module, node.level)
                if node.level
                else (node.module or "")
            )
            for alias in node.names:
                if alias.name == "*":
                    continue
                module.imports[alias.asname or alias.name] = (target, alias.name)


class ProjectIndex:
    """Every Python module in one repository, with imports resolved between them."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.modules: dict[str, ModuleInfo] = {}
        self.by_path: dict[str, ModuleInfo] = {}
        self.parse_failures = 0
        self._build()

    def _build(self) -> None:
        for path in self.root.rglob("*.py"):
            if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
                continue
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
                self.parse_failures += 1
                continue
            try:
                dotted = _dotted_name(path, self.root)
            except ValueError:
                continue
            info = ModuleInfo(dotted=dotted, path=path, tree=tree)
            _collect(info)
            self.modules[dotted] = info
            self.by_path[path.as_posix()] = info

    def module_for(self, rel_path: str) -> ModuleInfo | None:
        return self.by_path.get((self.root / rel_path).as_posix())

    def _lookup_module(self, dotted: str) -> ModuleInfo | None:
        if dotted in self.modules:
            return self.modules[dotted]
        # A repository is often rooted one level down (src/pkg, or pkg/pkg), so
        # try progressively shorter suffixes of the dotted path.
        parts = dotted.split(".")
        for i in range(1, len(parts)):
            candidate = ".".join(parts[i:])
            if candidate in self.modules:
                return self.modules[candidate]
        return None

    def resolve_function(
        self, name: str, origin: ModuleInfo, depth: int = 0
    ) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ModuleInfo] | None:
        """Find the definition of `name` as called from `origin`."""
        if depth > MAX_DEPTH:
            return None
        if name in origin.functions:
            return origin.functions[name], origin
        imported = origin.imports.get(name)
        if imported is None:
            return None
        module_dotted, original = imported
        target = self._lookup_module(module_dotted)
        if target is None:
            return None
        if not original:
            return None
        if original in target.functions:
            return target.functions[original], target
        # Re-exported through another module (a package __init__, typically).
        return self.resolve_function(original, target, depth + 1)

    def resolve_constant(
        self, name: str, origin: ModuleInfo, depth: int = 0
    ) -> tuple[ast.expr, ModuleInfo] | None:
        if depth > MAX_DEPTH:
            return None
        if name in origin.assigns:
            return origin.assigns[name], origin
        imported = origin.imports.get(name)
        if imported is None:
            return None
        module_dotted, original = imported
        target = self._lookup_module(module_dotted)
        if target is None or not original:
            return None
        if original in target.assigns:
            return target.assigns[original], target
        return self.resolve_constant(original, target, depth + 1)

    def stats(self) -> dict[str, int]:
        return {
            "modules": len(self.modules),
            "functions": sum(len(m.functions) for m in self.modules.values()),
            "imports": sum(len(m.imports) for m in self.modules.values()),
            "parse_failures": self.parse_failures,
        }


__all__ = ["MAX_DEPTH", "ModuleInfo", "ProjectIndex"]
