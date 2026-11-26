"""Rewrites of a compiled template into one that renders the same and that the review can follow."""

from __future__ import annotations

import ast
import copy

from .known_helpers import (
    bound_names,
    lookup_path,
    method_locals,
    object_names,
    specialise_known_helpers,
)
from .template import (
    constant,
    NAME_MAPPER,
)


def rewrite_template(tree: ast.Module) -> set[int]:
    """Apply each rewrite; returns the getVar calls they made that read the tool namespace."""
    literal_getattr(tree)
    return specialise_known_helpers(tree)


# Attributes of a parameter wrapper that hold its value: never a method, which the attribute would leave uncalled.
_VALUE_ATTRIBUTES = frozenset(("value",))


def literal_getattr(tree: ast.Module) -> None:
    """Replace ``getattr($x, "value", default)`` by ``$x.value if hasattr($x, "value") else default``.

    Only where ``getattr`` and ``hasattr`` are the builtins, the template binds no ``value``, ``$x`` is a lookup of
    the namespace and ``default`` a lookup or literal, which the rewrite may read more than once or not at all.
    """
    bound = bound_names(tree)
    if "getattr" in bound or "hasattr" in bound or bound & _VALUE_ATTRIBUTES:
        return
    _LiteralGetattr().visit(tree)


class _LiteralGetattr(ast.NodeTransformer):
    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if not (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and not node.keywords
            and len(node.args) in (2, 3)
            and constant(node.args[1]) in _VALUE_ATTRIBUTES
            and (path := lookup_path(node.args[0])) is not None
            and (root := path.split(".")[0]) not in method_locals()
            and root not in object_names()
            and all(_pure(arg) for arg in node.args)
        ):
            return node
        name = str(constant(node.args[1]))
        receiver = node.args[0]
        attribute = ast.Attribute(value=receiver, attr=name, ctx=ast.Load())
        if len(node.args) == 2:
            return ast.fix_missing_locations(ast.copy_location(attribute, node))
        test = ast.Call(
            func=ast.Name(id="hasattr", ctx=ast.Load()), args=[copy.deepcopy(receiver), node.args[1]], keywords=[]
        )
        choice = ast.IfExp(test=test, body=attribute, orelse=node.args[2])
        return ast.fix_missing_locations(ast.copy_location(choice, node))


def _pure(node: ast.expr) -> bool:
    """A literal, a name, a NameMapper lookup with a literal name, or an attribute of one: reading it changes
    nothing."""
    if isinstance(node, (ast.Constant, ast.Name)):
        return isinstance(node, ast.Constant) or isinstance(node.ctx, ast.Load)
    if isinstance(node, ast.Attribute):
        return isinstance(node.ctx, ast.Load) and _pure(node.value)
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in NAME_MAPPER
        and not node.keywords
        and len(node.args) == 3
        and isinstance(node.args[0], ast.Name)
        and isinstance(constant(node.args[1]), str)
        and isinstance(node.args[2], ast.Constant)
    )
