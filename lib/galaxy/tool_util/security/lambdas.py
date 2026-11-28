"""Lambdas of a template that the review can read as functions of their arguments, and changes in place it cannot follow.

The analysis evaluates the body of a lambda once, where the lambda is made, and a call of it gives that value
joined with what the call passes (:class:`~.interp.TemplateAnalysis`). That is what a call renders only when the
body cannot read anything that changes between the lambda and its call, nor change anything itself. Such a lambda
is pure. Its body reads only:

* its arguments, and the names that comprehensions and lambdas in it bind;
* literals;
* ``$name``, which Cheetah looks up in the locals of the frame that runs it, then in the namespace: an argument
  of the innermost lambda, or a target of the innermost comprehension, else a lookup. A lookup of a ``#set
  global`` value, a member of the template, an attribute of the template object or of a locals dict, or a name
  the module or Python answers to, can give what the template sets after the lambda is made;
* the builtins and modules the analysis reads as computing a value from what they are given
  (:data:`PURE_NAMES`), where the template binds no local or import of that name.

It changes nothing: no ``:=``, no method that adds to its object, reorders it or takes from it in place
(:data:`~.interp.MUTATORS`, :data:`~.interp.REORDERS`), no attribute that starts with ``_``, no comprehension
target but names. A lambda in it follows the same rules. The defaults of the lambda's own arguments are evaluated
where the lambda is made, as the analysis reads them, and can be anything.

A pure lambda passed on as a value carries what it gives: a call of whatever it reaches gives that too
(:func:`~.values.stringify`).

Any other lambda is code the review does not follow (:func:`impurity`): it can read a local the template sets
again before the call, or change a list of the template's with what the call passes.

A method that changes its object in place is followed where the template calls it on one of its own names, or
maps it over a list (``map(l.append, values)``). Passed on in any other way, or called on a name a comprehension
binds or on any other value (``list.append($l, value)``, ``type(l).append(l, value)``), what it changes is not
followed, nor what ``operator.iadd`` and its kin change or a comprehension stores into its target
(:func:`unfollowed_changes`).
"""

from __future__ import annotations

import ast
from collections.abc import (
    Iterable,
    Iterator,
)
from typing import Callable

from .interp import (
    MUTATORS,
    PY_NAMES,
    REORDERS,
    TEMPLATE_NAMES,
)
from .template import (
    Method,
    name_lookup,
    NAME_MAPPER,
    NAMESPACE_LOOKUPS,
    template_attributes,
)

# The names of PY_NAMES a pure lambda may use. Not those that reach objects by name or act (getattr, open,
# print), reach a value's class (type), the template object (self, getVar, varExists, hasVar) or the
# interpreter and the server (sys, os, time), nor Galaxy's functions in the namespace.
PURE_NAMES = frozenset(
    name
    for name in PY_NAMES - frozenset("getattr open print type self getVar varExists hasVar sys os time".split())
    if not name.startswith("_")
)

# The functions of the operator module that change their first argument in place.
_OPERATOR_CHANGES = frozenset(
    "iadd iand iconcat ifloordiv ilshift imatmul imod imul ior ipow irshift isub itruediv ixor setitem delitem".split()
)
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


def scopes(
    node: ast.AST, bound: frozenset[str], frame: frozenset[str]
) -> Iterator[tuple[ast.AST, frozenset[str], frozenset[str]]]:
    """Each node of an expression with ``bound``, the names the code around it binds, which Python names read,
    and ``frame``, those of the frame that runs it, which `$name` finds there: the arguments of the innermost
    lambda, or the targets of the innermost comprehension. Python 3.12 runs a comprehension in the frame around
    it, older versions do not: `$name` of a name bound outside it is read as a lookup either way.

    The defaults of a lambda and the first iterable of a comprehension are evaluated in the frame around them.
    It does not go into the targets of a comprehension, the arguments of a lambda, nor the literal arguments of
    a NameMapper call."""
    yield node, bound, frame
    if isinstance(node, ast.Lambda):
        arguments = node.args
        for default in [*arguments.defaults, *arguments.kw_defaults]:
            if default is not None:
                yield from scopes(default, bound, frame)
        names = lambda_arguments(node)
        yield from scopes(node.body, bound | names, names)
    elif isinstance(node, _COMPREHENSIONS):
        own: frozenset[str] = frozenset()
        for generator in node.generators:
            yield from scopes(generator.iter, bound, own if own else frame)
            names = _targets(generator)[0]
            bound, own = bound | names, own | names
            for condition in generator.ifs:
                yield from scopes(condition, bound, own)
        for part in [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]:
            yield from scopes(part, bound, own)
    elif lookup := name_lookup(node, NAME_MAPPER):
        assert isinstance(node, ast.Call)
        if lookup[0] not in NAMESPACE_LOOKUPS:
            # `VFN(value, 'a.b', ...)`: attributes of a value.
            yield from scopes(node.args[0], bound, frame)
    else:
        for child in ast.iter_child_nodes(node):
            yield from scopes(child, bound, frame)


def lambda_arguments(node: ast.Lambda) -> frozenset[str]:
    arguments = node.args
    own = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg]
    return frozenset(a.arg for a in own if a is not None)


def unbound_lookups(method: Method) -> set[str]:
    """The first names of the method's lookups (`$name`) where no local of the frame that runs them holds the
    name: not an argument, a local of Cheetah's own code, a `#set` or loop variable set on every path to the
    lookup, nor a name of the frame :func:`scopes` gives. There Cheetah looks the name up in the `#set global`
    store, the template object and the namespace."""
    found: set[str] = set()
    _block_lookups(method.body, frozenset(method.args) | method.preamble, found)
    for expression in method.at_definition:
        _lookups(expression, frozenset(), found)
    return found


def _block_lookups(body: list[ast.stmt], frame: frozenset[str], found: set[str]) -> None:
    for stmt in body:
        _lookups(stmt, frame, found)
        if isinstance(stmt, ast.Assign):
            frame |= {name for target in stmt.targets for name in _bound(target)}


def _lookups(node: ast.AST, frame: frozenset[str], found: set[str]) -> None:
    if isinstance(node, ast.expr):
        for child, _, child_frame in scopes(node, frozenset(), frame):
            lookup = name_lookup(child, NAMESPACE_LOOKUPS)
            if lookup and (first := lookup[1].split(".")[0]) not in child_frame:
                found.add(first)
    elif isinstance(node, ast.For):
        _lookups(node.iter, frame, found)
        _block_lookups(node.body, frame | set(_bound(node.target)), found)
        _block_lookups(node.orelse, frame, found)
    else:
        for _, value in ast.iter_fields(node):
            if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                _block_lookups(value, frame, found)
            else:
                for child in value if isinstance(value, list) else [value]:
                    if isinstance(child, ast.AST):
                        _lookups(child, frame, found)


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


def _targets(generator: ast.comprehension) -> tuple[frozenset[str], list[ast.expr]]:
    """The names a generator of a comprehension binds, and the attributes and subscripts it stores into."""
    nodes = list(ast.walk(generator.target))
    names = frozenset(n.id for n in nodes if isinstance(n, ast.Name))
    return names, [n for n in nodes if isinstance(n, (ast.Attribute, ast.Subscript))]


class _Purity:
    """Reads the nodes of a lambda's body with their ``bound`` and ``frame`` (:func:`scopes`)."""

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

    def lambda_(self, node: ast.Lambda) -> str | None:
        names = lambda_arguments(node)
        for child, bound, frame in scopes(node.body, names, names):
            if reason := self.node(child, bound, frame):
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

    def lookup(self, path: str, frame: frozenset[str]) -> str | None:
        """`$a.b.c`: Cheetah finds `a` in the locals of the frame that runs it, else in the namespace."""
        first, *rest = path.split(".")
        if first not in frame:
            # The attributes of the frame's locals, the #set global store and the template object come before
            # the namespace, the module and Python after it.
            if first in self.changing or first in template_attributes():
                return f"reads `${first}`, which the template can set again before the call"
            if first in TEMPLATE_NAMES and first not in PURE_NAMES and not self.is_input(first):
                return f"uses `${first}`"
        return self.attributes(rest)

    @staticmethod
    def attributes(names: Iterable[str]) -> str | None:
        for name in names:
            if name in MUTATORS or name in REORDERS:
                return f"changes a value in place with `.{name}`"
            if name.startswith("_"):
                return f"reaches `.{name}`"
        return None

    def node(self, node: ast.AST, bound: frozenset[str], frame: frozenset[str]) -> str | None:
        if isinstance(node, _COMPREHENSIONS):
            for generator in node.generators:
                if stores := _targets(generator)[1]:
                    return f"stores into `{ast.unparse(stores[0])}`"
        if isinstance(node, ast.NamedExpr):
            return f"binds `{ast.unparse(node.target)}` with `:=`"
        if isinstance(node, (ast.Yield, ast.YieldFrom, ast.Await)):
            return "is a generator"
        if isinstance(node, ast.Name):
            return self.name(node.id, bound) if isinstance(node.ctx, ast.Load) else f"binds `{node.id}`"
        if isinstance(node, ast.Attribute):
            return self.attributes([node.attr])
        if lookup := name_lookup(node, NAME_MAPPER):
            function, path = lookup
            if function in NAMESPACE_LOOKUPS:
                return self.lookup(path, frame)
            return self.attributes(path.split("."))
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
    return _Purity(locals_, imported, changing, is_input).lambda_(node)


def nested_lambdas(node: ast.Lambda) -> Iterator[ast.Lambda]:
    """The lambdas in the body of a lambda, which :func:`impurity` judges with it."""
    for child in ast.walk(node.body):
        if isinstance(child, ast.Lambda):
            yield child


def unfollowed_changes(method: Method, locals_: frozenset[str]) -> Iterator[tuple[ast.AST, str]]:
    """Methods that change their object in place, in a method's code, where the analysis does not follow the change.

    Followed: a call on a local or a `$` name (`acc.append(x)`, `$acc.append(x)`), and `map` of such a method.
    Calls on what a name holds (`$d['k'].append(x)`, `$d.setdefault(k, []).append(x)`) are left as the analysis
    reads them; on any other value (`type(acc).append(acc, x)`, `(acc or []).append(x)`) they are not followed,
    nor the functions of the operator module that change their argument (`operator.iadd(acc, [x])`).
    """
    for stmt in method.body:
        yield from _changes(stmt, locals_, frozenset())


def _receiver(node: ast.expr) -> str | None:
    """The name a mutator is taken from: `acc` of `acc.append` and of `$acc.append`, None for anything else."""
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name):
            return node.value.id
        if (lookup := name_lookup(node.value, NAMESPACE_LOOKUPS)) and "." not in lookup[1]:
            return f"${lookup[1]}"
        return None
    if (lookup := name_lookup(node, NAME_MAPPER)) and lookup[0] == "VFN":
        assert isinstance(node, ast.Call)
        inner = name_lookup(node.args[0], NAMESPACE_LOOKUPS)
        return f"${inner[1]}" if inner and "." not in inner[1] and "." not in lookup[1] else None
    return None


def _held(node: ast.expr) -> bool:
    """Whether a value is what a name holds: the name, an item or attribute of it, or what a method of it gives."""
    while True:
        if isinstance(node, ast.Name) or name_lookup(node, NAMESPACE_LOOKUPS):
            return True
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            node = node.value
        elif (lookup := name_lookup(node, NAME_MAPPER)) and lookup[0] == "VFN":
            assert isinstance(node, ast.Call)
            node = node.args[0]
        elif isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Attribute) or (name_lookup(node.func, NAME_MAPPER) or ("",))[0] == "VFN"
        ):
            node = node.func
        else:
            return False


def _taken_from(function: ast.AST) -> ast.expr:
    """What a method is taken from: `x` of `x.append` and of `VFN(x, 'append', ...)`."""
    if isinstance(function, ast.Attribute):
        return function.value
    assert isinstance(function, ast.Call)
    return function.args[0]


def _mutator(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr in MUTATORS:
        return node.attr
    if (lookup := name_lookup(node, NAME_MAPPER)) and lookup[0] == "VFN" and lookup[1].split(".")[-1] in MUTATORS:
        return lookup[1].split(".")[-1]
    return None


def _changes(node: ast.AST, locals_: frozenset[str], own: frozenset[str]) -> Iterator[tuple[ast.AST, str]]:
    """``own``: the names the comprehensions around ``node`` bind."""
    if isinstance(node, ast.Lambda):
        # A lambda is pure, so it changes nothing, or code the review does not follow at all.
        for default in [*node.args.defaults, *(d for d in node.args.kw_defaults if d is not None)]:
            yield from _changes(default, locals_, own)
        return
    if isinstance(node, _COMPREHENSIONS):
        for generator in node.generators:
            yield from _changes(generator.iter, locals_, own)
            names, stores = _targets(generator)
            for target in stores:
                yield target, f"a comprehension stores into `{ast.unparse(target)}`"
            own = own | names
            for condition in generator.ifs:
                yield from _changes(condition, locals_, own)
        for part in [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]:
            yield from _changes(part, locals_, own)
        return
    called: set[int] = set()
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _OPERATOR_CHANGES:
            if isinstance(func.value, ast.Name) and func.value.id == "operator":
                yield node, f"`operator.{func.attr}` changes its argument in place"
        mapped = node.args and (
            (isinstance(func, ast.Name) and func.id == "map")
            or (name_lookup(func, NAMESPACE_LOOKUPS) or ("", ""))[1] == "map"
        )
        for function in [func, *(node.args[:1] if mapped else [])]:
            name = _mutator(function)
            if name is None:
                continue
            receiver = _receiver(function)
            if receiver is None:
                if function is func:
                    called.add(id(function))
                    taken = _taken_from(function)
                    if not _held(taken):
                        yield node, f"`.{name}` is called on `{ast.unparse(taken)}`, which is not a local of the template"
                continue
            called.add(id(function))
            bare = receiver.lstrip("$")
            if bare in own or not (receiver.startswith("$") or bare in locals_):
                yield node, f"`.{name}` is called on `{receiver}`, which is not a local of the template"
    if (name := _mutator(node)) is not None and id(node) not in called:
        yield node, f"`.{name}` is passed on as a value"
    for child in ast.iter_child_nodes(node):
        if id(child) in called:
            # The method itself is judged, what it is taken from may hold more.
            yield from _changes(_taken_from(child), locals_, own)
            continue
        yield from _changes(child, locals_, own)
