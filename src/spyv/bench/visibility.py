"""Static prompt visibility: how much prompt surface can a static analyzer recover?

Implements the metric defined in METRICS.md, which was committed before this
file existed so the definition could not be fitted to the result.

The design turns on one observation: a prompt *site* is statically identifiable
even when its *argument* is not. `Task(description=self._build())` is plainly a
prompt site -- the construct is right there in the AST -- but its content cannot
be recovered without running the program. So sites are the denominator and
content resolvability is what gets classified, which means the metric needs no
hand-labelled ground truth.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..discovery import _SKIP_DIRS, _name_matches, _string_bindings

Visibility = Literal["static", "partial", "opaque"]

# Construct -> the keyword arguments that framework treats as instruction text.
_CREWAI_AGENT = {"role", "goal", "backstory"}
_CREWAI_TASK = {"description", "expected_output"}
_CREWAI_TASK_CALLS = {"Task", "ConditionalTask"}
_CREWAI_AGENT_CALLS = {"Agent"}
_LANGCHAIN_CALLS = {
    "SystemMessage",
    "SystemMessagePromptTemplate",
    "ChatPromptTemplate",
    "PromptTemplate",
}
# Generic kwargs any framework may use for an instruction.
_GENERIC_PROMPT_KWARGS = {
    "system_prompt",
    "system_message",
    "system_instruction",
    "instructions",
    "preamble",
    "persona",
}


@dataclass
class PromptSite:
    """One source location that supplies instruction text to a model."""

    file: str
    line: int
    framework: str
    construct: str
    visibility: Visibility
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "framework": self.framework,
            "construct": self.construct,
            "visibility": self.visibility,
            "reason": self.reason,
        }


def is_stringish(node: ast.expr | None) -> bool:
    """Could this expression ever evaluate to prompt text?

    A container or a non-string constant cannot, so it is not a prompt site at
    all and must be excluded from the denominator rather than counted as opaque.
    This matters: name matching is substring-based, so `personal_details = {}`
    matches the "persona" hint and `SYSTEM_FIELDS = {...}` matches "system".
    Counting those as unrecoverable prompts would inflate the opaque rate with
    variables that were never prompts.
    """
    if node is None:
        return False
    if isinstance(node, (ast.Dict, ast.List, ast.Set, ast.Tuple, ast.DictComp, ast.SetComp, ast.ListComp)):
        return False
    return not (isinstance(node, ast.Constant) and not isinstance(node.value, str))


def classify(node: ast.expr | None, bindings: dict[str, str]) -> tuple[Visibility, str]:
    """Classify how much of an argument's text is recoverable without executing it.

    Returns the visibility class and, when opaque, why -- the reason is what makes
    a negative result diagnosable rather than just a number.
    """
    if node is None:
        return "opaque", "missing"

    if isinstance(node, ast.Constant):
        return ("static", "") if isinstance(node.value, str) else ("opaque", "non_string_constant")

    if isinstance(node, ast.JoinedStr):
        # An f-string is partial exactly when it interpolates something.
        has_hole = any(isinstance(v, ast.FormattedValue) for v in node.values)
        has_literal = any(
            isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value.strip()
            for v in node.values
        )
        if not has_literal:
            return "opaque", "fstring_all_holes"
        return ("partial", "fstring_interpolation") if has_hole else ("static", "")

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, _ = classify(node.left, bindings)
        right, _ = classify(node.right, bindings)
        if left == "static" and right == "static":
            return "static", ""
        if "opaque" in (left, right):
            # A literal joined to an unrecoverable value still has a skeleton.
            if "static" in (left, right) or "partial" in (left, right):
                return "partial", "concat_with_opaque"
            return "opaque", "concat_opaque"
        return "partial", "concat_partial"

    if isinstance(node, ast.Name):
        if node.id in bindings:
            # The binding map only holds statically resolvable values, but the
            # bound text may itself have come from an f-string.
            return ("partial", "via_binding_fstring") if "{...}" in bindings[node.id] else ("static", "")
        return "opaque", "name_unresolved"

    if isinstance(node, ast.Attribute):
        if node.attr in bindings:
            return ("partial", "via_binding_fstring") if "{...}" in bindings[node.attr] else ("static", "")
        return "opaque", "attribute_unresolved"

    if isinstance(node, ast.Call):
        return "opaque", "function_call"
    if isinstance(node, ast.Subscript):
        return "opaque", "subscript"
    if isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
        return "opaque", "comprehension"
    if isinstance(node, ast.IfExp):
        # A conditional yields one of several texts; the analyzer cannot know which.
        return "opaque", "conditional_expression"
    if isinstance(node, ast.Await):
        return "opaque", "await"

    return "opaque", "unsupported_expression"


def _callee(node: ast.Call) -> str:
    func = node.func
    return getattr(func, "id", None) or getattr(func, "attr", None) or ""


def _sites_from_call(
    node: ast.Call, path: str, bindings: dict[str, str]
) -> list[PromptSite]:
    name = _callee(node)
    kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
    out: list[PromptSite] = []

    def add(framework: str, construct: str, value: ast.expr | None) -> None:
        if not is_stringish(value):
            return
        vis, reason = classify(value, bindings)
        out.append(
            PromptSite(
                file=path,
                line=getattr(value, "lineno", node.lineno),
                framework=framework,
                construct=construct,
                visibility=vis,
                reason=reason,
            )
        )

    if name in _CREWAI_AGENT_CALLS and _CREWAI_AGENT & kwargs.keys():
        for field_name in sorted(_CREWAI_AGENT & kwargs.keys()):
            add("crewai", f"Agent.{field_name}", kwargs[field_name])
        return out

    if name in _CREWAI_TASK_CALLS and _CREWAI_TASK & kwargs.keys():
        for field_name in sorted(_CREWAI_TASK & kwargs.keys()):
            add("crewai", f"Task.{field_name}", kwargs[field_name])
        return out

    # A Task/Agent may be aliased; the characteristic field pair still identifies it.
    if kwargs.keys() >= _CREWAI_TASK:
        for field_name in sorted(_CREWAI_TASK):
            add("crewai", f"Task.{field_name}", kwargs[field_name])
        return out

    if name in _LANGCHAIN_CALLS:
        value = kwargs.get("content") or kwargs.get("template")
        if value is None and node.args:
            value = node.args[0]
        if value is not None:
            add("langchain", f"{name}", value)
            return out

    for kwarg in sorted(_GENERIC_PROMPT_KWARGS & kwargs.keys()):
        add("generic", f"kwarg.{kwarg}", kwargs[kwarg])

    return out


def _sites_from_dict(node: ast.Dict, path: str, bindings: dict[str, str]) -> list[PromptSite]:
    """OpenAI-style {"role": "system", "content": ...} message."""
    role_is_system = False
    content: ast.expr | None = None
    for k, v in zip(node.keys, node.values, strict=False):
        if not isinstance(k, ast.Constant):
            continue
        if k.value == "role" and isinstance(v, ast.Constant) and v.value == "system":
            role_is_system = True
        elif k.value == "content":
            content = v
    if not role_is_system or not is_stringish(content):
        return []
    vis, reason = classify(content, bindings)
    return [
        PromptSite(
            file=path,
            line=getattr(content, "lineno", node.lineno),
            framework="openai",
            construct="message.system",
            visibility=vis,
            reason=reason,
        )
    ]


def _sites_from_tuple(node: ast.Tuple, path: str, bindings: dict[str, str]) -> list[PromptSite]:
    """LangChain ("system", "...") message tuple."""
    if len(node.elts) < 2:
        return []
    first, second = node.elts[0], node.elts[1]
    if not (isinstance(first, ast.Constant) and first.value == "system"):
        return []
    if not is_stringish(second):
        return []
    vis, reason = classify(second, bindings)
    return [
        PromptSite(
            file=path,
            line=getattr(second, "lineno", node.lineno),
            framework="langchain",
            construct="system_tuple",
            visibility=vis,
            reason=reason,
        )
    ]


def _sites_from_assign(
    node: ast.Assign | ast.AnnAssign, path: str, bindings: dict[str, str]
) -> list[PromptSite]:
    """A constant whose *name* declares it a prompt, whatever its value turns out to be."""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    out: list[PromptSite] = []
    for t in targets:
        name = getattr(t, "id", None) or getattr(t, "attr", None)
        if not name or not _name_matches(name):
            continue
        if not is_stringish(node.value):
            continue
        vis, reason = classify(node.value, bindings)
        out.append(
            PromptSite(
                file=path,
                line=node.lineno,
                framework="binding",
                construct=f"const.{name}",
                visibility=vis,
                reason=reason,
            )
        )
    return out


def sites_in_source(source: str, path: str) -> list[PromptSite]:
    """Enumerate every prompt site in one Python source file."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    bindings = _string_bindings(tree)
    out: list[PromptSite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            out.extend(_sites_from_call(node, path, bindings))
        elif isinstance(node, ast.Dict):
            out.extend(_sites_from_dict(node, path, bindings))
        elif isinstance(node, ast.Tuple):
            out.extend(_sites_from_tuple(node, path, bindings))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            out.extend(_sites_from_assign(node, path, bindings))

    # One physical location can be reached by more than one walk branch.
    seen: set[tuple[str, int, str]] = set()
    unique: list[PromptSite] = []
    for site in out:
        key = (site.file, site.line, site.construct)
        if key in seen:
            continue
        seen.add(key)
        unique.append(site)
    return unique


@dataclass
class VisibilityResult:
    name: str
    files_scanned: int = 0
    sites: list[PromptSite] = field(default_factory=list)
    error: str | None = None

    def counts(self) -> Counter[str]:
        return Counter(s.visibility for s in self.sites)

    def metrics(self) -> dict[str, Any]:
        c = self.counts()
        total = len(self.sites)
        static, partial, opaque = c["static"], c["partial"], c["opaque"]
        return {
            "sites": total,
            "static": static,
            "partial": partial,
            "opaque": opaque,
            "spv_full": static / total if total else 0.0,
            "spv_partial": (static + partial) / total if total else 0.0,
            "opaque_rate": opaque / total if total else 0.0,
            "by_framework": _breakdown(self.sites, lambda s: s.framework),
            "by_construct": _breakdown(self.sites, lambda s: s.construct),
            "opaque_reasons": dict(
                Counter(s.reason for s in self.sites if s.visibility == "opaque").most_common()
            ),
        }


def _breakdown(sites: list[PromptSite], key: Any) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for s in sites:
        bucket = out.setdefault(key(s), {"static": 0, "partial": 0, "opaque": 0})
        bucket[s.visibility] += 1
    return dict(sorted(out.items()))


def run_visibility(root: str | Path, *, name: str | None = None) -> VisibilityResult:
    root_path = Path(root)
    result = VisibilityResult(name=name or root_path.name)
    if not root_path.exists():
        result.error = "path not found"
        return result

    for path in root_path.rglob("*.py"):
        if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        result.files_scanned += 1
        try:
            rel = path.relative_to(root_path).as_posix()
        except ValueError:
            rel = path.as_posix()
        result.sites.extend(sites_in_source(source, rel))
    return result


__all__ = [
    "PromptSite",
    "Visibility",
    "VisibilityResult",
    "classify",
    "is_stringish",
    "run_visibility",
    "sites_in_source",
]
