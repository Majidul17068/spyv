"""The recoverability ladder: what each level of analysis actually recovers.

Our headline number describes one analyser, which invites the fair objection that
it measures our implementation rather than static analysis. Reporting a single
point cannot answer that. Reporting a curve can: if recoverability keeps climbing
as the analysis strengthens, the low figure was ours; if it flattens, the residue
is a property of the programs.

Five levels, each strictly stronger than the last:

  L0  literals only            string constants, f-strings and literal
                               concatenation. A bare name is opaque.
  L1  + constant propagation   one hop through a file-wide binding map. This is
                               what the paper's headline actually measures, which
                               we had not previously stated.
  L2  + interprocedural        resolve a callee defined in the same module and
                               read its return expressions.
  L3  + import resolution      follow callees and constants across modules.
  L4  + string expressions     the forms a string analyser handles and an AST
                               walker does not: str.format, percent formatting,
                               str.join over literals, and conditionals whose
                               branches are all recoverable.

L4 matters more than it sounds. Our own class definition calls a literal skeleton
with interpolated holes `partial`, and `"You are a {} agent.".format(role)` is
exactly that -- yet levels below L4 report it opaque. The ladder makes that gap
visible instead of leaving it as an unstated conservatism.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Literal

from ..discovery import _string_bindings
from .visibility import Visibility, is_stringish

Level = Literal[0, 1, 2, 3, 4]
LEVEL_NAMES = {
    0: "literals",
    1: "+ constant propagation",
    2: "+ interprocedural",
    3: "+ import resolution",
    4: "+ string expressions",
}

# Methods that change a string's layout but not the text a model receives.
_WHITESPACE_METHODS = frozenset({"strip", "lstrip", "rstrip"})

# Functions whose result is their literal argument, modulo indentation.
_DEDENT_LIKE = frozenset({"dedent", "cleandoc"})


def _is_dedent_like(func: ast.expr) -> bool:
    """`dedent(...)`, `textwrap.dedent(...)`, or `inspect.cleandoc(...)`."""
    if isinstance(func, ast.Name):
        return func.id in _DEDENT_LIKE
    if isinstance(func, ast.Attribute):
        return func.attr in _DEDENT_LIKE
    return False

MAX_DEPTH = 3
_HOLE = "{...}"


@dataclass
class Ctx:
    """Everything a level is allowed to consult, gated by `level`."""

    level: int
    bindings: dict[str, str]
    module: Any = None      # ModuleInfo, for L3
    index: Any = None       # ProjectIndex, for L3


def _merge(vis: list[Visibility]) -> Visibility:
    """Combine sub-results: opaque dominates unless something literal survives."""
    if not vis:
        return "opaque"
    if all(v == "static" for v in vis):
        return "static"
    if any(v in ("static", "partial") for v in vis):
        return "partial"
    return "opaque"


def _returns_of(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
    return [n.value for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]


def _local_functions(tree: ast.AST) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    out: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, node)
    return out


def _callee_name(node: ast.Call) -> str:
    return getattr(node.func, "id", None) or getattr(node.func, "attr", None) or ""


def classify_at(
    node: ast.expr | None,
    ctx: Ctx,
    functions: dict[str, Any] | None = None,
    depth: int = 0,
) -> Visibility:
    """Classify one expression under the resolution powers of ctx.level."""
    if node is None or depth > MAX_DEPTH:
        return "opaque"
    functions = functions if functions is not None else {}

    # --- L0: literal forms, available at every level ------------------------
    if isinstance(node, ast.Constant):
        return "static" if isinstance(node.value, str) else "opaque"

    if isinstance(node, ast.JoinedStr):
        has_hole = any(isinstance(v, ast.FormattedValue) for v in node.values)
        has_lit = any(
            isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value.strip()
            for v in node.values
        )
        if not has_lit:
            return "opaque"
        return "partial" if has_hole else "static"

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _merge([classify_at(node.left, ctx, functions, depth + 1),
                       classify_at(node.right, ctx, functions, depth + 1)])

    # --- L4: percent formatting -- a literal template with holes ------------
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        if ctx.level >= 4:
            left = classify_at(node.left, ctx, functions, depth + 1)
            if left in ("static", "partial"):
                return "partial"
        return "opaque"

    # --- L1: one hop through the binding map --------------------------------
    if isinstance(node, (ast.Name, ast.Attribute)):
        if ctx.level >= 1:
            key = node.id if isinstance(node, ast.Name) else node.attr
            if key in ctx.bindings:
                return "partial" if _HOLE in ctx.bindings[key] else "static"
        # --- L3: constants defined in another module ------------------------
        if ctx.level >= 3 and ctx.index is not None and ctx.module is not None:
            key = node.id if isinstance(node, ast.Name) else node.attr
            found = ctx.index.resolve_constant(key, ctx.module)
            if found is not None:
                value, owner = found
                sub = Ctx(ctx.level, _string_bindings(owner.tree), owner, ctx.index)
                return classify_at(value, sub, _local_functions(owner.tree), depth + 1)
        return "opaque"

    # --- L4: a conditional whose branches are all recoverable ---------------
    if isinstance(node, ast.IfExp):
        if ctx.level >= 4:
            return _merge([classify_at(node.body, ctx, functions, depth + 1),
                           classify_at(node.orelse, ctx, functions, depth + 1)])
        return "opaque"

    if isinstance(node, ast.Call):
        func = node.func
        # --- L4: "...".format(...) and " ".join([...]) ----------------------
        if ctx.level >= 4 and isinstance(func, ast.Attribute):
            if func.attr == "format":
                base = classify_at(func.value, ctx, functions, depth + 1)
                if base in ("static", "partial"):
                    return "partial" if node.args or node.keywords else base
            if func.attr == "join":
                sep = classify_at(func.value, ctx, functions, depth + 1)
                if sep in ("static", "partial") and node.args:
                    arg = node.args[0]
                    if isinstance(arg, (ast.List, ast.Tuple)):
                        return _merge([classify_at(e, ctx, functions, depth + 1) for e in arg.elts])
                    return "opaque"
            # Whitespace normalisers over a recoverable string preserve its value
            # up to layout: "...".strip() is as readable as the literal it wraps.
            if func.attr in _WHITESPACE_METHODS:
                return classify_at(func.value, ctx, functions, depth + 1)

        # --- L4: textwrap.dedent / inspect.cleandoc over a literal ----------
        # The canonical way to write a multi-line prompt in Python. Treating it
        # as an unresolvable call placed fully-literal prompt text in the opaque
        # bucket, and that text was then described as beyond the reach of any
        # static analysis. dedent of a literal is a literal.
        if ctx.level >= 4 and _is_dedent_like(func) and node.args:
            return classify_at(node.args[0], ctx, functions, depth + 1)

        # --- L2: a callee defined in this module ----------------------------
        name = _callee_name(node)
        if ctx.level >= 2 and isinstance(func, ast.Name) and name in functions:
            rets = _returns_of(functions[name])
            if rets:
                return _merge([classify_at(r, ctx, functions, depth + 1) for r in rets])

        # --- L3: a callee in another module ---------------------------------
        if ctx.level >= 3 and ctx.index is not None and ctx.module is not None and isinstance(func, ast.Name):
            found = ctx.index.resolve_function(name, ctx.module)
            if found is not None:
                fn, owner = found
                rets = _returns_of(fn)
                if rets:
                    sub = Ctx(ctx.level, _string_bindings(owner.tree), owner, ctx.index)
                    return _merge([classify_at(r, sub, _local_functions(owner.tree), depth + 1)
                                   for r in rets])
        return "opaque"

    return "opaque"


def measure_repo(root: str | Path, level: int,  # noqa: F821
                 stratum: str | None = None) -> dict[str, int]:
    """Classify every prompt site in a repository at one rung of the ladder.

    `stratum` restricts the measurement to "production" or "scaffolding" files,
    per PROTOCOL_SCAFFOLDING.md. Pooling the two conflates populations whose
    recoverability differs by a wide margin, so the ladder has to be reported
    per stratum rather than only in aggregate.
    """
    from pathlib import Path as _P

    from .headroom import _locate_expressions
    from .project import ProjectIndex
    from .visibility import sites_in_source

    root = _P(root)
    counts: dict[str, int] = {"static": 0, "partial": 0, "opaque": 0}
    index = ProjectIndex(root) if level >= 3 else None
    modules = index.modules.values() if index else None

    if modules is None:
        from ..discovery import _SKIP_DIRS
        items = []
        for path in root.rglob("*.py"):
            if any(p in _SKIP_DIRS or p.endswith(".egg-info") for p in path.parts):
                continue
            try:
                items.append((path, path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError):
                continue
    else:
        items = []
        for mod in modules:
            try:
                items.append((mod.path, mod.path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError):
                continue

    for path, src in items:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.as_posix()
        if stratum is not None:
            from .scaffolding import classify_path
            if classify_path(rel) != stratum:
                continue
        sites = sites_in_source(src, rel)
        if not sites:
            continue
        located = _locate_expressions(tree, {(s.line, s.construct) for s in sites})
        module = index.by_path.get(path.as_posix()) if index else None
        ctx = Ctx(level, _string_bindings(tree), module, index)
        funcs = _local_functions(tree)
        for site in sites:
            expr = located.get((site.line, site.construct))
            if expr is None or not is_stringish(expr):
                counts["opaque"] += 1
                continue
            counts[classify_at(expr, ctx, funcs)] += 1
    return counts


__all__ = ["LEVEL_NAMES", "Ctx", "Level", "classify_at", "measure_repo"]
