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

Every part of the name is a plain identifier, which rules out dunders, mangled and Cheetah's private names; a
part after the first may also have a dash, as parameter names in sections can.

A `#for` over the values of a select, over a list the template sets once, or over a list of text written in it,
gets the same reading: one branch per value, with the value in place of the loop variables, and the text a
branch then sets with `#set` in place of the names it sets (:func:`unroll_known_loops`).
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
    added_imports,
    BODY_START,
    compiled_module,
    constant,
    INCLUDE,
    MACRO_METHOD,
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
_GLOBALS = "_CHEETAH__globalSetVars"

# A call of a helper, the lookup of the helper it calls, and the literal text it passes.
_Call = tuple[ast.Call, ast.Call, tuple[str, ...]]


def specialise_known_helpers(tree: ast.Module) -> set[int]:
    """Replace each known helper only ever called with literal text by one copy per call with that text.

    Returns the getVar calls of the copies, which read the tool namespace.
    """
    namespace_get_vars: set[int] = set()
    template = _template_class(tree)
    if template is None:
        return namespace_get_vars
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


def _template_class(tree: ast.Module) -> ast.ClassDef | None:
    """The one class of the module, when it has Cheetah's own base."""
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    return classes[0] if len(classes) == 1 and _plain_class(classes[0]) else None


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
    looked_up = _word(_LOOKED_UP | {INCLUDE})
    generated = _word(_GENERATED)
    generated_code = _generated_code(tree)
    # Reading getVar or varExists is the use the helpers make of them; looking up the include method is not.
    lookup_paths = {
        id(lookup.args[1])
        for node in ast.walk(tree)
        if (lookup := _lookup(node)) and not (INCLUDE in (path := str(constant(lookup.args[1]))) or _GLOBALS in path)
    }
    global_keys = _global_stores(tree)
    for node in ast.walk(tree):
        if id(node) in generated_code:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            continue
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            if node.attr == INCLUDE or (node.attr == "_CHEETAH__globalSetVars" and id(node) not in global_keys):
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


def _global_stores(tree: ast.Module) -> set[int]:
    """The ``self._CHEETAH__globalSetVars`` of each ``self._CHEETAH__globalSetVars["x"]``, which ``#set global $x``
    stores into."""
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == _GLOBALS
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "self"
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    }


def namespace_names(tree: ast.Module, names: Iterable[str]) -> set[str]:
    """Those of ``names`` that only the namespace can answer for in the template (:func:`_unclaimed`); none when
    it can put a value under any name, through the search list or the ``#set global`` store."""
    if _template_class(tree) is None or _looks_up_search_list(tree) or _reaches_global_store(tree):
        return set()
    bound = bound_names(tree)
    return {name for name in names if _unclaimed(name, bound)}


def _looks_up_search_list(tree: ast.Module) -> bool:
    """Whether a lookup reaches the search list itself (``$searchList()``, ``$SL``, ``$self``)."""
    return any(_lookup_root(node) in (object_names() | method_locals()) - _LOOKED_UP for node in ast.walk(tree))


def _reaches_global_store(tree: ast.Module) -> bool:
    """Whether the template names the ``#set global`` store other than in Cheetah's own code and stores."""
    skipped = _generated_code(tree) | _global_stores(tree)
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        if isinstance(node, ast.Attribute) and node.attr == _GLOBALS:
            return True
        if isinstance(node, ast.Name) and node.id == _GLOBALS:
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _GLOBALS in node.value:
            return True
    return False


def _generated_code(tree: ast.Module) -> set[int]:
    """The nodes of the code Cheetah generates for every template: method preambles, module constants."""
    return _preamble(tree) | {
        id(node) for stmt in tree.body if ast.dump(stmt) in _module_code() for node in ast.walk(stmt)
    }


def self_contained(tree: ast.Module) -> bool:
    """Whether the template has Cheetah's own base and no methods, attributes or imports of its own."""
    return _template_class(tree) is not None and _members(tree) == _baseline_members() and not added_imports(tree)


@lru_cache(maxsize=1)
def _baseline_members() -> frozenset[str]:
    return _members(compiled_module("x"))


def _members(tree: ast.Module) -> frozenset[str]:
    return frozenset(
        ast.dump(stmt)
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for stmt in node.body
        if not (isinstance(stmt, ast.FunctionDef) and stmt.name in ("__init__", "respond"))
    )


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
_PART = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")


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
            # An empty part names nothing: the lookup fails there. Galaxy allows a dash in the name of a
            # parameter in a section or conditional.
            if not all(not part or (_PART if i else IDENTIFIER).match(part) for i, part in enumerate(parts)):
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
    """Give a ``#for`` of the template body over known values (:func:`_loop_values`) one branch per value the
    loop variables can take, with that value in their place, when getVar then looks up literal names only.

    Galaxy accepts only the select's options, and ``str()`` of none selected is ``None``. The loop itself stays,
    so the branches run in the order the values come. Returns the getVar calls of the branches.
    """
    found: set[int] = set()
    template = _template_class(tree)
    literal = _literal_text(tree)
    if template is None or _rebinds(tree, literal):
        return found
    # A lookup that reaches the search list itself can put any value under a name.
    if _looks_up_search_list(tree):
        return found
    bound = bound_names(tree)
    for method in template.body:
        if isinstance(method, ast.FunctionDef) and method.name == "respond":
            macros = _macro_methods(template)
            lists = _global_lists(tree, method, macros, literal)
            calls = _first_calls(method, macros)
            # A statement of the template body, and a template macro from the first statement that calls it.
            scopes = [*enumerate(method.body), *((calls[name], macros[name]) for name in calls)]
            for index, scope in scopes:
                # Set by a statement before this one.
                before = {name: values for name, (at, values) in lists.items() if at < index}
                for loop in reversed([node for node in ast.walk(scope) if isinstance(node, ast.For)]):
                    targets = _loop_targets(loop)
                    values = _loop_values(loop, targets, model, bound, before) if targets else None
                    branches = _branches(loop, targets, values, bound) if targets and values is not None else None
                    if branches is not None:
                        get_vars, loop.body = branches
                        found |= get_vars
    return found


def _macro_methods(template: ast.ClassDef) -> dict[str, ast.FunctionDef]:
    """The methods the review read template macros in as."""
    return {
        node.name: node
        for node in template.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith(MACRO_METHOD)
    }


def _macro_calls(node: ast.AST, macros: dict[str, ast.FunctionDef]) -> set[str]:
    return {path for part in ast.walk(node) if (path := lookup_path(part)) in macros}


def _first_calls(method: ast.FunctionDef, macros: dict[str, ast.FunctionDef]) -> dict[str, int]:
    """For each template macro, the index of the first statement of ``method`` that runs it, through others too."""
    first: dict[str, int] = {}
    for index, stmt in enumerate(method.body):
        pending = list(_macro_calls(stmt, macros))
        while pending:
            if (name := pending.pop()) not in first:
                first[name] = index
                pending.extend(_macro_calls(macros[name], macros))
    return first


def _runs(stmt: ast.stmt, macros: dict[str, ast.FunctionDef]) -> list[ast.stmt]:
    """``stmt``, and the statements a template macro it is a call of always runs: those before any that can return."""
    if not (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call) and not stmt.value.args):
        return [stmt]
    macro = macros.get(lookup_path(stmt.value.func) or "")
    if macro is None:
        return [stmt]
    body = []
    for inner in macro.body:
        if any(isinstance(node, ast.Return) for node in ast.walk(inner)):
            break
        body.append(inner)
    return [stmt, *body]


def _global_lists(
    tree: ast.Module, method: ast.FunctionDef, macros: dict[str, ast.FunctionDef], literal: set[int]
) -> dict[str, tuple[int, tuple[str, ...]]]:
    """Each name `#set global $name = ['a', ...]` in the template body sets, or in a template macro a statement of it
    calls, with that statement's index, when nothing else binds it and only `#for` loops name it."""
    stores = {}
    global_stores = _global_stores(tree)
    for index, stmt in [(index, stmt) for index, top in enumerate(method.body) for stmt in _runs(top, macros)]:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(target := stmt.targets[0], ast.Subscript)
            and id(target.value) in global_stores
            and isinstance(name := constant(target.slice), str)
            and IDENTIFIER.match(name)
            and name not in object_names()
            and isinstance(stmt.value, (ast.List, ast.Tuple))
            and all(isinstance(constant(element), str) for element in stmt.value.elts)
        ):
            stores[name] = (index, tuple(str(constant(element)) for element in stmt.value.elts), target)
    if not stores:
        return {}
    iters = {
        id(lookup.args[1])
        for scope in (method, *macros.values())
        for node in ast.walk(scope)
        if isinstance(node, ast.For) and lookup_path(node.iter) in stores and (lookup := _lookup(node.iter))
    }
    bindings = list(_bindings(tree))
    lists = {}
    for name, (index, values, target) in stores.items():
        if [node for bound, node in bindings if bound == name] != [target]:
            continue
        word = _word({name})
        skip = literal | iters | {id(target.slice)}
        if any(word.search(text) for node in ast.walk(tree) for text in _texts(node, skip)):
            continue
        lists[name] = (index, values)
    return lists


def _lookup_root(node: ast.AST) -> str | None:
    lookup = _lookup(node)
    if lookup is None or not isinstance(lookup.func, ast.Name) or lookup.func.id not in NAMESPACE_LOOKUPS:
        return None
    return str(constant(lookup.args[1])).split(".")[0]


def _loop_targets(loop: ast.For) -> tuple[str, ...] | None:
    """The names of `#for $v in` or `#for $a, $b in`."""
    if isinstance(loop.target, ast.Name):
        return (loop.target.id,)
    if isinstance(loop.target, ast.Tuple) and all(isinstance(name, ast.Name) for name in loop.target.elts):
        return tuple(name.id for name in loop.target.elts if isinstance(name, ast.Name))
    return None


def _loop_values(
    loop: ast.For, targets: tuple[str, ...], model: Model, bound: set[str], lists: dict[str, tuple[str, ...]]
) -> tuple[tuple[str, ...], ...] | None:
    """The values the variables of a loop can take: over a literal list of text (or of tuples of text), the
    values of a select (`str($select).split(',')`, `$select.value`), or a list ``lists`` holds."""
    it = loop.iter
    if isinstance(it, (ast.List, ast.Tuple)):
        return _literal_values(it, len(targets))
    if len(targets) != 1:
        return None
    path = lookup_path(it)
    if path in lists:
        return tuple((value,) for value in lists[path])
    if path is not None and path.endswith(".value"):
        # A multiple select's value is the list of its options, a single select's is one option, its letters.
        options = _select_options(path[: -len(".value")], model, bound)
        if options is None:
            return None
        return tuple((value,) for value in dict.fromkeys([*options, *(c for option in options for c in option)]))
    if not (
        isinstance(it, ast.Call)
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
    ):
        return None
    options = _select_options(path, model, bound)
    return None if options is None else tuple((value,) for value in (*options, "None"))


def _literal_values(it: ast.List | ast.Tuple, arity: int) -> tuple[tuple[str, ...], ...] | None:
    """The elements of a literal list of text, or of tuples of ``arity`` texts."""
    values = []
    for element in it.elts:
        if arity == 1:
            parts = [element]
        elif isinstance(element, (ast.List, ast.Tuple)) and len(element.elts) == arity:
            parts = element.elts
        else:
            return None
        texts = [constant(part) for part in parts]
        if not all(isinstance(text, str) for text in texts):
            return None
        values.append(tuple(str(text) for text in texts))
    return tuple(values)


def _select_options(path: str, model: Model, bound: set[str]) -> tuple[str, ...] | None:
    """The options of the select at ``path``, when the tool lists them and only the namespace answers for it."""
    root, *rest = path.split(".")
    if not _unclaimed(root, bound):
        return None
    found = model.lookup(root)
    nodes = list(found.nodes) if found is not None else []
    for part in rest:
        nodes = [child for node in nodes if isinstance(node, Group) for child in node.children.get(part, ())]
    if len(nodes) != 1 or not isinstance(nodes[0], Value):
        return None
    return nodes[0].options


def _branches(
    loop: ast.For, targets: tuple[str, ...], values: tuple[tuple[str, ...], ...], bound: set[str]
) -> tuple[set[int], list[ast.stmt]] | None:
    """The loop body as `if (a, b) == values: <body with values for a, b>` for each tuple of values, and the
    getVar calls in it; None unless the body reads the variables only as `$a` and its getVar calls then look up
    literal names."""
    body = ast.Module(body=loop.body, type_ignores=[])
    if any(name in targets for name, _ in _bindings(body, set())):
        return None
    branches = []
    for value in values:
        branch = _Substitute(dict(zip(targets, value))).visit(copy.deepcopy(body))
        stmts = _propagate(branch.body)
        if _reads_any(ast.Module(body=stmts, type_ignores=[]), targets):
            return None
        branches.append((value, stmts))
    get_vars = _literal_get_vars([stmt for _, stmts in branches for stmt in stmts], bound)
    if not get_vars:
        return None
    chain: list[ast.stmt] = []
    for value, stmts in reversed(branches):
        left: ast.expr = ast.Name(id=targets[0], ctx=ast.Load())
        right: ast.expr = ast.Constant(value[0])
        if len(targets) > 1:
            left = ast.Tuple(elts=[ast.Name(id=name, ctx=ast.Load()) for name in targets], ctx=ast.Load())
            right = ast.Tuple(elts=[ast.Constant(text) for text in value], ctx=ast.Load())
        test = ast.Compare(left=left, ops=[ast.Eq()], comparators=[right])
        chain = [ast.fix_missing_locations(ast.copy_location(ast.If(test=test, body=stmts, orelse=chain), loop))]
    return get_vars, chain


def _propagate(stmts: list[ast.stmt]) -> list[ast.stmt]:
    """Put the text each `#set $n = 'text'` of ``stmts`` sets in place of the `$n` that follow it, up to a
    statement that binds `n` again."""
    known: dict[str, str] = {}
    found = []
    for stmt in stmts:
        for name, _ in _bindings(stmt, set()):
            known.pop(name, None)
        if known:
            stmt = _Substitute(dict(known)).visit(stmt)
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(target := stmt.targets[0], ast.Name)
            and isinstance(text := constant(stmt.value), str)
        ):
            known[target.id] = text
        found.append(stmt)
    return found


def _reads_any(method: ast.AST, names: tuple[str, ...]) -> bool:
    """Whether a method still reads one of ``names``, as a Python name or the first part of a lookup."""
    for node in ast.walk(method):
        if isinstance(node, ast.Name) and node.id in names:
            return True
        if (lookup := _lookup(node)) and str(constant(lookup.args[1])).split(".")[0] in names:
            return True
    return False


class _Substitute(ast.NodeTransformer):
    """Put literal text in place of the lookups of a helper's arguments or loop variables, and join or
    ``replace`` literal text."""

    def __init__(self, values: dict[str, str]):
        self.values = values

    def _own_frame(self, node: ast.AST) -> ast.AST:
        # Its lookups search its own frame, without the method's locals, then the namespace.
        return node

    visit_Lambda = visit_GeneratorExp = visit_ListComp = visit_SetComp = visit_DictComp = _own_frame

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
        # `'a:b'.replace(':', '_')`, which Cheetah compiles to `VFN('a:b', 'replace', False)(':', '_')`.
        method = node.func
        if (
            isinstance(method, ast.Call)
            and isinstance(method.func, ast.Name)
            and method.func.id == "VFN"
            and len(method.args) == 3
            and not method.keywords
            and isinstance(text := constant(method.args[0]), str)
            and constant(method.args[1]) == "replace"
            and constant(method.args[2]) is False
            and len(node.args) == 2
            and not node.keywords
            and all(isinstance(constant(arg), str) for arg in node.args)
        ):
            return ast.copy_location(
                ast.Constant(text.replace(str(constant(node.args[0])), str(constant(node.args[1])))), node
            )
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        left, right = constant(node.left), constant(node.right)
        if isinstance(node.op, ast.Add) and isinstance(left, str) and isinstance(right, str):
            return ast.copy_location(ast.Constant(left + right), node)
        return node
