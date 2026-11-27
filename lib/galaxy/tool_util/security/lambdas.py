"""Lambdas of a template that the review can read as functions of their arguments.

The analysis evaluates the body of a lambda once, where the lambda is made, and a call of it gives that value
joined with what the call passes (:class:`~.interp.TemplateAnalysis`). That is what a call renders only when the
body cannot read anything that changes between the lambda and its call, nor change anything itself. Such a lambda
is pure. Its body reads only:

* its arguments, and the names that comprehensions and lambdas in it bind;
* literals;
* ``$name``, which Cheetah looks up in the frame of the lambda, then in the namespace. Not the name of a
  ``#set global`` value, a member of the template, or a name the template object, its module or Python answers
  to first: what those give can change before the call;
* the builtins and modules the analysis reads as computing a value from what they are given
  (:data:`PURE_NAMES`), where the template binds no local or import of that name.

It changes nothing: no ``:=``, no method that changes its object in place (:data:`~.interp.MUTATORS`), no
attribute that starts with ``_``, no comprehension target but names. A lambda in it follows the same rules. The
defaults of the lambda's own arguments are evaluated where the lambda is made, as the analysis reads them, and can
be anything.

Any other lambda is code the review does not follow (:func:`impurity`): it can read a local the template sets
again before the call, or change a list of the template's with what the call passes.
"""

from __future__ import annotations

import ast
from collections.abc import (
    Callable,
    Iterable,
    Iterator,
)

from Cheetah.Template import Template

from .interp import (
    MUTATORS,
    PY_NAMES,
    TEMPLATE_NAMES,
)
from .template import (
    Method,
    name_lookup,
    NAME_MAPPER,
    NAMESPACE_LOOKUPS,
)

# The names of PY_NAMES a pure lambda may use. Not those that reach objects by name or act (getattr, open,
# print), reach a value's class (type), the template object (self, getVar, varExists, hasVar) or the
# interpreter and the server (sys, os, time), nor Galaxy's functions in the namespace.
PURE_NAMES = frozenset(
    name
    for name in PY_NAMES - frozenset("getattr open print type self getVar varExists hasVar sys os time".split())
    if not name.startswith("_")
)

# What `$name` finds on the template object, before the namespace.
_TEMPLATE_ATTRIBUTES = frozenset(dir(Template))
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)


def method_locals(method: Method) -> frozenset[str]:
    """The names the code of a method binds in the method's own scope: its arguments, `#set` and loop
    variables, imports, and what a `:=` in a comprehension binds."""
    names = set(method.args)
    for stmt in method.body:
        names.update(_bound(stmt))
    return frozenset(names)


def _bound(node: ast.AST) -> Iterator[str]:
    if isinstance(node, ast.Lambda):
        return
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        yield from ((alias.asname or alias.name).split(".")[0] for alias in node.names)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        yield node.name
        return
    elif isinstance(node, ast.ExceptHandler) and node.name:
        yield node.name
    elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        yield node.id
    elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
        yield node.target.id
    if isinstance(node, _COMPREHENSIONS):
        # Its targets are its own; a `:=` in it binds in the method.
        for child in ast.walk(node):
            if isinstance(child, ast.NamedExpr) and isinstance(child.target, ast.Name):
                yield child.target.id
        return
    for child in ast.iter_child_nodes(node):
        yield from _bound(child)


def imported_names(imports: Iterable[ast.stmt]) -> frozenset[str] | None:
    """The module-level names the template's own imports bind to something else than a module of that name;
    None when a ``from ... import *`` can bind any name."""
    names = set()
    for node in imports:
        for alias in getattr(node, "names", ()):
            if alias.name == "*":
                return None
            if isinstance(node, ast.ImportFrom) or (alias.asname and alias.asname != alias.name):
                names.add(alias.asname or alias.name)
    return frozenset(names)


class _Purity:
    def __init__(
        self,
        locals_: frozenset[str],
        imported: frozenset[str] | None,
        changing: frozenset[str],
        is_input: Callable[[str], bool],
    ):
        self.locals = locals_
        self.imported = imported
        self.changing = changing
        self.is_input = is_input

    def lambda_(self, node: ast.Lambda, bound: frozenset[str], nested: bool) -> str | None:
        arguments = node.args
        if nested:
            # The defaults of a lambda in the body are evaluated when the body runs.
            defaults = [*arguments.defaults, *(d for d in arguments.kw_defaults if d is not None)]
            for default in defaults:
                if reason := self.expr(default, bound):
                    return reason
        own = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg]
        return self.expr(node.body, bound | {a.arg for a in own if a is not None})

    def comprehension(self, node: ast.AST, bound: frozenset[str]) -> str | None:
        assert isinstance(node, _COMPREHENSIONS)
        for generator in node.generators:
            if reason := self.expr(generator.iter, bound):
                return reason
            for target in ast.walk(generator.target):
                if isinstance(target, (ast.Attribute, ast.Subscript)):
                    return f"stores into `{ast.unparse(target)}`"
            bound = bound | {n.id for n in ast.walk(generator.target) if isinstance(n, ast.Name)}
            for condition in generator.ifs:
                if reason := self.expr(condition, bound):
                    return reason
        parts = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        for part in parts:
            if reason := self.expr(part, bound):
                return reason
        return None

    def name(self, name: str, bound: frozenset[str]) -> str | None:
        if name in bound:
            return None
        if name in self.locals:
            return f"reads `{name}`, a local the template can set again before the call"
        if name in PURE_NAMES and self.imported is not None and name not in self.imported:
            return None
        return f"uses `{name}`"

    def lookup(self, path: str, bound: frozenset[str]) -> str | None:
        """`$a.b.c`: Cheetah finds `a` in the frame of the lambda, else in the namespace."""
        first, *rest = path.split(".")
        if first not in bound:
            # The #set global store and the template object come before the namespace, its module and Python after.
            if first in self.changing or first in _TEMPLATE_ATTRIBUTES:
                return f"reads `${first}`, which the template can set again before the call"
            if first in TEMPLATE_NAMES and first not in PURE_NAMES and not self.is_input(first):
                return f"uses `${first}`"
        return self.attributes(rest)

    @staticmethod
    def attributes(names: Iterable[str]) -> str | None:
        for name in names:
            if name in MUTATORS:
                return f"changes a value in place with `.{name}`"
            if name.startswith("_"):
                return f"reaches `.{name}`"
        return None

    def expr(self, node: ast.AST | None, bound: frozenset[str]) -> str | None:
        if node is None or isinstance(node, (ast.Constant, ast.expr_context)):
            return None
        if isinstance(node, ast.Lambda):
            return self.lambda_(node, bound, nested=True)
        if isinstance(node, _COMPREHENSIONS):
            return self.comprehension(node, bound)
        if isinstance(node, ast.NamedExpr):
            return f"binds `{ast.unparse(node.target)}` with `:=`"
        if isinstance(node, (ast.Yield, ast.YieldFrom, ast.Await)):
            return "is a generator"
        if isinstance(node, ast.Name):
            return self.name(node.id, bound) if isinstance(node.ctx, ast.Load) else f"binds `{node.id}`"
        if isinstance(node, ast.Attribute):
            return self.attributes([node.attr]) or self.expr(node.value, bound)
        if lookup := name_lookup(node, NAME_MAPPER):
            function, path = lookup
            assert isinstance(node, ast.Call)
            if function in NAMESPACE_LOOKUPS:
                return self.lookup(path, bound)
            # `VFN(value, 'a.b', ...)`: attributes of a value.
            return self.attributes(path.split(".")) or self.expr(node.args[0], bound)
        for child in ast.iter_child_nodes(node):
            if reason := self.expr(child, bound):
                return reason
        return None


def impurity(
    node: ast.Lambda,
    locals_: frozenset[str],
    imported: frozenset[str] | None,
    changing: frozenset[str],
    is_input: Callable[[str], bool],
) -> str | None:
    """Why the review cannot read a lambda as a function of its arguments, None for a pure lambda.

    ``locals_``: the names its method binds (:func:`method_locals`); ``imported``: see :func:`imported_names`;
    ``changing``: the names of `#set global` values and of the template's members; ``is_input``: whether the
    namespace has a tool input of a name.
    """
    return _Purity(locals_, imported, changing, is_input).lambda_(node, frozenset(), nested=False)


def nested_lambdas(node: ast.Lambda) -> Iterator[ast.Lambda]:
    """The lambdas in the body of a lambda, which :func:`impurity` judges with it."""
    for child in ast.walk(node.body):
        if isinstance(child, ast.Lambda):
            yield child

