"""The strings the names a template looks variables up by can be, decided once for the whole template.

``$getVar(name)`` reads whatever variable ``name`` names. When the name is built from literal text, the
variables it can name are known and their values are checked like any other. The decision is made on the
template's syntax, not while it is followed: for each variable, the strings it can be are the union over
every place it is bound (`#set` and `#for` in the same method, `#set global` anywhere, the calls of a
`#def` for its arguments, the namespace for a name that is not an argument), and only when each of those is
literal text and the variable is never changed in place, unpacked into or handed to code that could change
it. Anything else is not known, and the lookup is reflection.
"""

from __future__ import annotations

import ast
from typing import Iterable

from .model import Model
from .template import (
    CompiledTemplate,
    constant,
    name_lookup,
    NAMESPACE_LOOKUPS,
)
from .values import (
    literal_product,
    literal_strings,
    literal_union,
)

# The store of `#set global` in the compiled template.
_GLOBALS = "_CHEETAH__globalSetVars"
# Calls a list variable can be handed to without being changed.
_READING_CALLS = frozenset(("len", "str"))

# What a variable is bound to at one place: ("value", expr), ("elements", iterable) or ("unknown", None),
# with the method the expression is in.
Binding = tuple[str, ast.expr | None, str]
# The scope of `#set global` variables, and of what is evaluated where a #def is defined.
_GLOBAL = "#global"
_DEFINITION = "#definition"


def _loaded_name(node: ast.AST) -> str | None:
    """The variable a load reads: `$name`, `name`, or the head of `$name.attr`."""
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        return node.id
    if lookup := name_lookup(node, NAMESPACE_LOOKUPS):
        return lookup[1].split(".")[0]
    return None


def _names_in(target: ast.AST) -> Iterable[str]:
    for node in ast.walk(target):
        if isinstance(node, ast.Name):
            yield node.id


class NameStrings:
    """What each variable of a template can be, as literal strings."""

    def __init__(self, template: CompiledTemplate, model: Model) -> None:
        self.model = model
        self.helpers = template.helpers
        # Bindings by (method, variable); a #def's arguments are its own variables, `#set global` is _GLOBAL's.
        self.bindings: dict[tuple[str, str], list[Binding]] = {}
        self.arguments = {(name, arg) for name, method in template.helpers.items() for arg in method.args}
        # The method each node of the template is in.
        self.scope_of: dict[int, str] = {}
        # Variables loaded where something can change them in place, or that are aliased.
        self.escaping: set[str] = set()
        methods = [template.main, *template.helpers.values()]
        for method in methods:
            for statement in method.body:
                for node in ast.walk(statement):
                    self.scope_of[id(node)] = method.name
        for method in methods:
            for statement in method.body:
                for node in ast.walk(statement):
                    self._note(node, method.name)
        self._helper_calls(methods)
        self._loads(methods)

    # -- collecting ------------------------------------------------------------------------------

    def _bind(self, scope: str, name: str, kind: str, expr: ast.expr | None, at: str) -> None:
        self.bindings.setdefault((scope, name), []).append((kind, expr, at))

    def _unknown(self, scope: str, target: ast.AST) -> None:
        for name in _names_in(target):
            self._bind(scope, name, "unknown", None, scope)

    def _note(self, node: ast.AST, scope: str) -> None:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._bind(scope, target.id, "value", node.value, scope)
                elif (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Attribute)
                    and target.value.attr == _GLOBALS
                    and isinstance(key := constant(target.slice), str)
                ):
                    self._bind(_GLOBAL, key, "value", node.value, scope)
                else:
                    self._unknown(scope, target)
        elif isinstance(node, ast.AugAssign):
            self._unknown(scope, node.target)
        elif isinstance(node, ast.For):
            if isinstance(node.target, ast.Name):
                self._bind(scope, node.target.id, "elements", node.iter, scope)
            else:
                self._unknown(scope, node.target)
        elif isinstance(node, ast.comprehension):
            self._unknown(scope, node.target)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    self._unknown(scope, item.optional_vars)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            self._bind(scope, node.name, "unknown", None, scope)
        elif isinstance(node, ast.NamedExpr):
            self._unknown(scope, node.target)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                self._bind(scope, name, "unknown", None, scope)

    def _helper_calls(self, methods: list) -> None:
        """A #def's arguments are bound at each of its calls; one it is referenced by otherwise binds them to anything."""
        called: dict[int, str] = {}
        for method in methods:
            for statement in method.body:
                for node in ast.walk(statement):
                    if isinstance(node, ast.Call) and (helper := self._helper_of(node.func)):
                        called[id(node.func)] = helper
                        self._bind_arguments(helper, node)
        for method in methods:
            for statement in method.body:
                for node in ast.walk(statement):
                    helper = self._helper_of(node)
                    if helper and id(node) not in called:
                        for arg in self.helpers[helper].args:
                            self._bind(helper, arg, "unknown", None, helper)
        for name, method in self.helpers.items():
            for arg in method.args:
                if arg in method.defaults:
                    # Evaluated where the #def is defined, outside any method.
                    self._bind(name, arg, "value", method.defaults[arg], _DEFINITION)
                    self.scope_of.setdefault(id(method.defaults[arg]), _DEFINITION)

    def _helper_of(self, node: ast.AST) -> str | None:
        if lookup := name_lookup(node, NAMESPACE_LOOKUPS):
            return lookup[1] if lookup[1] in self.helpers else None
        if isinstance(node, ast.Name) and node.id in self.helpers:
            return node.id
        if isinstance(node, ast.Attribute) and node.attr in self.helpers:
            return node.attr
        return None

    def _bind_arguments(self, helper: str, call: ast.Call) -> None:
        args = self.helpers[helper].args
        at = self.scope_of.get(id(call), "")
        if any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
            for arg in args:
                self._bind(helper, arg, "unknown", None, at)
            return
        for name, value in zip(args, call.args):
            self._bind(helper, name, "value", value, at)
        for keyword in call.keywords:
            if keyword.arg in args:
                self._bind(helper, keyword.arg, "value", keyword.value, at)
            else:
                # An argument of another name: the call can bind anything.
                for arg in args:
                    self._bind(helper, arg, "unknown", None, at)

    def _loads(self, methods: list) -> None:
        """Mark the variables read where they can be changed in place or aliased: only a `#for` over a list,
        `len()`, `str()` and building another name leave a list as it is."""
        for method in methods:
            for statement in method.body:
                safe: set[int] = set()
                for node in ast.walk(statement):
                    if isinstance(node, ast.For):
                        safe.add(id(node.iter))
                    elif isinstance(node, ast.Call):
                        func = node.func
                        if isinstance(func, ast.Name) and func.id in _READING_CALLS:
                            safe.update(id(a) for a in node.args)
                for node in ast.walk(statement):
                    name = _loaded_name(node)
                    if name is None:
                        continue
                    if lookup := name_lookup(node, NAMESPACE_LOOKUPS):
                        if "." in lookup[1]:
                            # `$name.attr`: a method of it can change it.
                            self.escaping.add(name)
                            continue
                    if id(node) not in safe:
                        self.escaping.add(name)

    # -- deciding --------------------------------------------------------------------------------

    def strings(self, node: ast.AST | None) -> frozenset[str] | None:
        """Every string the expression can be, or None."""
        scope = self.scope_of.get(id(node)) if node is not None else None
        return None if scope is None else self._strings(node, scope, frozenset())

    def _strings(self, node: ast.AST | None, scope: str, seen: frozenset) -> frozenset[str] | None:
        if isinstance(node, ast.Constant):
            return frozenset((node.value,)) if isinstance(node.value, str) else None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return literal_product(self._strings(node.left, scope, seen), self._strings(node.right, scope, seen))
        if isinstance(node, ast.IfExp):
            return literal_union(self._strings(node.body, scope, seen), self._strings(node.orelse, scope, seen))
        if isinstance(node, ast.BoolOp):
            return literal_union(*(self._strings(value, scope, seen) for value in node.values))
        if isinstance(node, ast.JoinedStr):
            pieces = []
            for value in node.values:
                if isinstance(value, ast.FormattedValue):
                    if value.conversion != -1 or value.format_spec is not None:
                        return None
                    pieces.append(self._strings(value.value, scope, seen))
                else:
                    pieces.append(self._strings(value, scope, seen))
            return literal_product(*pieces)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and len(node.args) == 1
            and not node.keywords
        ):
            return self._strings(node.args[0], scope, seen)
        if node is None or (name := _loaded_name(node)) is None:
            return None
        if (lookup := name_lookup(node, NAMESPACE_LOOKUPS)) and "." in lookup[1]:
            return None
        return self._variable(name, scope, seen)

    def _bindings(self, name: str, scope: str) -> tuple[list[Binding], bool]:
        """Where a variable read in ``scope`` can have been bound, and whether the namespace's can be read."""
        local = self.bindings.get((scope, name), [])
        if (scope, name) in self.arguments:
            return local, False
        # Not bound in the method yet, or never: the `#set global` variables, then the namespace.
        return local + self.bindings.get((_GLOBAL, name), []), True

    def _variable(self, name: str, scope: str, seen: frozenset) -> frozenset[str] | None:
        if (scope, name) in seen:
            return None
        seen = seen | {(scope, name)}
        bindings, namespace = self._bindings(name, scope)
        found: list[frozenset[str] | None] = []
        for kind, expr, at in bindings:
            if kind == "value":
                found.append(self._strings(expr, at, seen))
            elif kind == "elements":
                found.append(self._elements(expr, at, seen))
            else:
                return None
        if namespace and (value := self.model.lookup(name)) is not None:
            found.append(literal_strings(value))
        elif not found:
            return None
        return literal_union(*found)

    def _elements(self, node: ast.AST | None, scope: str, seen: frozenset) -> frozenset[str] | None:
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            if any(isinstance(elt, ast.Starred) for elt in node.elts):
                return None
            return literal_union(*(self._strings(elt, scope, seen) for elt in node.elts))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "split"
            and len(node.args) == 1
            and not node.keywords
            and isinstance(separator := constant(node.args[0]), str)
            and separator
        ):
            strings = self._strings(node.func.value, scope, seen)
            if strings is None:
                return None
            return literal_union(frozenset(piece for string in strings for piece in string.split(separator)))
        if node is None or (name := _loaded_name(node)) is None or (scope, name) in seen or name in self.escaping:
            return None
        if (lookup := name_lookup(node, NAMESPACE_LOOKUPS)) and "." in lookup[1]:
            return None
        bindings, namespace = self._bindings(name, scope)
        found: list[frozenset[str] | None] = []
        for kind, expr, at in bindings:
            if kind != "value" or not isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
                return None
            found.append(self._elements(expr, at, seen | {(scope, name)}))
        if namespace and (value := self.model.lookup(name)) is not None:
            # A multiple select: its values.
            found.append(literal_strings(value))
        elif not found:
            return None
        return literal_union(*found)
