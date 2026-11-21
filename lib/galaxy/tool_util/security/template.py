"""Turn a Cheetah template into a Python AST without running any of it.

Galaxy renders ``<command>`` and ``<configfile>`` with Cheetah, which compiles a template
to a Python module. Analysing that module is exact where scanning the template text is a
guess: Cheetah has already resolved comments, directives, ``\\$`` escapes and placeholder
boundaries, and every write is either a literal string or one expression.

Compiling is not safe by itself. ``#compiler-settings python``, ``#compiler x = <expr>``
and ``#defmacro`` run Python or compile nested templates *while Cheetah parses*, before a
template is ever rendered. :func:`compile_template` refuses such templates, and never asks
Cheetah for a class (which would execute the generated module, including ``#import`` and
``#attr`` lines).
"""

from __future__ import annotations

import ast
import bisect
import re
import warnings
from collections import Counter
from dataclasses import (
    dataclass,
    field,
)
from functools import lru_cache

from Cheetah.Compiler import Compiler
from Cheetah.Parser import Parser

# Directives that execute at parse time. The directive start token cannot change without
# one of them, so a plain text search over-approximates and cannot be evaded.
COMPILE_TIME_DIRECTIVE = re.compile(r"#\s*(compiler-settings|compiler|defmacro|i18n)\b")
# `#encoding name` makes Cheetah eval() the repr of the source re-decoded as `name`. With an encoding
# that maps ASCII to other characters (UTF-7) the repr's quotes can be closed. Same regex as Cheetah's.
ENCODING_DIRECTIVE = re.compile(r"(?:^|\r\n|\r|\n)\s*#\s{0,5}encoding[:\s]*([-\w.]*)")
_ASCII_COMPATIBLE = frozenset(("", "ascii", "us-ascii", "utf-8", "utf8", "latin-1", "latin1", "iso-8859-1"))

_LINE_COMMENT = re.compile(r"# .*?\bline (\d+), col (\d+)\.?\s*$")
_BODY_START = "_filter"


class CompileTimeExecution(Exception):
    """The template contains a directive that runs code when it is compiled."""

    def __init__(self, directive: str, line: int):
        super().__init__(f"#{directive} on line {line}")
        self.directive = directive
        self.line = line


class LinearParser(Parser):  # type: ignore[misc, unused-ignore]  # Cheetah is untyped
    """Cheetah's parser with the same answers in time linear in the template.

    Cheetah's source reader finds the line of a position by scanning every line, the start of a line
    by searching back to the start of the template for a carriage return, and tells whether the text
    at the current position starts with a token by searching the rest of the template for it.
    """

    def lineNum(self, pos: int | None = None) -> int | None:
        if pos is None:
            pos = self._pos
        i = bisect.bisect_right(self._BOLs, pos) - 1
        if i >= 0 and pos <= self._EOLs[i]:
            return i
        return None

    def startswith(self, it: str, pos: int | None = None) -> bool:
        if pos is None or pos == self._pos:
            return self._src.startswith(it, self._pos)
        return bool(super().startswith(it, pos))

    def findBOL(self, pos: int | None = None) -> int:
        if pos is None:
            pos = self._pos
        newline = self._src.rfind("\n", 0, pos)
        return max(newline + 1, self._src.rfind("\r", newline + 1, pos) + 1)


class NoCompileTimeSettings(Compiler):  # type: ignore[misc, unused-ignore]  # Cheetah is untyped
    """Second line of defence behind the text search: these two methods are the ``eval``/``exec`` sinks."""

    parserClass = LinearParser

    def setCompilerSetting(self, key: str, valueExpr: str) -> None:
        raise CompileTimeExecution("compiler", 0)

    def setCompilerSettings(self, keywords: list[str], settingsStr: str) -> None:
        raise CompileTimeExecution("compiler-settings", 0)


@dataclass
class Method:
    name: str
    args: list[str]
    body: list[ast.stmt]
    # Default values of the arguments, and everything else Python evaluates when the method is
    # defined rather than called (defaults, decorators).
    defaults: dict[str, ast.expr] = field(default_factory=dict)
    at_definition: list[ast.expr] = field(default_factory=list)


@dataclass
class CompiledTemplate:
    source: str
    main: Method
    helpers: dict[str, Method] = field(default_factory=dict)
    # Imports and class attributes the template added (#import, #from, #attr, #extends).
    imports: list[ast.stmt] = field(default_factory=list)
    attrs: list[ast.stmt] = field(default_factory=list)
    # Template line of each generated statement, by id() of the statement.
    statement_lines: dict[int, int] = field(default_factory=dict)

    def template_line(self, node: ast.AST) -> int | None:
        """Template line of a generated statement; an estimate where Cheetah left no annotation."""
        return self.statement_lines.get(id(node))


_MODULE_NAME = "DynamicallyCompiledCheetahTemplate"


def _generate(source: str) -> str:
    # Template.compile(returnAClass=False) does the same, then encodes the module as ASCII,
    # which fails for a template with a non-ASCII character.
    compiler = NoCompileTimeSettings(
        source, moduleName=_MODULE_NAME, mainClassName=_MODULE_NAME, mainMethodName="respond", settings={}
    )
    compiler.compile()
    return str(compiler.getModuleCode())


def _imports(tree: ast.Module) -> list[ast.stmt]:
    return [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]


@lru_cache(maxsize=1)
def _baseline_imports() -> Counter[str]:
    """Imports Cheetah puts in every generated module (``os``, ``sys``, ``time``, ``types`` among them)."""
    return Counter(ast.dump(node) for node in _imports(ast.parse(_generate("x"))))


def _method(func: ast.FunctionDef) -> Method:
    body = func.body
    start = 0
    for i, stmt in enumerate(body):
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id == _BODY_START
        ):
            start = i + 1
            break
    end = len(body)
    if body and isinstance(body[-1], ast.Return):
        end -= 1
    args = [a.arg for a in func.args.args if a.arg not in ("self", "trans")]
    positional = func.args.args
    defaults = {
        arg.arg: default
        for arg, default in zip(positional[len(positional) - len(func.args.defaults) :], func.args.defaults)
    }
    at_definition = [*func.args.defaults, *(d for d in func.args.kw_defaults if d is not None), *func.decorator_list]
    return Method(func.name, args, body[start:end], defaults, at_definition)


def _is_literal_write(stmt: ast.stmt) -> str | None:
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name):
        if stmt.value.func.id == "write" and stmt.value.args and isinstance(stmt.value.args[0], ast.Constant):
            value = stmt.value.args[0].value
            return value if isinstance(value, str) else None
    return None


def _statement_lines(body: list[ast.stmt], annotated: dict[int, int], current: int, out: dict[int, int]) -> int:
    """Give every statement a template line.

    Cheetah annotates placeholders and block directives with their line. Between those, a
    literal write advances by the newlines it contains and any other statement is a directive
    on a line of its own (``#set``, ``#silent``).
    """
    for stmt in body:
        end = getattr(stmt, "end_lineno", None) or stmt.lineno
        known = annotated.get(stmt.lineno)
        if known is None and not isinstance(stmt, (ast.If, ast.For, ast.While, ast.Try)):
            known = next((annotated[n] for n in range(stmt.lineno, end + 1) if n in annotated), None)
        if known is not None:
            current = known
        out[id(stmt)] = current
        literal = _is_literal_write(stmt)
        if literal is not None:
            current += literal.count("\n")
            continue
        blocks = [getattr(stmt, name, None) for name in ("body", "orelse", "finalbody")]
        blocks += [handler.body for handler in getattr(stmt, "handlers", [])]
        nested = [block for block in blocks if isinstance(block, list) and block]
        if nested:
            inner = current + 1 if known is not None and not _is_placeholder(stmt) else current
            for block in nested:
                inner = _statement_lines(block, annotated, inner, out)
            current = max(current, inner)
            if not _is_placeholder(stmt):
                current += 1  # the #end line
        elif known is None:
            current += 1
    return current


def _is_placeholder(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.If)
        and isinstance(stmt.test, ast.Compare)
        and isinstance(stmt.test.left, ast.Name)
        and stmt.test.left.id == "_v"
    )


def compile_template(source: str) -> CompiledTemplate:
    """Parse ``source`` with Cheetah's own compiler and return the generated code as an AST.

    Raises :class:`CompileTimeExecution` instead of compiling a template that would run code
    during compilation, and Cheetah's ``ParseError`` or ``SyntaxError`` for a broken template.
    """
    if match := COMPILE_TIME_DIRECTIVE.search(source):
        raise CompileTimeExecution(match.group(1), source.count("\n", 0, match.start()) + 1)
    for match in ENCODING_DIRECTIVE.finditer(source):
        if match.group(1).lower() not in _ASCII_COMPATIBLE:
            raise CompileTimeExecution("encoding", source.count("\n", 0, match.end()) + 1)
    code = _generate(source)
    with warnings.catch_warnings():
        # Template authors write regexes such as '\w' in plain strings; that is not our finding to make.
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(code)
    annotated: dict[int, int] = {}
    for lineno, text in enumerate(code.splitlines(), start=1):
        if match := _LINE_COMMENT.search(text):
            annotated[lineno] = int(match.group(1))
    baseline = _baseline_imports().copy()
    imports = []
    for node in _imports(tree):
        dumped = ast.dump(node)
        if baseline[dumped] > 0:
            baseline[dumped] -= 1
        else:
            imports.append(node)
    main: Method | None = None
    helpers: dict[str, Method] = {}
    attrs: list[ast.stmt] = []
    statement_lines: dict[int, int] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                if item.name == "__init__":
                    continue
                method = _method(item)
                start = annotated.get(item.body[0].lineno - 1, 1) if item.name != "respond" else 1
                _statement_lines(method.body, annotated, start, statement_lines)
                if item.name == "respond":
                    main = method
                else:
                    helpers[item.name] = method
            elif isinstance(item, ast.Assign):
                names = [t.id for t in item.targets if isinstance(t, ast.Name)]
                if not all(name.startswith("_CHEETAH_") or name.startswith("_mainCheetahMethod") for name in names):
                    attrs.append(item)
            elif not (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant)):
                attrs.append(item)
    if main is None:
        # A template can define its own main method, e.g. when it consists of #def blocks only.
        main = Method("respond", [], [])
    return CompiledTemplate(
        source=source,
        main=main,
        helpers=helpers,
        imports=imports,
        attrs=attrs,
        statement_lines=statement_lines,
    )
