"""How much of the opaque prompt surface could a better static analyzer recover?

Our visibility metric reports what AST-level literal extraction reaches -- which
is what deployed prompt tooling actually does. The obvious objection is that a
sound string analyzer in the tradition of Christensen et al. (SAS 2003) or
Wassermann and Su (ICSE 2007) would resolve far more, so the number describes our
analyzer rather than static analysis. That objection is fair, and this module
answers it with a bound instead of an argument.

Every opaque site is sorted into one of three buckets:

  reachable       a stronger but still ordinary static analysis would resolve it:
                  the value comes from a function defined in the same file whose
                  returns are all literals, or from an attribute assigned a
                  literal in the same class. This is headroom -- our number is
                  pessimistic by exactly this much.

  runtime_bound   the text depends on data that does not exist until the program
                  runs: a parameter, a request, a database row, a file, an
                  environment variable. No string analyzer can produce this text;
                  the best any sound analysis can do is over-approximate it. This
                  is the irreducible floor, and it is the number that survives the
                  objection.

  undetermined    neither could be established within the bounds of this analysis
                  (cross-module, dynamic dispatch, deep chains). Reported
                  separately rather than assigned to whichever bucket flatters
                  the result.

The point of the split is that `runtime_bound` is a property of the program, not
of the tool examining it.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..discovery import _SKIP_DIRS, _string_bindings
from .visibility import classify, is_stringish, sites_in_source

Bucket = Literal["reachable", "runtime_bound", "undetermined"]

# Calls whose result is only known at run time. Prompt text derived from any of
# these cannot be recovered by any static analysis, only over-approximated.
_IO_HINTS = (
    "open", "read", "load", "loads", "get", "post", "fetch", "query", "execute",
    "getenv", "environ", "input", "request", "recv", "download", "search",
    "retrieve", "invoke", "predict", "generate", "complete", "embed",
)


@dataclass
class OpaqueVerdict:
    file: str
    line: int
    construct: str
    reason: str
    bucket: Bucket
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "construct": self.construct,
            "reason": self.reason,
            "bucket": self.bucket,
            "detail": self.detail,
        }


def _looks_like_io(node: ast.Call) -> str | None:
    name = (getattr(node.func, "id", None) or getattr(node.func, "attr", None) or "").lower()
    for hint in _IO_HINTS:
        # Exact name or a `hint_*` prefix only. An `*_hint` suffix rule matched
        # names like `make_from_input` on "input", producing the right verdict
        # for the wrong reason -- and a heuristic that is right by accident is
        # not evidence.
        if name == hint or name.startswith(hint + "_"):
            return name
    return None


class _Index:
    """Function, method and attribute definitions in one module."""

    def __init__(self, tree: ast.AST) -> None:
        self.functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self.attributes: dict[str, list[ast.expr]] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions[node.name] = node
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                        self.attributes.setdefault(t.attr, []).append(node.value)


def _returns_of(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
    out: list[ast.expr] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and node.value is not None:
            out.append(node.value)
    return out


def _param_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    a = fn.args
    names = {p.arg for p in [*a.posonlyargs, *a.args, *a.kwonlyargs]}
    if a.vararg:
        names.add(a.vararg.arg)
    if a.kwarg:
        names.add(a.kwarg.arg)
    return names - {"self", "cls"}


def _depends_on_runtime(expr: ast.expr, params: set[str]) -> str | None:
    """Does this expression's text depend on something only known at run time?"""
    for node in ast.walk(expr):
        if isinstance(node, ast.Name) and node.id in params:
            return f"parameter:{node.id}"
        if isinstance(node, ast.Call):
            io = _looks_like_io(node)
            if io:
                return f"io:{io}"
        if isinstance(node, ast.Attribute) and node.attr.lower() in {"environ", "args", "body", "json"}:
            return f"external:{node.attr}"
    return None


def _judge_call(node: ast.Call, index: _Index, bindings: dict[str, str]) -> tuple[Bucket, str]:
    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
    fn = index.functions.get(name or "")
    if fn is None:
        # The definition is not visible, so the name is all there is to go on.
        # Used only as a fallback: reading the body is evidence, guessing from
        # the identifier is not.
        io = _looks_like_io(node)
        if io:
            return "runtime_bound", f"io_call_by_name:{io}"
        return "undetermined", "callee_not_in_module"

    returns = _returns_of(fn)
    if not returns:
        return "undetermined", "no_return_found"

    params = _param_names(fn)
    local = _string_bindings(fn)
    merged = {**bindings, **local}

    runtime_reasons: list[str] = []
    all_resolvable = True
    for r in returns:
        dep = _depends_on_runtime(r, params)
        if dep:
            runtime_reasons.append(dep)
            continue
        vis, _ = classify(r, merged)
        if vis == "opaque":
            all_resolvable = False

    if runtime_reasons:
        return "runtime_bound", f"return_depends_on:{runtime_reasons[0]}"
    if all_resolvable:
        return "reachable", "callee_returns_literals"
    return "undetermined", "callee_returns_opaque"


def _judge_attribute(attr: str, index: _Index, bindings: dict[str, str]) -> tuple[Bucket, str]:
    assigned = index.attributes.get(attr)
    if not assigned:
        return "undetermined", "attribute_not_assigned_in_module"
    for value in assigned:
        if isinstance(value, ast.Call):
            io = _looks_like_io(value)
            if io:
                return "runtime_bound", f"attribute_from_io:{io}"
        vis, _ = classify(value, bindings)
        if vis == "opaque":
            return "undetermined", "attribute_value_opaque"
    return "reachable", "attribute_assigned_literal"


def analyze_source(source: str, path: str) -> list[OpaqueVerdict]:
    """Bucket every opaque prompt site in one module."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    opaque = {(s.line, s.construct): s for s in sites_in_source(source, path) if s.visibility == "opaque"}
    if not opaque:
        return []

    index = _Index(tree)
    bindings = _string_bindings(tree)
    verdicts: list[OpaqueVerdict] = []

    def record(site: Any, bucket: Bucket, detail: str) -> None:
        verdicts.append(
            OpaqueVerdict(
                file=path, line=site.line, construct=site.construct,
                reason=site.reason, bucket=bucket, detail=detail,
            )
        )

    # Map each opaque site to the expression it actually points at. Matching on
    # line number alone is wrong: `t = Task(description=f(), ...)` puts the
    # Assign value, the Task call and the keyword value all on one line, and the
    # outermost of those is not the prompt expression.
    located: dict[tuple[int, str], ast.expr] = {}
    handled: set[tuple[int, str]] = set()

    def offer(line: int, construct: str, expr: ast.expr | None) -> None:
        if expr is None or (line, construct) not in opaque:
            return
        located.setdefault((line, construct), expr)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            callee = getattr(node.func, "id", None) or getattr(node.func, "attr", None) or ""
            for arg_name, value in kwargs.items():
                line = getattr(value, "lineno", node.lineno)
                for construct in (
                    f"Agent.{arg_name}",
                    f"Task.{arg_name}",
                    f"kwarg.{arg_name}",
                ):
                    offer(line, construct, value)
            first = kwargs.get("content") or kwargs.get("template") or (node.args[0] if node.args else None)
            if first is not None:
                offer(getattr(first, "lineno", node.lineno), callee, first)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                name = getattr(t, "id", None) or getattr(t, "attr", None)
                if name:
                    offer(node.lineno, f"const.{name}", node.value)
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values, strict=False):
                if isinstance(k, ast.Constant) and k.value == "content":
                    offer(getattr(v, "lineno", node.lineno), "message.system", v)
        elif isinstance(node, ast.Tuple) and len(node.elts) >= 2:
            offer(getattr(node.elts[1], "lineno", node.lineno), "system_tuple", node.elts[1])

    for (line, construct), site in opaque.items():
        expr = located.get((line, construct))
        if expr is None or not is_stringish(expr):
            continue
        if isinstance(expr, ast.Call):
            bucket, detail = _judge_call(expr, index, bindings)
        elif isinstance(expr, ast.Attribute):
            bucket, detail = _judge_attribute(expr.attr, index, bindings)
        elif isinstance(expr, ast.Subscript):
            bucket, detail = "runtime_bound", "subscript_of_runtime_value"
        elif isinstance(expr, ast.Name):
            bucket, detail = "undetermined", "name_not_resolved_in_module"
        else:
            bucket, detail = "undetermined", f"expr:{type(expr).__name__}"
        record(site, bucket, detail)
        handled.add((line, construct))

    for (line, construct), site in opaque.items():
        if (line, construct) not in handled:
            record(site, "undetermined", "site_expression_not_located")
    return verdicts


def run_headroom(root: str | Path, *, name: str | None = None) -> dict[str, Any]:
    root_path = Path(root)
    verdicts: list[OpaqueVerdict] = []
    for path in root_path.rglob("*.py"):
        if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            rel = path.relative_to(root_path).as_posix()
        except ValueError:
            rel = path.as_posix()
        verdicts.extend(analyze_source(source, rel))

    buckets = Counter(v.bucket for v in verdicts)
    total = len(verdicts)
    return {
        "name": name or root_path.name,
        "opaque_sites": total,
        "buckets": dict(buckets),
        "reachable_share": buckets["reachable"] / total if total else 0.0,
        "runtime_bound_share": buckets["runtime_bound"] / total if total else 0.0,
        "undetermined_share": buckets["undetermined"] / total if total else 0.0,
        "details": dict(Counter(v.detail for v in verdicts).most_common(12)),
    }


__all__ = ["Bucket", "OpaqueVerdict", "analyze_source", "run_headroom"]
