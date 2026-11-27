"""#def helpers of widely installed tools that look a variable up with ``getVar`` by the name their caller passes.

``getVar`` of a computed name can reach any variable, which the review reports as reflection. A known
helper that is only ever called with literal text renders the same as one copy of it per call, the text in place
of its arguments, and in a copy ``getVar`` looks up a literal name, which the review follows.

Nothing else may reach the helper: a template that names it any other way, or that rebinds a name its calls and
lookups go through, is left as it is. A computed name that reaches it (``getVar``, ``getattr``, ``vars``) is
reflection by itself.

The copies are made only when each name they look up is a tool input, found where the review reads it.
``getVar`` (and Cheetah's ``$name`` inside the helper, after the helper's own arguments) searches, in order:

* the ``#set global`` store, a dict: the name is not a key the template stores anywhere (dead code and later
  writes too), nor an attribute of a dict, which the lookup also accepts;
* the template object: the name is not an attribute of a compiled template, nor one the template defines
  (``#def``, ``#block``, ``#attr``, ``$self.x``);
* the namespace: the template binds the name nowhere else, so it is a tool input, a job parameter of that
  name, or nothing, and the review reads these getVar calls as such
  (:attr:`~.template.CompiledTemplate.namespace_get_vars`).

Every part of the name is a plain identifier, which rules out dunders, mangled and Cheetah's private names.

A `#for` over the values of a select gets the same reading: one branch per value, with the value in place of
the loop variable (:func:`unroll_known_loops`).
"""

from __future__ import annotations

import ast
import copy
import re
from collections import Counter
from collections.abc import (
    Iterable,
    Iterator,
)
from functools import lru_cache
from typing import TYPE_CHECKING

from Cheetah.Template import Template

from galaxy.util.tree_dict import TreeDict
from .nodes import Value
from .template import (
    BODY_START,
    compiled_module,
    constant,
    NAME_MAPPER,
    NAMESPACE_LOOKUPS,
)
from .values import Group

if TYPE_CHECKING:
    from .model import Model

# The Cheetah source of each known helper, in every version tools-iuc has had.
KNOWN_HELPERS = (
    # bowtie2, bwa, bwa_mem2 and picard: read_group_macros.xml.
    """#def rg_param(name)
    #if $varExists("rg")
        #return $rg.get($name, None)
    #else
        #return $getVar($name, None)
    #end if
#end def""",
    # picrust2: macros.xml.
    """#def getVarCond($sec_cond, $var)
    #if $varExists($var)
        #return $getVar($var)
    #else if $varExists($sec_cond + "." + $var)
        #return $getVar($sec_cond + "." + $var)
    #else
        #return
    #end if
#end def""",
    """#def getVarCond($var)
    ## $var $varExists($var) $varExists("predict_pathways." + $var)
    #if $varExists($var)
        #return $getVar($var)
    #else if $varExists("predict_pathways." + $var)
        #return $getVar("predict_pathways." + $var)
    #else
        #return
    #end if
#end def""",
)

# Names that Cheetah looks up in the namespace, whose binding decides what a helper's lookups reach.
_LOOKED_UP = frozenset(("getVar", "varExists", "hasVar"))
# Names of the generated code that its calls and writes go through.
_GENERATED = frozenset(("SL", "write", "_filter", "_CHEETAH__globalSetVars", *NAME_MAPPER))
_INCLUDE = "_handleCheetahInclude"
_GLOBALS = "_CHEETAH__globalSetVars"

# A call of a helper, the lookup of the helper it calls, and the literal text it passes.
_Call = tuple[ast.Call, ast.Call, tuple[str, ...]]


def specialise_known_helpers(tree: ast.Module) -> set[int]:
    """Replace each known helper only ever called with literal text by one copy per call with that text.

    Returns the getVar calls of the copies, which read the tool namespace.
    """
    namespace_get_vars: set[int] = set()
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if len(classes) != 1 or not _plain_class(classes[0]):
        return namespace_get_vars
    template = classes[0]
    literal = _literal_text(tree)
    if _rebinds(tree, literal):
        return namespace_get_vars
    methods = [node for node in template.body if isinstance(node, ast.FunctionDef)]
    defined = Counter(method.name for method in methods)
    for method in methods:
        arguments = _references().get(ast.dump(method))
        if arguments is None or defined[method.name] != 1:
            continue
        calls = _literal_calls(tree, method, len(arguments), literal)
        if calls is None:
            continue
        copies = _copies(tree, method, arguments, calls, literal)
        if copies is None:
            continue
        get_vars = _namespace_get_vars(copies.values(), bound_names(tree))
        if get_vars is None:
            continue
        namespace_get_vars |= get_vars
        index = template.body.index(method)
        template.body[index : index + 1] = list(copies.values())
        for call, lookup, values in calls:
            lookup.args[1] = ast.copy_location(ast.Constant(copies[values].name), lookup.args[1])
            call.args = []
    return namespace_get_vars


@lru_cache(maxsize=1)
def _references() -> dict[str, tuple[str, ...]]:
    """The dump of the method each known helper compiles to, with the names of its arguments."""
    references = {}
    for source in KNOWN_HELPERS:
        for node in ast.walk(compiled_module(source)):
            if isinstance(node, ast.FunctionDef) and node.name not in ("__init__", "respond"):
                references[ast.dump(node)] = tuple(arg.arg for arg in node.args.args[1:])
    return references


def _plain_class(template: ast.ClassDef) -> bool:
    """A template class with Cheetah's own base, whose namespace lookups are those of ``Template``."""
    bases = template.bases
    return (
        len(bases) == 1
        and isinstance(bases[0], ast.Name)
        and bases[0].id == "Template"
        and not template.keywords
        and not template.decorator_list
    )


def _literal_text(tree: ast.Module) -> set[int]:
    """The constants that are text the template writes, and the source text Cheetah passes its filter."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "write" and len(node.args) == 1 and isinstance(node.args[0], ast.Constant):
                found.add(id(node.args[0]))
            elif node.func.id == "_filter":
                found.update(id(k.value) for k in node.keywords if k.arg == "rawExpr")
    return found


def _texts(node: ast.AST, skip: set[int]) -> Iterator[str]:
    """The names a node binds or reads, and the value of a constant that is not in ``skip``."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str) and id(node) not in skip:
            yield node.value
        return
    for field, value in ast.iter_fields(node):
        if field == "type_comment":
            continue
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            yield from (item for item in value if isinstance(item, str))


def _word(names: frozenset[str] | set[str]) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(name) for name in sorted(names)) + r")(?!\w)")


def _preamble(tree: ast.Module) -> set[int]:
    """The nodes of the code Cheetah puts before the body of each method."""
    found: set[int] = set()
    for method in ast.walk(tree):
        if not isinstance(method, ast.FunctionDef):
            continue
        for stmt in method.body:
            found.update(id(node) for node in ast.walk(stmt))
            if isinstance(stmt, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == BODY_START for target in stmt.targets
            ):
                break
        else:
            # A method without the preamble is not one Cheetah generated.
            found.difference_update(id(node) for stmt in method.body for node in ast.walk(stmt))
    return found


def _rebinds(tree: ast.Module, literal: set[int]) -> bool:
    """Whether the template binds or reaches a name that lookups and writes go through, or includes a template."""
    looked_up = _word(_LOOKED_UP | {_INCLUDE})
    generated = _word(_GENERATED)
    generated_code = _generated_code(tree)
    # Reading getVar or varExists is the use the helpers make of them; looking up the include method is not.
    lookup_paths = {
        id(lookup.args[1])
        for node in ast.walk(tree)
        if (lookup := _lookup(node)) and not (_INCLUDE in (path := str(constant(lookup.args[1]))) or _GLOBALS in path)
    }
    global_keys = set()
    for node in ast.walk(tree):
        # `#set global $x` stores into `self._CHEETAH__globalSetVars["x"]`.
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "_CHEETAH__globalSetVars"
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "self"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            global_keys.add(id(node.value))
    for node in ast.walk(tree):
        if id(node) in generated_code:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            continue
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            if node.attr == _INCLUDE or (node.attr == "_CHEETAH__globalSetVars" and id(node) not in global_keys):
                return True
            continue
        if isinstance(node, ast.FunctionDef) and node.args.args and node.args.args[0].arg == "self":
            # `self` is the first argument of every method; its other names are checked as ast.arg nodes.
            if looked_up.search(node.name) or generated.search(node.name):
                return True
            continue
        if isinstance(node, ast.arg) and node.arg == "self":
            continue
        for text in _texts(node, literal | lookup_paths):
            if looked_up.search(text):
                return True
            if not isinstance(node, ast.Constant) and generated.search(text):
                return True
            # Only Cheetah's own stores and reads reach the #set global store.
            if _GLOBALS in text:
                return True
    return False


def _generated_code(tree: ast.Module) -> set[int]:
    """The nodes of the code Cheetah generates for every template: method preambles, module constants."""
    return _preamble(tree) | {
        id(node) for stmt in tree.body if ast.dump(stmt) in _module_code() for node in ast.walk(stmt)
    }


def bound_names(tree: ast.Module) -> set[str]:
    """Every name the template binds: Python names, arguments, imports, #def and #attr names, attributes of
    ``self`` and keys of the ``#set global`` store."""
    return {name for name, _ in _bindings(tree)}


def _bindings(tree: ast.AST, generated_code: set[int] | None = None) -> Iterator[tuple[str, ast.AST]]:
    """Each name ``tree`` binds, with the node that binds it."""
    if generated_code is None:
        generated_code = _generated_code(tree) if isinstance(tree, ast.Module) else set()
    for node in ast.walk(tree):
        if id(node) in generated_code:
            continue
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            yield node.id, node
        elif isinstance(node, ast.Attribute) and not isinstance(node.ctx, ast.Load):
            yield node.attr, node
        elif isinstance(node, ast.Subscript) and not isinstance(node.ctx, ast.Load):
            if isinstance(key := constant(node.slice), str):
                yield key.replace("$", "").split(".")[0], node
        elif isinstance(node, ast.arg):
            yield node.arg, node
        elif isinstance(node, ast.alias):
            yield (node.asname or node.name).split(".")[0], node
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            yield node.name, node
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            yield from ((name, node) for name in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            yield node.name, node


IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")


@lru_cache(maxsize=1)
def object_names() -> frozenset[str]:
    """Names a lookup finds on the #set global store, a namespace mapping or a compiled template object: their
    instance attributes too (the ``data`` of the TreeDict Galaxy retries the namespace as)."""
    return frozenset(dir(Template("x", searchList=[{}]))) | frozenset(dir({})) | frozenset(dir(TreeDict({})))


def _namespace_get_vars(copies: Iterable[ast.FunctionDef], bound: set[str]) -> set[int] | None:
    """The getVar calls of the copies, when each name they and the copies' other lookups read is one only the
    namespace can answer for; None otherwise."""
    for clone in copies:
        for node in ast.walk(clone):
            lookup = _lookup(node)
            if lookup is not None and isinstance(lookup.func, ast.Name) and lookup.func.id in NAMESPACE_LOOKUPS:
                root = str(constant(lookup.args[1])).split(".")[0]
                if root not in _LOOKED_UP and not _unclaimed(root, bound):
                    return None
    return _literal_get_vars(copies, bound)


def _literal_get_vars(nodes: Iterable[ast.AST], bound: set[str]) -> set[int] | None:
    """The getVar calls in ``nodes``, when each looks up a literal name only the namespace can answer for;
    None otherwise."""
    found = set()
    for top in nodes:
        for node in ast.walk(top):
            if not isinstance(node, ast.Call) or _namespace_lookup(node.func, "getVar") is None:
                continue
            name = constant(node.args[0]) if node.args else None
            if not isinstance(name, str):
                return None
            parts = name.replace("$", "").split(".")
            # An empty part names nothing: the lookup fails there.
            if not all(not part or IDENTIFIER.match(part) for part in parts):
                return None
            if parts[0] and not _unclaimed(parts[0], bound):
                return None
            found.add(id(node))
    return found


def lookup_path(node: ast.AST) -> str | None:
    """The path of `$a.b`: `VFFSL(SL, "a.b", True)`, each part a plain name."""
    lookup = _lookup(node)
    if (
        lookup is None
        or not isinstance(lookup.func, ast.Name)
        or lookup.func.id not in NAMESPACE_LOOKUPS
        or lookup.keywords
        or len(lookup.args) != 3
        or not (isinstance(lookup.args[0], ast.Name) and lookup.args[0].id == "SL")
    ):
        return None
    path = str(constant(lookup.args[1]))
    return path if all(IDENTIFIER.match(part) for part in path.split(".")) else None


@lru_cache(maxsize=1)
def method_locals() -> frozenset[str]:
    """The locals Cheetah gives every template method (``SL``, ``write``, ``trans``): a lookup finds them first."""
    names = {"self"}
    for node in ast.walk(compiled_module("$x")):
        if isinstance(node, ast.FunctionDef) and node.name == "respond":
            names.update(name for name, _ in _bindings(ast.Module(body=node.body, type_ignores=[]), set()))
            names.update(arg.arg for arg in node.args.args + node.args.kwonlyargs)
    return frozenset(names)


def _unclaimed(name: str, bound: set[str]) -> bool:
    """A plain name that only the namespace can answer for: a tool input, a job parameter, or nothing."""
    return (
        bool(IDENTIFIER.match(name))
        and name not in bound
        and name not in object_names()
        and name not in method_locals()
    )


@lru_cache(maxsize=1)
def _module_code() -> frozenset[str]:
    """The statements Cheetah puts at the top of every module it generates: its imports, ``VFFSL = ...``."""
    return frozenset(ast.dump(stmt) for stmt in compiled_module("x").body if not isinstance(stmt, ast.ClassDef))


def _lookup(node: ast.AST) -> ast.Call | None:
    """A NameMapper call with a literal name: `VFFSL(SL, "a.b", True)`."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in NAME_MAPPER
        and len(node.args) > 1
        and isinstance(constant(node.args[1]), str)
    ):
        return node
    return None


def _literal_calls(tree: ast.Module, method: ast.FunctionDef, arity: int, literal: set[int]) -> list[_Call] | None:
    """Every call of a helper, with its lookup and its ``arity`` literal strings; None if the template names it
    any other way."""
    calls = []
    paths: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or (lookup := _namespace_lookup(node.func, method.name)) is None:
            continue
        values = [constant(arg) for arg in node.args]
        if node.keywords or len(values) != arity or not all(isinstance(value, str) for value in values):
            return None
        calls.append((node, lookup, tuple(str(value) for value in values)))
        paths.add(id(lookup.args[1]))
    word = _word({method.name})
    for node in ast.walk(tree):
        if node is method:
            continue
        if any(word.search(text) for text in _texts(node, literal | paths)):
            return None
    return calls


def _namespace_lookup(node: ast.AST, name: str) -> ast.Call | None:
    """The lookup Cheetah makes for `$name(...)`: `VFFSL(SL, "name", False)`."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in NAMESPACE_LOOKUPS
        and not node.keywords
        and len(node.args) == 3
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "SL"
        and constant(node.args[1]) == name
        and isinstance(node.args[2], ast.Constant)
        and node.args[2].value is False
    ):
        return node
    return None


def _copies(
    tree: ast.Module,
    method: ast.FunctionDef,
    arguments: tuple[str, ...],
    calls: list[_Call],
    literal: set[int],
) -> dict[tuple[str, ...], ast.FunctionDef] | None:
    """A copy of the helper for each text it is called with, under a name the template does not use."""
    used = {word for node in ast.walk(tree) for text in _texts(node, literal) for word in re.findall(r"\w+", text)}
    copies: dict[tuple[str, ...], ast.FunctionDef] = {}
    for _, _, values in calls:
        if values in copies:
            continue
        index = len(copies)
        while f"{method.name}_{index}" in used:
            index += 1
        name = f"{method.name}_{index}"
        used.add(name)
        clone = _Substitute(dict(zip(arguments, values))).visit(copy.deepcopy(method))
        clone.name = name
        clone.args.args = clone.args.args[:1]
        if _reads_any(clone, arguments):
            return None
        copies[values] = ast.fix_missing_locations(clone)
    return copies


def unroll_known_loops(tree: ast.Module, model: Model) -> set[int]:
    """Give a ``#for`` of the template body over the values of a select one branch per value the loop variable
    can take, with that value in its place, when getVar then looks up literal names only.

    Galaxy accepts only the select's options, and ``str()`` of none selected is ``None``. The loop itself stays,
    so the branches run in the order the values come. Returns the getVar calls of the branches.
    """
    found: set[int] = set()
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if len(classes) != 1 or not _plain_class(classes[0]) or _rebinds(tree, _literal_text(tree)):
        return found
    # A lookup that reaches the search list itself can put any value under a name.
    if any(_lookup_root(node) in (object_names() | method_locals()) - _LOOKED_UP for node in ast.walk(tree)):
        return found
    bound = bound_names(tree)
    for method in classes[0].body:
        if isinstance(method, ast.FunctionDef) and method.name == "respond":
            for loop in reversed([node for node in ast.walk(method) if isinstance(node, ast.For)]):
                values = _loop_values(loop, model, bound)
                branches = _branches(loop, values, bound) if values is not None else None
                if branches is not None:
                    get_vars, loop.body = branches
                    found |= get_vars
    return found


def _lookup_root(node: ast.AST) -> str | None:
    lookup = _lookup(node)
    if lookup is None or not isinstance(lookup.func, ast.Name) or lookup.func.id not in NAMESPACE_LOOKUPS:
        return None
    return str(constant(lookup.args[1])).split(".")[0]


def _loop_values(loop: ast.For, model: Model, bound: set[str]) -> tuple[str, ...] | None:
    """The values the variable of `#for $v in str($select).split(',')` can take."""
    it = loop.iter
    if not (
        isinstance(loop.target, ast.Name)
        and isinstance(it, ast.Call)
        and isinstance(it.func, ast.Attribute)
        and it.func.attr == "split"
        and not it.keywords
        and len(it.args) == 1
        and constant(it.args[0]) == ","
        and isinstance(text := it.func.value, ast.Call)
        and isinstance(text.func, ast.Name)
        and text.func.id == "str"
        and "str" not in bound
        and not text.keywords
        and len(text.args) == 1
        and (path := lookup_path(text.args[0])) is not None
        and _unclaimed(path.split(".")[0], bound)
    ):
        return None
    root, *rest = path.split(".")
    found = model.lookup(root)
    nodes = list(found.nodes) if found is not None else []
    for part in rest:
        nodes = [child for node in nodes if isinstance(node, Group) for child in node.children.get(part, ())]
    if len(nodes) != 1 or not isinstance(nodes[0], Value) or nodes[0].options is None:
        return None
    return (*nodes[0].options, "None")


def _branches(loop: ast.For, values: tuple[str, ...], bound: set[str]) -> tuple[set[int], list[ast.stmt]] | None:
    """The loop body as `if v == value: <body with value for v>` for each value, and the getVar calls in it;
    None unless the body reads the variable only as `$v` and its getVar calls then look up literal names."""
    assert isinstance(loop.target, ast.Name)
    target = loop.target.id
    body = ast.Module(body=loop.body, type_ignores=[])
    if any(name == target for name, _ in _bindings(body, set())):
        return None
    branches = []
    for value in values:
        branch = _Substitute({target: value}).visit(copy.deepcopy(body))
        if _reads_any(branch, (target,)):
            return None
        branches.append((value, branch.body))
    get_vars = _literal_get_vars([stmt for _, stmts in branches for stmt in stmts], bound)
    if not get_vars:
        return None
    chain: list[ast.stmt] = []
    for value, stmts in reversed(branches):
        test = ast.Compare(left=ast.Name(id=target, ctx=ast.Load()), ops=[ast.Eq()], comparators=[ast.Constant(value)])
        chain = [ast.fix_missing_locations(ast.copy_location(ast.If(test=test, body=stmts, orelse=chain), loop))]
    return get_vars, chain


def _reads_any(method: ast.AST, names: tuple[str, ...]) -> bool:
    """Whether a method still reads one of ``names``, as a Python name or the first part of a lookup."""
    for node in ast.walk(method):
        if isinstance(node, ast.Name) and node.id in names:
            return True
        if (lookup := _lookup(node)) and str(constant(lookup.args[1])).split(".")[0] in names:
            return True
    return False


class _Substitute(ast.NodeTransformer):
    """Put literal text in place of the lookups of a helper's arguments, and join literal text that is added."""

    def __init__(self, values: dict[str, str]):
        self.values = values

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in NAMESPACE_LOOKUPS
            and len(node.args) == 3
            and not node.keywords
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "SL"
            and constant(node.args[1]) in self.values
        ):
            # An argument is a local of the helper: the lookup finds it before the namespace.
            return ast.copy_location(ast.Constant(self.values[str(constant(node.args[1]))]), node)
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        left, right = constant(node.left), constant(node.right)
        if isinstance(node.op, ast.Add) and isinstance(left, str) and isinstance(right, str):
            return ast.copy_location(ast.Constant(left + right), node)
        return node
