"""Bounded lexical binding recovery; not whole-program Python analysis."""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Callable

_SCOPES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


class BoundText(str):
    """Keep skeleton provenance separate from literal placeholder-like text."""

    partial: bool

    def __new__(cls, value: str, partial: bool = False) -> BoundText:
        obj = super().__new__(cls, value)
        obj.partial = partial
        return obj


def _has_holes(node: ast.AST | None) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return False
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(n, ast.FormattedValue) for n in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _has_holes(node.left) or _has_holes(node.right)
    return True


def binding_contexts(tree: ast.AST, text_of: Callable) -> dict[ast.AST, dict[str, str]]:
    """Map candidate constructs to conservative, position-sensitive bindings.

    Only direct unconditional literal/skeleton assignments are eligible. A local
    parameter, import, dynamic assignment or mutation invalidates the name.
    Object attributes are deliberately outside this analysis.
    """
    contexts: dict[ast.AST, dict[str, str]] = {}
    external = {name for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal)) for name in n.names}
    external.update(
        n.target.id for n in ast.walk(tree) if isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name)
    )
    # Give up on propagation throughout files with explicit namespace mutation.
    dynamic_namespace = any(
        (isinstance(n, ast.ImportFrom)
        and any(a.name == "*" for a in n.names))
        or (isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in {"exec", "globals", "locals", "vars"})
        for n in ast.walk(tree)
    )
    if dynamic_namespace:
        return contexts

    def scope(root: ast.AST, inherited: dict[str, str], outer: dict[str, str]) -> None:
        body = getattr(root, "body", [])
        direct = set(body if isinstance(body, list) else [])
        locals_: set[str] = set()
        invalid = set(external)
        values: dict[str, list[tuple[str, tuple[int, int]]]] = defaultdict(list)
        assigned: dict[ast.Name, str | None] = {}

        class Collect(ast.NodeVisitor):
            def visit(self, node: ast.AST) -> None:
                if node is not root and isinstance(node, _SCOPES):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        locals_.add(node.name)
                        invalid.add(node.name)
                    return
                return super().visit(node)

            def visit_Assign(self, node: ast.Assign) -> None:
                value = text_of(node.value) if node in direct else None
                if value is not None:
                    value = BoundText(value, _has_holes(node.value))
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned[target] = value
                self.generic_visit(node)

            def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
                if isinstance(node.target, ast.Name):
                    value = text_of(node.value) if node in direct else None
                    assigned[node.target] = BoundText(value, _has_holes(node.value)) if value is not None else None
                self.generic_visit(node)

            def visit_Name(self, node: ast.Name) -> None:
                if isinstance(node.ctx, (ast.Store, ast.Del)):
                    locals_.add(node.id)
                    value = assigned.get(node)
                    if value is None:
                        invalid.add(node.id)
                    else:
                        values[node.id].append((value, (node.lineno, node.col_offset)))

            def visit_arg(self, node: ast.arg) -> None:
                locals_.add(node.arg)
                invalid.add(node.arg)

            def visit_alias(self, node: ast.alias) -> None:
                name = node.asname or node.name.split(".")[0]
                locals_.add(name)
                invalid.add(name)

            def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
                if node.name:
                    locals_.add(node.name)
                    invalid.add(node.name)
                self.generic_visit(node)

            def visit_MatchAs(self, node: ast.MatchAs | ast.MatchStar) -> None:
                if node.name:
                    locals_.add(node.name)
                    invalid.add(node.name)
                self.generic_visit(node)

            visit_MatchStar = visit_MatchAs

            def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
                if node.rest:
                    locals_.add(node.rest)
                    invalid.add(node.rest)
                self.generic_visit(node)

        Collect().visit(root)
        stable = {
            k: v[0][0]
            for k, v in values.items()
            if k not in invalid and len({(x, getattr(x, "partial", False)) for x, _ in v}) == 1
        }
        first = {k: min(pos for _, pos in values[k]) for k in stable}
        parent = {k: v for k, v in inherited.items() if k not in locals_ and k not in invalid}

        class Walk(ast.NodeVisitor):
            def visit(self, node: ast.AST) -> None:
                if node is not root and isinstance(node, _SCOPES):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for expr in [
                            *node.decorator_list,
                            *node.args.defaults,
                            *(x for x in node.args.kw_defaults if x is not None),
                        ]:
                            self.visit(expr)
                    if isinstance(node, ast.ClassDef):
                        for expr in [*node.decorator_list, *node.bases, *(x.value for x in node.keywords)]:
                            self.visit(expr)
                    pos = (node.lineno, node.col_offset)
                    base = (
                        outer
                        if isinstance(root, ast.ClassDef)
                        else {**parent, **{k: v for k, v in stable.items() if first[k] < pos}}
                    )
                    scope(node, base, base)
                    return
                if isinstance(node, (ast.Call, ast.Assign, ast.AnnAssign, ast.Dict, ast.Tuple)):
                    pos = (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
                    contexts[node] = {**parent, **{k: v for k, v in stable.items() if first[k] < pos}}
                if node is root and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    for stmt in node.body:
                        self.visit(stmt)
                    return None
                if node is root and isinstance(node, ast.Lambda):
                    self.visit(node.body)
                    return None
                return super().visit(node)

        Walk().visit(root)

    scope(tree, {}, {})
    return contexts
