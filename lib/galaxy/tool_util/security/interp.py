"""Follow user-controlled values through a compiled template to the places they are written.

An abstract interpreter over the Python code Cheetah generates. It does not run the template:
it walks every branch, keeps for each variable the characters a user could put into it
(:class:`~.model.AV`), and at each write asks the shell lexer where the text lands.
"""

from __future__ import annotations

import ast
import builtins
import dataclasses
import re
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    Callable,
    FrozenSet,
)

from Cheetah.Template import Template

from . import (
    charsets,
    sed,
    shell,
)
from .charsets import Verdict
from .model import (
    Model,
    SAFE_SPECIALS,
)
from .nodes import (
    Data,
    dataset_content,
    file_content,
    Special,
    user_preference,
)
from .report import (
    Finding,
    OPAQUE,
    QUOTE_CLOSERS,
    Report,
    source_refs,
    SourceRef,
    VULNERABILITY,
)
from .template import (
    CompiledTemplate,
    Method,
)
from .validators import regex_constraint
from .values import (
    attribute,
    AV,
    CLEAN,
    concat,
    CONDITIONAL,
    contents,
    element,
    Group,
    introduced,
    join,
    raw,
    recording,
    REPR_PUNCTUATION,
    stringify,
)

_MAX_STATES = 64
_MAX_DEPTH = 8
# Statements one template may cost. The largest template in tools-iuc needs about 4,200; a template
# built to explode (helpers calling helpers in loops) is cut off here and reported as not analysed.
_MAX_STEPS = 50_000


class _BudgetExceeded(Exception):
    pass


_NAME_MAPPER = ("VFFSL", "VFSL", "VFN", "VFL")
_MUTATORS = frozenset(("append", "extend", "add", "insert", "update", "setdefault", "appendleft", "__setitem__"))
_CLEAN_FUNCTIONS = frozenset(
    (
        "int float len bool abs round ord hex oct bin sum any all isinstance hasattr callable id hash range"
        " divmod pow type varExists hasVar __get_data_table_entry__ os.path.exists os.path.isfile"
        " os.path.isdir os.path.getsize os.path.isabs math.ceil math.floor math.log math.sqrt"
    ).split()
)
# Python that starts a process, evaluates code or opens a file: a sink inside the Galaxy server process.
_SERVER_SINK = re.compile(
    r"^(os\.(system|popen\w*|exec\w*|spawn\w*)|subprocess\.\w+|commands\.\w+|eval|exec|execfile|__import__|open)$"
)
# Functions that turn harmless-looking text into arbitrary characters.
_DECODERS = re.compile(
    r"^(base64\.\w*decode\w*|binascii\.(unhexlify|a2b_\w+)|bytes\.fromhex|bytearray\.fromhex|codecs\.decode"
    r"|urllib\.parse\.unquote\w*|html\.unescape|json\.loads|ast\.literal_eval|zlib\.decompress)$"
)
_ENCODERS = re.compile(
    r"^(base64\.(\w*b64encode|b32encode|b16encode|encodebytes)|binascii\.(hexlify|b2a_hex)|hashlib\.\w+)$"
)
# What json.dumps writes around the strings of a list or a dict.
_JSON_PUNCTUATION: charsets.Chars = frozenset('"\\[]{},: ')
# What escaping a value for a syntax writes around or into it, whatever the value holds.
_ESCAPING_ADDS: dict[str, charsets.Chars] = {
    # shlex.quote("a'b") is 'a'"'"'b'.
    "shlex": frozenset("'\""),
    "json": _JSON_PUNCTUATION,
    "pyrepr": REPR_PUNCTUATION,
}


def _literal_chars(value: AV) -> charsets.Chars:
    """The probe characters of the literal text in a value and its elements."""
    chars = frozenset().union(*(charsets.probe(p) for p in value.parts or () if isinstance(p, str)))
    for inner in (*(value.items or ()), *((value.elem,) if value.elem is not None else ()), *value.alts):
        chars = chars | _literal_chars(inner)
    return chars


def _matched_chars(old: Any) -> charsets.Chars:
    """Characters a value holds where str.replace(old, new) puts new text: the job check sees them.

    The job check counts a carriage return as a newline, which replace("\\r", "\\n") makes of it.
    """
    if not isinstance(old, str) or not old:
        return charsets.NONE
    return charsets.probe(old) | (frozenset("\n") if "\r" in old else charsets.NONE)


# How a quote character moves the quote state of shell text: none (""), single or double quotes.
_QUOTE_MOVES = {("", "'"): "'", ("", '"'): '"', ("'", "'"): "", ('"', '"'): ""}


def _after_text(states: frozenset[str], text: str) -> frozenset[str]:
    after = set()
    for state in states:
        for char in text:
            state = _QUOTE_MOVES.get((state, char), state)
        after.add(state)
    return frozenset(after)


def _kept_literal_chars(item: AV, separator: AV) -> charsets.Chars:
    """The literal text each element of a join writes around its own value (`"'%s'" % x`).

    The join is written as two elements and the separator between them. That shows every quote
    state a longer join reaches when a third element can only start in a quote state the first or
    the second started in, from wherever the join is written. An element can be one of several
    strings; its values move no quotes (their own quotes are theirs to be checked for).
    """
    if not item.tainted or separator.parts is None or separator.tainted:
        return charsets.NONE
    texts = ["".join(part for part in string.parts or () if isinstance(part, str)) for string in item.alts or (item,)]
    between = "".join(part for part in separator.parts if isinstance(part, str))
    literal = "".join(texts) + between
    if set(literal) & set("\\`$"):
        return charsets.NONE

    def next_starts(starts: frozenset[str]) -> frozenset[str]:
        return _after_text(frozenset().union(*(_after_text(starts, text) for text in texts)), between)

    for state in ("", "'", '"'):
        first = frozenset((state,))
        second = next_starts(first)
        if not next_starts(second) <= first | second:
            return charsets.NONE
    return charsets.probe(literal)


def _ansi_quoted(chars: charsets.Chars, script: bool = False) -> Verdict | None:
    """A value in $'...', where a backslash can escape the closing quote, which is as good as a quote."""
    verdict = charsets.single_quoted(chars | {"'"} if "\\" in chars else chars, script)
    if verdict is not None and "\\" in chars:
        verdict = verdict._replace(breakout=_verdict_breakout(verdict) | {"\\"})
    return verdict


def _verdict_breakout(verdict: Verdict) -> charsets.Chars:
    return verdict.chars if verdict.breakout is None else verdict.breakout


def _unquoted_harm(chars: charsets.Chars, language: str, script: bool) -> charsets.Chars:
    """The characters that run code when a value with these characters is outside any quotes."""
    if language != "shell" and language not in shell.CODE_LANGUAGES:
        # A data file: nothing in it runs.
        return charsets.NONE
    after = charsets.unquoted(chars, script=script) if language == "shell" else charsets.code(language, chars, "")
    return after.chars if after is not None and after.severity in (charsets.HIGH, charsets.CRITICAL) else charsets.NONE


def _breakout(
    verdict: Verdict, text: AV, language: str, escaped: charsets.Chars, script: bool
) -> tuple[charsets.Chars, charsets.Chars, charsets.Chars]:
    """The characters of the user's value, before any escaping the template applies, that a finding needs.

    Returns ``(breakout, requires, closes)``: a value must contain one of ``breakout`` and, when
    ``requires`` is not empty, one of ``requires``; ``closes`` are its characters that close or open
    quotes where it is written. Escaping writes quotes whatever the value holds (shlex.quote,
    json.dumps, repr): when one of them is a breakout character, the escaping itself leaves the
    place, the value must bring what is dangerous after it, and any quote of its own that the
    escaping leaves as it is (repr writes `'` raw inside "...") then opens new quotes.
    """
    breakout = _verdict_breakout(verdict)
    added = _ESCAPING_ADDS.get(text.quoted, charsets.NONE) | escaped
    if not breakout & added:
        return breakout, verdict.requires, breakout & QUOTE_CLOSERS
    rest = text.chars - added
    return (breakout - added) | _unquoted_harm(rest, language, script), charsets.NONE, text.chars & QUOTE_CLOSERS


_STRING_FUNCTIONS = frozenset(("str", "unicode", "repr", "format", "basestring"))
_CONTAINER_FUNCTIONS = frozenset(("list", "tuple", "set", "frozenset", "sorted", "reversed", "iter", "next"))
_NONE_METHODS = frozenset(("reverse", "sort", "clear", "remove"))
# str methods whose result keeps the escaping of the text when their literal arguments hold no quote.
_ESCAPE_KEEPING_METHODS = frozenset(
    ("strip", "lstrip", "rstrip", "replace", "lower", "upper", "title", "capitalize", "casefold")
)
_CASE_METHODS = frozenset(("lower", "upper", "casefold"))
# str methods whose result holds only characters of the value and of their literal arguments.
_PRESERVING_METHODS = frozenset(
    (
        "strip lstrip rstrip lower upper casefold title capitalize swapcase zfill center ljust rjust"
        " removeprefix removesuffix __str__"
    ).split()
)
_QUOTING: charsets.Chars = frozenset("'\"\\`")
_CLEAN_METHODS = frozenset(
    (
        "startswith endswith find rfind index rindex count isdigit isalpha isalnum isspace islower isupper"
        " isnumeric isdecimal istitle isidentifier is_of_type element_is_set"
    ).split()
)

# How a configfile's language is recognised: the command that reads it, or its content.
_CONTENT_LANGUAGES = (
    ("sh", re.compile(r"^\s*#!\s*/\S*(ba|z|da)?sh\b")),
    ("python", re.compile(r"^\s*#!.*python|^\s*(import \w+|from \w+ import|def \w+\()", re.MULTILINE)),
    ("R", re.compile(r"^\s*#!.*Rscript|\blibrary\(|<-\s|\bsuppressMessages\(", re.MULTILINE)),
    ("perl", re.compile(r"^\s*#!.*perl|^\s*use strict", re.MULTILINE)),
)


def configfile_language(content: str, reader: str | None) -> str:
    """The language of a configfile, "data" when it is not a program."""
    if reader in ("source", "."):
        return "sh"
    if reader and (language := shell.language_of(reader)):
        return language
    for language, pattern in _CONTENT_LANGUAGES:
        if pattern.search(content):
            return language
    return "data"


# Prefixes of Env keys set by #if tests. "=x.y": the narrowed value of exactly this template name;
# its attributes (`.value`, string methods) still give the raw value. "~cond": a conditional
# restricted to some <when> blocks; the parameters below it are looked up in the restricted group.
NARROWED = "="
RESTRICTED = "~"


def _narrowing_key(key: str) -> bool:
    return key[:1] in (NARROWED, RESTRICTED)


def _keys_of(local: dict[str, AV], name: str) -> list[str]:
    """The narrowing keys about a name and its attributes."""
    return [k for k in local if _narrowing_key(k) and (k[1:] == name or k[1:].startswith(f"{name}."))]


@dataclass
class Env:
    local: dict[str, AV] = field(default_factory=dict)
    shared: dict[str, AV] = field(default_factory=dict)  # #set global

    def copy(self) -> Env:
        return Env(dict(self.local), self.shared)

    def merge(self, others: list[Env]) -> None:
        names = set(self.local)
        for other in others:
            names.update(other.local)
        for name in names:
            envs = [self] + others
            if _narrowing_key(name) and any(name not in o.local for o in others):
                # Narrowed on one path only: elsewhere the name has its full value again.
                self.local.pop(name, None)
                continue
            self.local[name] = join(*(o.local.get(name) for o in envs))

    def assign(self, name: str, value: AV, weak: bool = False) -> None:
        self.local[name] = join(self.local.get(name), value) if weak else value
        # What a test showed about the old value, or its attributes, does not hold for the new one.
        for key in _keys_of(self.local, name):
            del self.local[key]


@dataclass(frozen=True)
class _Text:
    """Lexer state of a configfile: only string literals are tracked."""

    quote: str = ""
    esc: bool = False
    escaped: str = ""  # as ShellState.escaped
    evaluated: bool = False  # the current string is code the script runs: eval('...'), parse(text = '...')
    fstring: bool = False  # the current string is a Python f-string: {...} in it is code


# What opens a string that the script itself runs as code, by configfile language: the text before the quote.
_EVALUATED_STRING = {
    "python": re.compile(r"(?<![\w.])(eval|exec|compile)\s*\(\s*[rRbBuUfF]{0,2}$"),
    "R": re.compile(r"(?<![\w.])(parse\s*\(\s*text\s*=|str2lang\s*\(|str2expression\s*\()\s*$"),
    "sh": re.compile(r"(?<![\w.-])(eval|(ba|da|z)?sh\s+-c)\s+$"),
    "perl": re.compile(r"(?<![\w$])eval\s*\(?\s*$"),
}

_FSTRING_PREFIX = re.compile(r"(?<![\w.])([fF][rR]?|[rR][fF])$")

States = FrozenSet[Any]
_COLLECTOR = "_captureCollector_"

_PERCENT = re.compile(r"%(\(\w+\))?[-+ #0]*\d*(?:\.\d+)?([sdrifgGeExXc%])")
_BRACES = re.compile(r"\{\{|\}\}|\{(\d*)\}|[{}]")


def _const(node: ast.AST | None) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _percent_format(text: str, values: list[AV]) -> AV | None:
    """`text % values` as an ordered mix of literal text and values, None when the format is not simple."""
    parts: list[str | AV] = []
    position = used = 0
    for match in _PERCENT.finditer(text):
        parts.append(text[position : match.start()])
        position = match.end()
        if match.group(2) == "%":
            parts.append("%")
        elif match.group(1) or used >= len(values):
            return None
        else:
            parts.append(values[used])
            used += 1
    if used != len(values):
        return None
    parts.append(text[position:])
    return concat(parts)


def _brace_format(text: str, values: list[AV]) -> AV | None:
    parts: list[str | AV] = []
    position = automatic = 0
    for match in _BRACES.finditer(text):
        parts.append(text[position : match.start()])
        position = match.end()
        token = match.group(0)
        if token in ("{{", "}}"):
            parts.append(token[0])
        elif match.group(1) is None:
            return None
        else:
            index = int(match.group(1)) if match.group(1) else automatic
            automatic += 1
            if index >= len(values):
                return None
            parts.append(values[index])
    parts.append(text[position:])
    return concat(parts)


def _unwrap_str(node: ast.expr) -> ast.expr:
    """``str(x)`` is ``x`` as the template writes it."""
    while (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str" and len(node.args) == 1
    ):
        node = node.args[0]
    return node


def _template_path(node: ast.expr) -> str | None:
    """The dotted name of a ``$name`` placeholder, as Cheetah compiles it."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _NAME_MAPPER:
        if node.func.id == "VFN":
            return None
        path = _const(node.args[1]) if len(node.args) > 1 else None
        return path if isinstance(path, str) else None
    if isinstance(node, ast.Name):
        return node.id
    return None


def _constrained(value: AV, constraint: Any) -> AV:
    """A value a test showed to be accepted by a regular expression."""
    text = stringify(value)
    if not text.tainted:
        return text
    chars = text.chars & constraint.chars
    lead = (text.chars if text.lead is None else text.lead) & constraint.lead & chars
    return AV(
        chars=chars,
        sources=text.sources,
        quoted=text.quoted,
        whole=text.whole,
        lead=lead,
        words=(text.words if text.words is not None else chars) & constraint.word_first(),
    )


def _without_removed(value: AV, removed: charsets.Removed) -> AV:
    text = stringify(value)
    if not text.tainted:
        return text
    chars = text.chars - removed.everywhere
    lead = (text.chars if text.lead is None else text.lead) - removed.everywhere - removed.start
    return AV(chars=chars, sources=text.sources, quoted=text.quoted, whole=text.whole, lead=lead, words=text.words)


# What int() and float() accept besides digits and letters (inf, nan, 1e5); int() of a parameter
# wrapper converts through float(). Whitespace is accepted at either end only, where it cannot split
# the value into several words, and in a command a newline becomes a space. Only digits, a sign
# and a dot are left to the user, so the whitespace is not tracked.
_NUMBER_CHARS = {"int": frozenset("+-_."), "float": frozenset("+-_.")}


def _number(value: AV, function: str) -> AV:
    text = stringify(value)
    if not text.tainted:
        return text
    chars = text.chars & _NUMBER_CHARS[function]
    return AV(chars=chars, sources=text.sources, whole=text.whole, lead=chars, words=chars)


class TemplateAnalysis:
    def __init__(
        self,
        model: Model,
        template: CompiledTemplate,
        report: Report,
        location: str = "command",
        language: str = "shell",
    ):
        self.model = model
        self.template = template
        self.report = report
        self.location = location
        self.language = language
        # A shell script keeps its lines; Galaxy writes the command on one line.
        self.script = language == "shell" and location != "command"
        self.events: set[shell.Event] = set()
        # configfile name -> commands that take it as an argument
        self.readers: dict[str, set[str]] = {}
        self._capture: list[list[AV]] = []
        self._returns: list[list[AV]] = []
        self._pending: ast.expr | None = None  # expression of the placeholder about to be written
        self._depth = 0
        self._steps = 0
        # Characters template code, not the user, can bring into the value of a source, as plain
        # text (str.replace, a decoder, an unknown function) or as the quotes of an escaping.
        self._introduced: dict[SourceRef, charsets.Chars] = {}
        self._escapes: dict[SourceRef, charsets.Chars] = {}
        # Every source of a user value the template writes, with what does harm in it unquoted.
        self._written: dict[SourceRef, charsets.Chars] = {}
        # Quote characters of values that an escaping's own quote leaves outside their string.
        self._closers: dict[SourceRef, charsets.Chars] = {}
        self._in_capture_region = 0
        self._noted: set[str] = set()
        self._line: int | None = None
        # Above zero while evaluating code that may not run (one arm of `a if c else b`, a #try body):
        # a conversion there that would fail says nothing about the value.
        self._speculative = 0
        self._in_try = 0  # inside a #try body, where a #raise may be caught
        # Names the template imports (`#from os.path import splitext`), by their full name.
        self._imported: dict[str, str] = {}
        for node in template.imports:
            if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for alias in node.names:
                    self._imported[alias.asname or alias.name] = f"{node.module}.{alias.name}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        self._imported[alias.asname] = alias.name
                    else:
                        top = alias.name.split(".")[0]
                        self._imported[top] = top

    # -- entry ---------------------------------------------------------------------------------

    def run(self) -> None:
        if self.language == "shell":
            initial: shell.ShellState | _Text = shell.INITIAL if self.location == "command" else shell.SCRIPT
        else:
            initial = _Text()
        try:
            with recording(self._record):
                states = self.block(self.template.main.body, frozenset((initial,)), Env())
        except _BudgetExceeded:
            self.note("template is too expensive to analyse, the review of it is incomplete")
            return
        finally:
            self._mark_unchecked()
        if self.language == "shell":
            for state in states:
                shell.finish(state, self.events)

    def _record_escape_closer(self, text: AV, quotes: tuple[str, ...]) -> None:
        """An escaping that writes the quote of the string the value is in closes it: the value's own
        quotes, which the escaping writes as they are when they differ from its own, open new ones."""
        refs = source_refs(text.sources)
        escaped = _ESCAPING_ADDS.get(text.quoted, charsets.NONE).union(
            *(self._escapes.get(ref, charsets.NONE) for ref in refs)
        )
        closing = {"'" if quote == shell.ANSI else quote for quote in quotes if quote}
        own = text.chars & QUOTE_CLOSERS
        if own and closing & escaped:
            for ref in refs:
                self._closers[ref] = self._closers.get(ref, charsets.NONE) | own

    def _record_closers(self, text: AV, closers: charsets.Chars) -> None:
        """Characters of the value that change how the text after it is quoted.

        A backslash at the end escapes the closing quote of the value's string, which then closes
        the string of the next value instead; outside quotes, a quote opens a string.
        """
        for ref in source_refs(text.sources):
            self._closers[ref] = self._closers.get(ref, charsets.NONE) | closers

    def _record_write(self, text: AV) -> None:
        refs = source_refs(text.sources)
        escaped = frozenset().union(*(self._escapes.get(ref, charsets.NONE) for ref in refs))
        harm = _unquoted_harm(
            text.chars - _ESCAPING_ADDS.get(text.quoted, charsets.NONE) - escaped, self.language, self.script
        )
        for ref in refs:
            self._written[ref] = self._written.get(ref, charsets.NONE) | harm

    def _record(self, sources: frozenset[str], chars: charsets.Chars, escape: bool) -> None:
        into = self._escapes if escape else self._introduced
        for ref in source_refs(sources):
            into[ref] = into.get(ref, charsets.NONE) | chars

    def _introduce(self, value: AV, chars: charsets.Chars = charsets.PROBE) -> None:
        introduced(stringify(value) if value.nodes else value, chars)

    def _unchecked(self, refs: tuple[SourceRef, ...], needed: charsets.Chars) -> tuple[SourceRef, ...]:
        return tuple(ref for ref in refs if self._introduced.get(ref, charsets.NONE) & needed)

    def _mark_unchecked(self) -> None:
        """Decide, for the whole template, which findings a character test on job values can judge.

        One value can change how everything after it is quoted: a stray quote flips the quoting of
        the rest of the line, so a quote from one value and a command character from another are
        enough. So:

        * a source the template rewrites is not checkable, wherever it is written (also when the
          rewrite comes after a finding, in a later loop pass);
        * when any finding of the template has a source that is not checkable or opaque, or a
          written source is opaque or rewritten so that it can gain a quote or a character that
          does harm unquoted, it can bring the quote that lets the other values out: no finding
          of the template is checkable, and its writes are not recorded;
        * otherwise the template's writes go into Report.writes: when the job check sees a value
          close its quotes (a finding with a quote in ``breakout``, at any severity), the harmful
          characters of every written value count, also of values that have no finding.
        """
        indexes = [
            i for i, f in enumerate(self.report.findings) if f.location == self.location and f.kind == VULNERABILITY
        ]
        for i in indexes:
            finding = self.report.findings[i]
            needed = finding.breakout | finding.requires | finding.closes
            unchecked = set(finding.unchecked) | set(self._unchecked(finding.refs, needed))
            self.report.findings[i] = dataclasses.replace(finding, unchecked=tuple(sorted(unchecked, key=repr)))
        poisoned = any(
            f.unchecked or any(ref.accessor == OPAQUE for ref in f.refs)
            for f in (self.report.findings[i] for i in indexes)
        ) or any(
            ref.accessor == OPAQUE or self._introduced.get(ref, charsets.NONE) & (QUOTE_CLOSERS | harm)
            for ref, harm in self._written.items()
        )
        if not poisoned:
            for recorded, into in ((self._written, self.report.writes), (self._closers, self.report.closers)):
                if recorded:
                    by_ref = into.setdefault(self.location, {})
                    for ref, chars in recorded.items():
                        by_ref[ref] = by_ref.get(ref, charsets.NONE) | chars
        for i in indexes:
            finding = self.report.findings[i]
            if poisoned and finding.refs:
                self.report.findings[i] = dataclasses.replace(finding, unchecked=finding.refs)

    def note(self, message: str) -> None:
        if message not in self._noted:
            self._noted.add(message)
            self.report.unanalyzed.append(f"{self.location}: {message}")

    # -- statements ----------------------------------------------------------------------------

    def block(self, stmts: list[ast.stmt], states: States, env: Env) -> States:
        for stmt in stmts:
            states = self.statement(stmt, states, env)
            if len(states) > _MAX_STATES:
                states = frozenset(sorted(states, key=repr)[:_MAX_STATES])
                self.report.unanalyzed.append(f"{self.location}: too many shell contexts to follow, some dropped")
        return states

    def statement(self, stmt: ast.stmt, states: States, env: Env) -> States:
        self._steps += 1
        if self._steps > _MAX_STEPS:
            raise _BudgetExceeded()
        line = self.template.template_line(stmt)
        if line is not None:
            self._line = line
        if isinstance(stmt, ast.Expr):
            return self.expression_statement(stmt.value, states, env)
        if isinstance(stmt, ast.Assign):
            # `#capture name` ... `#end capture`: Cheetah swaps the writer for a collector, then reads it.
            if any(isinstance(t, ast.Name) and t.id.startswith(_COLLECTOR) for t in stmt.targets):
                self._capture.append([])
                self._in_capture_region += 1
                return states
            source = ast.unparse(stmt.value)
            if self._in_capture_region and source.startswith(_COLLECTOR) and source.endswith(".getvalue()"):
                written = self._capture.pop()
                self._in_capture_region -= 1
                text = join(*written) if written else CLEAN
                for target in stmt.targets:
                    self.bind(target, AV(chars=text.chars, sources=text.sources, whole=False), env)
                return states
            if len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id == "_v":
                # Cheetah writes a placeholder as `_v = <expr>` followed by `if _v is not None: write(...)`.
                self._pending = stmt.value
                return states
            value = self.ev(stmt.value, env)
            for target in stmt.targets:
                self.bind(target, value, env)
            return states
        if isinstance(stmt, ast.AugAssign):
            value = self.ev(stmt.value, env)
            if isinstance(stmt.target, ast.Name):
                env.assign(stmt.target.id, stringify(value) if value.nodes else value, weak=True)
            else:
                self.bind(stmt.target, value, env, weak=True)
            return states
        if isinstance(stmt, ast.If):
            if self._is_placeholder_write(stmt):
                pending, self._pending = self._pending, None
                return self.write_placeholder(pending, self._raw_expr(stmt), states, env)
            self.ev(stmt.test, env)
            then_env, else_env = env.copy(), env.copy()
            when_true, when_false = self.narrowing(stmt.test, env)
            for target, narrow in when_true:
                self.apply_narrowing(target, narrow, then_env)
            for target, narrow in when_false:
                self.apply_narrowing(target, narrow, else_env)
            out = self.block(stmt.body, states, then_env) | self.block(stmt.orelse, states, else_env)
            # A branch that ends in #continue, #break or #return does not reach the code after the #if.
            then_leaves, else_leaves = self._leaves(stmt.body), self._leaves(stmt.orelse)
            env.local = {}
            if then_leaves and not else_leaves:
                env.merge([else_env])
            elif else_leaves and not then_leaves:
                env.merge([then_env])
            else:
                env.merge([then_env, else_env])
            return out
        if isinstance(stmt, (ast.For, ast.While)):
            before = dict(env.local)
            out = states
            current = states
            for _ in range(3):
                if isinstance(stmt, ast.For):
                    self.bind(stmt.target, element(self.ev(stmt.iter, env)), env, weak=True)
                else:
                    self.ev(stmt.test, env)
                current = self.block(stmt.body, current, env)
                if current <= out:
                    break
                out = current = out | current
            # The body may run zero times, or leave early (#continue, #break): after the loop a name can
            # still have its value from before, and what an iteration narrowed does not hold.
            for key, value in list(env.local.items()):
                if value is before.get(key):
                    continue
                if _narrowing_key(key):
                    del env.local[key]
                elif key in before:
                    env.local[key] = join(before[key], value)
            return self.block(stmt.orelse, out, env)
        if isinstance(stmt, ast.Try):
            self._speculative += 1
            self._in_try += 1
            try:
                body_env = env.copy()
                out = self.block(stmt.body, states, body_env)
                # A handler starts wherever the body stopped: from before it, or from after it.
                handler_envs = []
                for handler in stmt.handlers:
                    handler_env = Env(shared=env.shared)
                    handler_env.merge([env.copy(), body_env])
                    out = out | self.block(handler.body, states | out, handler_env)
                    handler_envs.append(handler_env)
                out = self.block(stmt.orelse, out, body_env)
            finally:
                self._speculative -= 1
                self._in_try -= 1
            env.local = {}
            env.merge([body_env, *handler_envs])
            return self.block(stmt.finalbody, out, env)
        if isinstance(stmt, ast.With):
            return self.block(stmt.body, states, env)
        if isinstance(stmt, ast.Return) and stmt.value is not None and self._returns:
            self._returns[-1].append(self.ev(stmt.value, env))
        return states

    # -- narrowing by #if tests ---------------------------------------------------------------

    def _leaves(self, stmts: list[ast.stmt]) -> bool:
        """The block ends in a statement after which the code that follows the #if does not run."""
        if not stmts:
            return False
        last = stmts[-1]
        if isinstance(last, ast.Raise):
            return not self._in_try
        return isinstance(last, (ast.Continue, ast.Break, ast.Return))

    def narrowing(self, test: ast.expr, env: Env) -> tuple[list[tuple[ast.expr, Any]], list[tuple[ast.expr, Any]]]:
        """What a test that is true, or false, says about the values it looks at.

        Each entry pairs the expression of the value (a template name or a local variable) with
        a function from its abstract value to the narrowed one. Tests that are not recognised
        say nothing.
        """
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            when_true, when_false = self.narrowing(test.operand, env)
            return when_false, when_true
        if isinstance(test, ast.BoolOp):
            parts = [self.narrowing(value, env) for value in test.values]
            if isinstance(test.op, ast.And):
                return [n for when_true, _ in parts for n in when_true], []
            return [], [n for _, when_false in parts for n in when_false]
        if isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute):
            name = ast.unparse(test.func)
            pattern = _const(test.args[0]) if test.args else None
            if name in ("re.match", "re.search", "re.fullmatch") and len(test.args) == 2 and not test.keywords:
                if isinstance(pattern, str) and (name != "re.search" or charsets.regex_anchored_start(pattern)):
                    if name == "re.fullmatch":
                        pattern = f"(?:{pattern})\\Z"
                    constraint = regex_constraint(pattern)
                    return [(test.args[1], lambda v, c=constraint: _constrained(v, c))], []
            return [], []
        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            left, op, right = test.left, test.ops[0], test.comparators[0]
            found: tuple[list[tuple[ast.expr, Any]], list[tuple[ast.expr, Any]]] = ([], [])
            if isinstance(op, (ast.Eq, ast.NotEq)):
                found = self._equal_narrowing(left, right, env) or self._equal_narrowing(right, left, env) or ([], [])
            elif isinstance(op, (ast.In, ast.NotIn)) and isinstance(right, (ast.List, ast.Tuple, ast.Set)):
                literals = [_const(elt) for elt in right.elts]
                if literals and all(isinstance(literal, str) for literal in literals):
                    found = self._literal_narrowing(left, [str(literal) for literal in literals], env)
            return found if isinstance(op, (ast.Eq, ast.In)) else (found[1], found[0])
        return [], []

    def _equal_narrowing(
        self, target: ast.expr, other: ast.expr, env: Env
    ) -> tuple[list[tuple[ast.expr, Any]], list[tuple[ast.expr, Any]]] | None:
        """Narrowings when `target == other` is true, and when it is false; None when there are none."""
        literal = _const(other)
        if isinstance(literal, str):
            found = self._literal_narrowing(target, [literal], env)
            return found if found != ([], []) else None
        # `x == re.sub(pattern, '_', x)`: the value holds no character the pattern replaces, except
        # those of the replacement itself.
        replacement = _const(other.args[1]) if isinstance(other, ast.Call) and len(other.args) == 3 else None
        if (
            isinstance(other, ast.Call)
            and ast.unparse(other.func) in ("re.sub", "re.subn")
            and len(other.args) == 3
            and not other.keywords
            and isinstance(_const(other.args[0]), str)
            and isinstance(replacement, str)
            and "\\" not in replacement
            and ast.unparse(_unwrap_str(other.args[2])) == ast.unparse(_unwrap_str(target))
        ):
            removed = charsets.regex_removed(str(_const(other.args[0])))
            if removed is not None:
                kept = charsets.probe(replacement)
                removed = charsets.Removed(removed.everywhere - kept, removed.start - kept, removed.start_repeats)
                return [(target, lambda v, r=removed: _without_removed(v, r))], []
        return None

    def _literal_narrowing(
        self, target: ast.expr, literals: list[str], env: Env
    ) -> tuple[list[tuple[ast.expr, Any]], list[tuple[ast.expr, Any]]]:
        """Narrowings when the target is one of the literals, and when it is none of them."""
        groups = self._conditional_groups(target, env)
        if groups is not None:
            # `$cond.selector == 'a'`: only the parameters of the <when value="a"> block exist.
            prefix = _template_path(_unwrap_str(target))
            if prefix is None:
                return [], []
            group_target = ast.Constant(value=prefix.rsplit(".", 1)[0])
            sides: list[list[tuple[ast.expr, Any]]] = []
            for values in (set(literals), None):
                restricted = [
                    group.restrict(values if values is not None else set(group.case_values) - set(literals))
                    for group in groups
                ]
                if any(r is None for r in restricted):
                    sides.append([])
                else:
                    sides.append([(group_target, lambda v, r=restricted: AV(nodes=tuple(r)))])
            return sides[0], sides[1]
        value = join(*(AV(parts=(literal,)) if literal else CLEAN for literal in literals))
        return [(target, lambda v, value=value: value)], []

    def _conditional_groups(self, target: ast.expr, env: Env) -> list[Group] | None:
        """The conditionals whose selector the expression is, None when it is not a selector."""
        path = _template_path(_unwrap_str(target))
        if path is None or "." not in path:
            return None
        parent, selector = path.rsplit(".", 1)
        owner = self.resolve(parent, env, False)
        groups = [node for node in owner.nodes if isinstance(node, Group)]
        if not groups or len(groups) != len(owner.nodes) or any(g.selector != selector for g in groups):
            return None
        return groups

    def apply_narrowing(self, target: ast.expr, narrow: Any, env: Env) -> None:
        target = _unwrap_str(target)
        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            # A dotted template name given directly (the conditional that owns a selector).
            env.local[RESTRICTED + target.value] = narrow(self.resolve(target.value, env, False))
            return
        if isinstance(target, ast.Name) and target.id in env.local:
            current = env.local[target.id]
            if not current.nodes:
                env.local[target.id] = narrow(current)
            return
        path = _template_path(target)
        if path is None:
            return
        first = path.split(".")[0]
        if first not in env.local and first in env.shared:
            # `#set global` names can change in any #def the template calls.
            return
        if "." not in path and path in env.local:
            if not env.local[path].nodes:
                env.local[path] = narrow(env.local[path])
            # A local holding a parameter: `$p.value` and the like stay raw, so nothing is narrowed.
            return
        env.local[NARROWED + path] = narrow(stringify(self.resolve(path, env, True)))

    @staticmethod
    def _is_placeholder_write(stmt: ast.If) -> bool:
        test = stmt.test
        return (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "_v"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.IsNot)
        )

    @staticmethod
    def _raw_expr(stmt: ast.If) -> str | None:
        for node in ast.walk(stmt):
            if isinstance(node, ast.keyword) and node.arg == "rawExpr":
                value = _const(node.value)
                return value if isinstance(value, str) else None
        return None

    def expression_statement(self, node: ast.expr, states: States, env: Env) -> States:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "write" and node.args:
            arg = node.args[0]
            text = _const(arg)
            if isinstance(text, str):
                return self.write_literal(text, states)
            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "_filter" and arg.args:
                return self.write_value(self.ev(arg.args[0], env), None, states, env)
            return self.write_value(self.ev(arg, env), None, states, env)
        self.ev(node, env)
        return states

    def bind(self, target: ast.expr, value: AV, env: Env, weak: bool = False) -> None:
        if isinstance(target, ast.Name):
            env.assign(target.id, value, weak)
        elif isinstance(target, (ast.Tuple, ast.List)):
            if value.items is not None and len(value.items) == len(target.elts):
                for elt, item in zip(target.elts, value.items):
                    self.bind(elt, item, env, weak)
            else:
                for elt in target.elts:
                    self.bind(elt.value if isinstance(elt, ast.Starred) else elt, element(value), env, weak)
        elif isinstance(target, ast.Subscript):
            base = target.value
            # self._CHEETAH__globalSetVars["name"] = value, from `#set global`
            key = _const(target.slice)
            if isinstance(base, ast.Attribute) and base.attr == "_CHEETAH__globalSetVars" and isinstance(key, str):
                env.shared[key] = join(env.shared.get(key), value) if weak else value
                for narrowed in _keys_of(env.local, key):
                    del env.local[narrowed]
            elif name := self._local_name(base, env):
                env.assign(name, AV(elem=join(value, self.ev(target.slice, env))), weak=True)

    # -- writes --------------------------------------------------------------------------------

    def write_literal(self, text: str, states: States) -> States:
        if self._capture:
            return states
        if self.language == "shell":
            return frozenset(shell.feed(state, text, self.events) for state in states)
        return frozenset(self._feed_text(state, text, self.language) for state in states)

    @staticmethod
    def _feed_text(state: _Text, text: str, language: str = "") -> _Text:
        quote, esc, escaped, evaluated, fstring = state.quote, state.esc, state.escaped, state.evaluated, state.fstring
        opener = _EVALUATED_STRING.get(language)
        code = ""  # program text of this chunk before the current position, outside strings
        for c in text:
            if c == "\n" and not esc:
                # Only a value on the same line is taken to follow the escaped quote: a Python string
                # ends with its line, and elsewhere every later quote of the script would be off by
                # one, which rarely still parses.
                escaped = ""
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif quote:
                if c == quote or c == "\n":
                    quote = ""
                    evaluated = fstring = False
            elif c in "'\"":
                quote = c
                evaluated = bool(opener and opener.search(code[-40:]))
                fstring = language == "python" and bool(_FSTRING_PREFIX.search(code[-3:]))
            if not quote:
                code = "" if c == "\n" else code + c
        return _Text(quote, esc, escaped, evaluated, fstring)

    def write_placeholder(self, node: ast.expr | None, raw_expr: str | None, states: States, env: Env) -> States:
        if isinstance(node, ast.Call) and not self._capture:
            callee = self.ev(node.func, env)
            if callee.helper and not self._returns_value(callee.helper):
                # `$helper(...)` written directly: its text continues the surrounding command.
                args = [self.ev(arg, env) for arg in node.args]
                keywords = {k.arg: self.ev(k.value, env) for k in node.keywords if k.arg}
                return self.inline(callee.helper, args, states, env, keywords)
        return self.write_value(self.ev(node, env), raw_expr, states, env)

    def _returns_value(self, name: str) -> bool:
        """A helper with `#return value` is a function: its result is written, not what it wrote."""
        method = self.template.helpers.get(name)
        return method is not None and any(
            isinstance(node, ast.Return) and node.value is not None for stmt in method.body for node in ast.walk(stmt)
        )

    def write_value(self, value: AV, raw_expr: str | None, states: States, env: Env) -> States:
        if value.helper and not self._capture:
            if self._returns_value(value.helper):
                return self.write_value(self.call_helper(value.helper, [], env), raw_expr, states, env)
            return self.inline(value.helper, [], states, env)
        text = stringify(value)
        if text.tainted:
            self._record_write(text)
        if self._capture:
            self._capture[-1].append(text)
            return states
        if text.alts:
            # One of several strings: each is written from here, with the quotes of its own literal text.
            after_any: States = frozenset()
            for alternative in text.alts:
                after_any = after_any | self.write_value(alternative, raw_expr, states, env)
            return after_any
        if text.parts is not None and (len(text.parts) != 1 or isinstance(text.parts[0], str)):
            # A string assembled in Python: its literal text is command text like any other.
            for part in text.parts:
                if isinstance(part, str):
                    states = self.write_literal(part, states)
                else:
                    states = self.write_value(part, raw_expr, states, env)
            return states
        if self.language != "shell":
            if not text.tainted:
                return states
            after_config: set[_Text] = set()
            for state in states:
                escaped = bool(state.quote) and state.escaped == state.quote
                self.judge_config(text, state.quote, raw_expr, escaped, state.evaluated, state.fstring)
                self._record_escape_closer(text, (state.quote,))
                if self._can_escape_config_quote(text, state.quote):
                    self._record_closers(text, frozenset("\\"))
                    state = _Text(state.quote, state.esc, state.quote, state.evaluated, state.fstring)
                after_config.add(state)
            return frozenset(after_config)
        out = set()
        for state in states:
            context, after = shell.placeholder(state)
            if context.comment:
                out.add(after)
                continue
            self.note_reader(value, context)
            if text.tainted:
                escaped = bool(context.quote) and state.escaped == context.quote
                self.judge_shell(text, context, raw_expr, escaped)
                self._record_escape_closer(text, (context.quote, context.inner))
                own_escapes = text.quoted == "dq-escaped" and context.quote == '"'
                if context.quote in ('"', shell.ANSI) and not context.lang and "\\" in text.chars and not own_escapes:
                    self._record_closers(text, frozenset("\\"))
                    after = after._replace(escaped=context.quote)
                if not context.quote and text.quoted != "shlex" and (opening := text.chars & frozenset("'\"\\")):
                    # shlex.quote balances the quotes it writes; any other quote here opens a string.
                    self._record_closers(text, opening)
            out.add(after)
        return frozenset(out)

    def _can_escape_config_quote(self, text: AV, quote: str) -> bool:
        """The value can end in a backslash that escapes the closing quote of a string in a program."""
        if not quote or "\\" not in text.chars or self.language not in shell.CODE_LANGUAGES:
            return False
        if text.quoted == "json" or (text.quoted == "pyrepr" and self.language == "python"):
            return False
        # In sh only double quotes treat a backslash as an escape.
        return self.language != "sh" or quote == '"'

    def note_reader(self, value: AV, context: shell.Context) -> None:
        # `Rscript '$script'`, `R --vanilla < '$script'`, `awk -f '$script'`: the program the command runs.
        if not (context.cmd and (context.first_arg or context.role in ("stdin", "scriptfile"))):
            return
        if context.cmd in shell.PROGRAM_IS_ARGUMENT and context.role != "scriptfile":
            # awk and sed take their program as an argument or with -f: any other file is data.
            return
        for node in value.nodes:
            if isinstance(node, Special) and node.path.startswith("configfile:"):
                self.readers.setdefault(node.path[len("configfile:") :], set()).add(context.cmd)

    def judge_shell(self, text: AV, context: shell.Context, raw_expr: str | None, escaped: bool = False) -> None:
        """``escaped``: an earlier user value in the same kind of quotes can end in a backslash."""
        chars = text.chars
        verdicts: list[Verdict] = []
        script = self.script
        if escaped and (verdict := charsets.unquoted(chars, text.words, script)):
            # The earlier value escaped its closing quote, so the quote that opens this value closes
            # that string instead, and this value is written unquoted.
            self.finding(
                verdict._replace(why=f"{verdict.why}, once an earlier value escapes the closing quote"),
                text,
                f"{context.describe()}, after a value that can end in a backslash",
                raw_expr,
                needs_closer="'" if context.quote == shell.ANSI else context.quote,
            )
        if context.role == "cmd" and context.lead and text.whole:
            verdicts.append(
                Verdict("command-position", charsets.HIGH, chars, "chooses the program that is run", charsets.NONE)
            )
        quoted_for_here = text.quoted == "shlex" and not context.quote and not context.lang
        if not quoted_for_here:
            if text.quoted == "shlex":
                chars = chars | {"'"}
            elif text.quoted == "pyrepr" and text.tainted:
                chars = chars | (REPR_PUNCTUATION if "'" in chars else REPR_PUNCTUATION - {'"'})
            # What the shell reads of the word. A program inside it still gets the quote.
            outer = chars
            if text.quoted == "sq-escaped" and context.quote == "'":
                # The sanitizer writes a quote as '"'"', which stays inside the single-quoted word.
                outer = chars - {"'"}
            elif text.quoted == "dq-escaped" and context.quote == '"':
                # The template writes a double quote as \", and the value has no backslash of its own.
                outer = chars - {'"', "\\"}
            if not context.lang:
                chars = outer
            lexical: dict[str, Callable[[charsets.Chars], Verdict | None]] = {
                "": lambda c: charsets.unquoted(c, text.words, script),
                "'": lambda c: charsets.single_quoted(c, script),
                '"': lambda c: charsets.double_quoted(c, script),
                # In $'...' a backslash can escape the closing quote, which is as good as a quote.
                shell.ANSI: lambda c: _ansi_quoted(c, script),
            }
            if verdict := lexical[context.quote](outer):
                verdicts.append(verdict)
            if context.lang == "sh":
                if verdict := lexical[context.inner](chars):
                    verdicts.append(
                        verdict._replace(rule="nested-interpreter", why=f"in the nested shell, {verdict.why}")
                    )
            elif context.lang == "sed" and context.sed is not None:
                # With --sandbox, GNU sed refuses a program with e, r, w or the e and w flags of s.
                if not context.sandbox and (verdict := sed.verdict(chars, context.sed)):
                    verdicts.append(verdict)
            elif context.lang:
                if verdict := charsets.code(context.lang, chars, context.inner):
                    verdicts.append(verdict)
        if not verdicts and "/" in chars:
            if context.role in ("redir", "stdin") or (context.role == "arg" and context.cmd in shell.FILE_COMMANDS):
                verdicts.append(
                    Verdict(
                        "path-traversal",
                        charsets.MEDIUM,
                        frozenset("/"),
                        "can name a file outside the job directory",
                    )
                )
        first = chars if text.lead is None else text.lead
        if not verdicts and "-" in chars and "-" in first and context.option_position:
            verdicts.append(
                Verdict(
                    "option-injection",
                    charsets.LOW,
                    frozenset("-"),
                    "can begin with a dash and be read as an option",
                )
            )
        for verdict in verdicts:
            self.finding(verdict, text, context.describe(), raw_expr)

    def judge_config(
        self,
        text: AV,
        quote: str,
        raw_expr: str | None,
        escaped: bool = False,
        evaluated: bool = False,
        fstring: bool = False,
    ) -> None:
        """``escaped``: an earlier user value in the same kind of string can end in a backslash.
        ``evaluated``: the string is code that the script runs (``eval('...')``).
        ``fstring``: the string is a Python f-string."""
        chars = text.chars
        if fstring and "{" in chars and text.quoted != "json":
            # {...} in an f-string is an expression; with parentheses it can call anything.
            severity = charsets.HIGH if "(" in chars else charsets.MEDIUM
            self.finding(
                Verdict(
                    "configfile-injection",
                    severity,
                    chars & frozenset("{}()"),
                    "can open an f-string expression",
                    frozenset("{"),
                ),
                text,
                f"inside an f-string {quote}...{quote} of a python script",
                raw_expr,
            )
        if evaluated and self.language in shell.CODE_LANGUAGES:
            # Escaping only keeps the value inside the string; the script then runs the string.
            verdict = charsets.code(self.language, chars, "")
            if verdict:
                self.finding(
                    verdict._replace(rule="configfile-injection", why=f"{verdict.why} when it runs the string"),
                    text,
                    f"inside a {quote}...{quote} string that the {self.language} script evaluates as code",
                    raw_expr,
                )
                return
        if text.quoted == "json" or (text.quoted == "pyrepr" and self.language == "python"):
            # Escaped by json.dumps, or a Python list written into Python code.
            return
        if escaped and self.language in shell.CODE_LANGUAGES:
            # The earlier value escaped the closing quote of its string; the quote that opens this
            # value's string closes it instead, so this value is program text.
            verdict = charsets.code(self.language, chars, "")
            if verdict:
                why = f"{verdict.why}, once an earlier value on the line escapes the closing quote"
                self.finding(
                    verdict._replace(rule="configfile-injection", why=why),
                    text,
                    f"inside a {quote}...{quote} string of a {self.language} script, after a value that can end"
                    " in a backslash",
                    raw_expr,
                    needs_closer=quote,
                )
                return
        where = f"inside a {quote}...{quote} string" if quote else "outside any string"
        if self.language in shell.CODE_LANGUAGES:
            verdict = charsets.code(self.language, chars, quote)
            if verdict:
                verdict = verdict._replace(rule="configfile-injection")
                self.finding(verdict, text, f"{where} of a {self.language} script", raw_expr)
            return
        hit = chars & frozenset(quote + "\n")
        if hit:
            # Nothing runs a data file; what a changed line does depends on the program that reads it.
            why = "can end the string or add lines to the file"
            self.finding(
                Verdict("configfile-injection", charsets.LOW, hit, why), text, f"{where} of a data file", raw_expr
            )

    def server_sink(self, name: str, text: AV) -> None:
        """A user-controlled value passed to Python that runs a command or opens a file while rendering."""
        if not text.tainted:
            return
        executes = not name.startswith("open")
        verdict = Verdict(
            "server-injection",
            charsets.CRITICAL if executes else charsets.HIGH,
            text.chars,
            "decides what the Galaxy server process " + ("executes" if executes else "opens"),
            charsets.NONE,
        )
        self.finding(verdict, text, f"into `{name}(...)` in template Python", name)

    def finding(
        self, verdict: Verdict, text: AV, where: str, raw_expr: str | None, needs_closer: str | None = None
    ) -> None:
        """``needs_closer``: the quote of the value's string, when the finding holds only once another
        value has escaped the closing quote; until then only that quote or a backslash closes it."""
        refs = source_refs(text.sources)
        escaped = frozenset().union(*(self._escapes.get(ref, charsets.NONE) for ref in refs))
        breakout, requires, closes = _breakout(verdict, text, self.language, escaped, self.script)
        source = "; ".join(sorted(text.sources)[:3])
        expr = f" (`{raw_expr}`)" if raw_expr else ""
        severity = verdict.severity
        if all(CONDITIONAL in s for s in text.sources) and severity != charsets.LOW:
            severity = charsets.SEVERITIES[charsets.SEVERITIES.index(severity) - 1]
        self.report.add(
            Finding(
                rule=verdict.rule,
                kind=VULNERABILITY,
                severity=severity,
                message=(
                    f"{source} is written {where}{expr} and {verdict.why}."
                    f" Characters that get through: {charsets.show(verdict.chars)}"
                ),
                location=self.location,
                line=self._line,
                expr=raw_expr,
                source=source,
                context=where,
                chars=charsets.show(verdict.chars),
                refs=refs,
                breakout=breakout,
                requires=requires,
                closes=closes if needs_closer is None else text.chars & frozenset(needs_closer + "\\"),
                needs_closer=needs_closer is not None,
                unchecked=self._unchecked(refs, breakout | requires | closes),
            )
        )

    # -- helpers (#def) ------------------------------------------------------------------------

    def _helper_env(self, method: Method, args: list[AV], env: Env, keywords: dict[str, AV] | None = None) -> Env:
        helper_env = Env(shared=env.shared)
        for i, name in enumerate(method.args):
            if i < len(args):
                helper_env.local[name] = args[i]
            elif keywords and name in keywords:
                helper_env.local[name] = keywords[name]
            else:
                helper_env.local[name] = self.ev(method.defaults.get(name), env)
        return helper_env

    def _too_deep(self, method: Method | None, args: list[AV], keywords: dict[str, AV] | None) -> bool:
        if method is not None and self._depth < _MAX_DEPTH:
            return False
        if method is not None and any(a.tainted for a in [*args, *(keywords or {}).values()]):
            self.note(f"#def calls nest deeper than {_MAX_DEPTH}, a user-controlled value was not followed further")
        return True

    def inline(
        self, name: str, args: list[AV], states: States, env: Env, keywords: dict[str, AV] | None = None
    ) -> States:
        method = self.template.helpers.get(name)
        if method is None or self._too_deep(method, args, keywords):
            return states
        self._depth += 1
        try:
            return self.block(method.body, states, self._helper_env(method, args, env, keywords))
        finally:
            self._depth -= 1

    def call_helper(self, name: str, args: list[AV], env: Env, keywords: dict[str, AV] | None = None) -> AV:
        """The text a helper produces, when it is used as a value rather than written in place."""
        method = self.template.helpers.get(name)
        if method is None or self._too_deep(method, args, keywords):
            for value in [*args, *(keywords or {}).values()]:
                self._introduce(contents(value))
            return join(*(contents(a) for a in [*args, *(keywords or {}).values()]))
        self._depth += 1
        self._capture.append([])
        self._returns.append([])
        try:
            self.block(method.body, frozenset(), self._helper_env(method, args, env, keywords))
        finally:
            written = self._capture.pop()
            returned = self._returns.pop()
            self._depth -= 1
        if returned:
            # `#return value`: the helper is a function, what it wrote is discarded.
            return join(*returned)
        text = join(*written) if written else CLEAN
        return AV(chars=text.chars, sources=text.sources, whole=len(written) == 1 and written[0].whole)

    # -- expressions ---------------------------------------------------------------------------

    def _unnarrowed(self, node: ast.expr, env: Env) -> AV:
        path = _template_path(node)
        if isinstance(node, ast.Call) and path is not None:
            autocall = bool(_const(node.args[2])) if len(node.args) > 2 else False
            return self.resolve(path, env, autocall, exact=False)
        return self.ev(node, env)

    def resolve(self, path: str, env: Env, autocall: bool, exact: bool = True) -> AV:
        """The value of a dotted template name; ``exact=False`` ignores what tests showed about it."""
        parts = path.split(".")
        narrowed = env.local.get(NARROWED + path) if exact else None
        if narrowed is not None:
            return narrowed
        if any(key.startswith(RESTRICTED) for key in env.local):
            for i in range(len(parts), 0, -1):
                key = RESTRICTED + ".".join(parts[:i])
                if key in env.local:
                    value = env.local[key]
                    for part in parts[i:]:
                        value = self._autocall(value, env) if autocall else value
                        value = attribute(value, part)
                    return self._autocall(value, env) if autocall else value
        first = parts[0]
        if first in env.local:
            value = env.local[first]
        elif first in env.shared:
            value = env.shared[first]
        elif first in self.template.helpers:
            value = AV(helper=first)
        else:
            found = self.model.lookup(first)
            if found is not None:
                value = found
            elif first in self._imported or first in TEMPLATE_NAMES:
                value = AV(py=self._imported.get(first, first))
            else:
                value = self.model.job_parameter(first)
        for part in parts[1:]:
            value = self._autocall(value, env) if autocall else value
            value = attribute(value, part)
        return self._autocall(value, env) if autocall else value

    def _autocall(self, value: AV, env: Env) -> AV:
        # Cheetah calls a callable it meets while resolving a dotted name.
        if value.bound is not None:
            return self.call_bound(value.bound[0], value.bound[1], [], [], env)
        if value.helper:
            return value
        return value

    def _local_name(self, node: ast.AST, env: Env) -> str | None:
        if isinstance(node, ast.Name) and node.id in env.local:
            return node.id
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _NAME_MAPPER:
            path = _const(node.args[1]) if len(node.args) > 1 else None
            if isinstance(path, str) and "." not in path and path in env.local:
                return path
        return None

    def ev(self, node: ast.AST | None, env: Env) -> AV:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return AV(parts=(node.value,)) if node.value else CLEAN
        if node is None or isinstance(node, ast.Constant):
            return CLEAN
        if isinstance(node, ast.Name):
            if node.id in env.local:
                return env.local[node.id]
            if node.id in self.template.helpers:
                return AV(helper=node.id)
            return AV(py=self._imported.get(node.id, node.id))
        if isinstance(node, ast.Call):
            return self.ev_call(node, env)
        if isinstance(node, ast.Attribute):
            return attribute(self.ev(node.value, env), node.attr)
        if isinstance(node, ast.Subscript):
            base = self.ev(node.value, env)
            index = _const(node.slice)
            self.ev(node.slice, env)
            if base.items is not None and isinstance(index, int) and -len(base.items) <= index < len(base.items):
                return base.items[index]
            if base.nodes and isinstance(index, str):
                return attribute(base, index)
            if isinstance(node.slice, ast.Slice) and base.elem is None and base.items is None and not base.nodes:
                return base
            return element(base)
        if isinstance(node, ast.BinOp):
            left, right = self.ev(node.left, env), self.ev(node.right, env)
            if self._numeric(node, left, right):
                return CLEAN
            if isinstance(node.op, ast.Add):
                if left.items is not None and right.items is not None:
                    return AV(items=left.items + right.items)
                if left.elem is not None or right.elem is not None or left.items is not None or right.items is not None:
                    return AV(elem=join(element(left, strict=True), element(right, strict=True)))
                return concat([left, right])
            template = _const(node.left)
            if isinstance(node.op, ast.Mod) and isinstance(template, str):
                values = list(right.items) if right.items is not None else [right]
                if (formatted := _percent_format(template, values)) is not None:
                    return formatted
            mixed = join(stringify(left), stringify(right))
            self._introduce(stringify(left), stringify(right).chars | charsets.probe(str(_const(node.right) or "")))
            self._introduce(stringify(right), stringify(left).chars | charsets.probe(str(template or "")))
            return AV(chars=mixed.chars, sources=mixed.sources, whole=False)
        if isinstance(node, ast.JoinedStr):
            return concat([self.ev(v, env) for v in node.values])
        if isinstance(node, ast.FormattedValue):
            return stringify(self.ev(node.value, env))
        if isinstance(node, ast.IfExp):
            self.ev(node.test, env)
            self._speculative += 1
            try:
                return join(self.ev(node.body, env), self.ev(node.orelse, env))
            finally:
                self._speculative -= 1
        if isinstance(node, ast.BoolOp):
            first = self.ev(node.values[0], env)
            self._speculative += 1
            try:
                return join(first, *(self.ev(v, env) for v in node.values[1:]))
            finally:
                self._speculative -= 1
        if isinstance(node, ast.Compare):
            self.ev(node.left, env)
            self.ev(node.comparators[0], env)
            # `a < b < c` evaluates c only when a < b holds.
            self._speculative += 1
            try:
                for comparator in node.comparators[1:]:
                    self.ev(comparator, env)
            finally:
                self._speculative -= 1
            return CLEAN
        if isinstance(node, ast.UnaryOp):
            value = self.ev(node.operand, env)
            return CLEAN if isinstance(node.op, ast.Not) else value
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return AV(items=tuple(self.ev(elt, env) for elt in node.elts))
        if isinstance(node, ast.Dict):
            return AV(elem=join(*(self.ev(v, env) for v in list(node.values) + [k for k in node.keys if k])))
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            self._speculative += 1
            try:
                return self._comprehension(node, env)
            finally:
                self._speculative -= 1
        return self._ev_rest(node, env)

    def _comprehension(self, node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp, env: Env) -> AV:
        inner = env.copy()
        for generator in node.generators:
            self.bind(generator.target, element(self.ev(generator.iter, inner)), inner)
            for condition in generator.ifs:
                self.ev(condition, inner)
        if isinstance(node, ast.DictComp):
            return AV(elem=join(self.ev(node.key, inner), self.ev(node.value, inner)))
        return AV(elem=self.ev(node.elt, inner))

    def _ev_rest(self, node: ast.AST, env: Env) -> AV:
        if isinstance(node, ast.Starred):
            return self.ev(node.value, env)
        if isinstance(node, ast.Lambda):
            inner = env.copy()
            for arg in [*node.args.args, *node.args.kwonlyargs]:
                inner.local[arg.arg] = CLEAN
            return AV(bound=(contents(self.ev(node.body, inner)), "__lambda__"))
        if isinstance(node, ast.NamedExpr):
            value = self.ev(node.value, env)
            self.bind(node.target, value, env)
            return value
        if isinstance(node, ast.Slice):
            for part in (node.lower, node.upper, node.step):
                self.ev(part, env)
            return CLEAN
        return CLEAN

    @staticmethod
    def _numeric(node: ast.BinOp, left: AV, right: AV) -> bool:
        """Arithmetic: `x - 1`, `x / 2`, `x + 1` give a number whatever the user wrote, or fail."""
        if any(v.elem is not None or v.items is not None or v.nodes for v in (left, right)):
            # Set difference and list concatenation keep the elements; a parameter wrapper or a
            # pathlib.Path may define the operator for strings.
            return False
        number = (int, float)
        with_number = type(_const(node.left)) in number or type(_const(node.right)) in number
        return with_number and isinstance(node.op, (ast.Add, ast.Sub, ast.Div, ast.FloorDiv, ast.Pow))

    def ev_call(self, node: ast.Call, env: Env) -> AV:
        func = node.func
        if isinstance(func, ast.Name) and func.id in _NAME_MAPPER and len(node.args) >= 2:
            path = _const(node.args[1])
            autocall = bool(_const(node.args[2])) if len(node.args) > 2 else False
            if isinstance(path, str):
                if func.id == "VFN":
                    # `$x.method()`: an attribute of x, which a test of `$x` itself says nothing about.
                    value = self._unnarrowed(node.args[0], env)
                    for part in path.split("."):
                        value = attribute(value, part)
                        if autocall:
                            value = self._autocall(value, env)
                    return value
                return self.resolve(path, env, autocall)
        callee = self.ev(func, env)
        args = [self.ev(arg, env) for arg in node.args]
        keywords = [self.ev(keyword.value, env) for keyword in node.keywords]
        named = {k.arg: v for k, v in zip(node.keywords, keywords) if k.arg}
        if callee.bound is not None:
            receiver, name = callee.bound
            if name in _MUTATORS:
                target = func.args[0] if isinstance(func, ast.Call) and func.args else getattr(func, "value", None)
                if local := self._local_name(target, env) if target is not None else None:
                    grown = join(*(a if name in ("extend", "update") else AV(elem=a) for a in args))
                    env.assign(local, AV(elem=element(grown, strict=True)), weak=True)
            return self.call_bound(receiver, name, args, node.args, env, keywords, node)
        if callee.helper:
            return self.call_helper(callee.helper, args, env, named)
        if callee.py:
            return self.call_python(callee.py, args, keywords, node, env)
        for value in args + keywords:
            # A function the analysis does not know can turn the value into anything.
            self._introduce(contents(value))
        if callee.nodes:
            # Calling an attribute of an opaque object: the result is as trustworthy as the object.
            return join(stringify(callee), *(contents(a) for a in args))
        return join(*(contents(a) for a in args + keywords))

    def call_python(self, name: str, args: list[AV], keywords: list[AV], node: ast.Call, env: Env) -> AV:
        first = args[0] if args else CLEAN
        if _SERVER_SINK.match(name):
            self.server_sink(name, join(*(stringify(a) for a in args + keywords)))
        if name == "open":
            if self._galaxy_file(node):
                return CLEAN
            datasets = self._opened_datasets(node, env)
            return dataset_content(datasets) if datasets else file_content()
        if name in ("int", "float") and len(node.args) == 1 and not node.keywords and not self._speculative:
            # Rendering stops when the conversion fails: afterwards the value is a number.
            self.apply_narrowing(node.args[0], lambda v, n=name: _number(v, n), env)
        if name in _CLEAN_FUNCTIONS:
            return CLEAN
        if name in _STRING_FUNCTIONS:
            if name == "repr":
                # repr() puts the string between quotes and escapes backslashes and that quote.
                introduced(stringify(first), frozenset("'\"\\"), escape=True)
            elif name == "format" and len(node.args) > 1:
                spec = _const(node.args[1])
                self._introduce(stringify(first), charsets.probe(spec) if isinstance(spec, str) else charsets.PROBE)
            return stringify(first)
        if name in _CONTAINER_FUNCTIONS:
            return first if (first.items is not None or first.elem is not None) else AV(elem=element(first))
        if name == "enumerate":
            return AV(elem=AV(items=(CLEAN, element(first))))
        if name == "zip":
            return AV(elem=AV(items=tuple(element(a) for a in args)))
        if name == "map" and len(args) >= 2:
            mapped = element(args[1])
            function = node.args[0]
            if isinstance(function, ast.Name) and function.id in _STRING_FUNCTIONS:
                mapped = stringify(mapped)
            return AV(elem=mapped)
        if name == "filter" and len(args) >= 2:
            return AV(elem=element(args[1]))
        if name == "dict":
            return AV(elem=join(*(element(a, strict=True) for a in args), *keywords))
        if name == "getVar":
            variable = _const(node.args[0]) if node.args else None
            default = args[1] if len(args) > 1 else CLEAN
            if isinstance(variable, str):
                known = self.model.lookup(variable.split(".")[0]) or env.local.get(variable.split(".")[0])
                if known is not None:
                    return join(self.resolve(variable, env, True), default)
            return default
        if _DECODERS.match(name):
            text = contents(first)
            self._introduce(text)
            return AV(chars=charsets.PROBE, sources=text.sources, whole=False) if text.tainted else CLEAN
        if name in ("re.sub", "re.subn") and len(args) >= 3:
            # With a count, or a replacement that is not plain text, some matches are left in place.
            every_match = len(node.args) == 3 and not node.keywords
            return self._substitute(_const(node.args[0]), args[1], node.args[1], stringify(args[2]), every_match)
        if name == "re.escape":
            text = stringify(first)
            self._introduce(text, frozenset("\\"))
            return AV(chars=text.chars | ({"\\"} if text.tainted else set()), sources=text.sources)
        if name in ("re.findall", "re.split", "re.finditer") and len(args) >= 2:
            return AV(elem=stringify(args[1]))
        if name in ("re.match", "re.search", "re.fullmatch") and len(args) >= 2:
            text = stringify(args[1])
            return AV(chars=text.chars, sources=text.sources, elem=text)
        if name in ("shlex.quote", "pipes.quote", "shlex.join"):
            text = stringify(first)
            introduced(text, _ESCAPING_ADDS["shlex"], escape=True)
            return AV(chars=text.chars, sources=text.sources, quoted="shlex")
        if name == "json.dumps":
            container = first.elem is not None or first.items is not None
            text = contents(first) if container and not first.nodes else stringify(first)
            extra = (_JSON_PUNCTUATION if container else frozenset('"\\')) if text.tainted else frozenset()
            introduced(text, extra, escape=True)
            return AV(chars=text.chars | extra, sources=text.sources, quoted="json")
        if _ENCODERS.match(name):
            # The encoded text is made of letters, digits and the few symbols of the encoding.
            text = contents(first)
            alphabet = frozenset("+/=-_\n") if "encodebytes" in name else frozenset("+/=-_")
            self._introduce(text, alphabet)
            return AV(chars=alphabet, sources=text.sources, whole=False) if text.tainted else CLEAN
        if name == "os.path.basename":
            text = stringify(first)
            return AV(chars=text.chars - {"/"}, sources=text.sources)
        if name in ("os.path.dirname", "os.path.normpath"):
            # Parts of the path, and the separators between them.
            text = stringify(first)
            return AV(chars=text.chars | ({"/"} if text.tainted else set()), sources=text.sources)
        if name == "os.path.join" and args and not keywords:
            parts = [stringify(a) for a in args]
            if not any(_literal_chars(part) & QUOTE_CLOSERS for part in parts):
                # The parts in order, with a separator between them. An absolute part drops the
                # parts before it, which only takes text away.
                joined: list[str | AV] = []
                for i, part in enumerate(parts):
                    joined.extend(("/", part) if i else (part,))
                return concat(joined)
        if name == "os.path.splitext":
            text = stringify(first)
            return AV(items=(text, text))
        for value in args + keywords:
            self._introduce(contents(value))
        return join(*(contents(a) for a in args + keywords))

    def _opened_datasets(self, node: ast.Call, env: Env) -> tuple[Data, ...]:
        """The input datasets ``open()`` reads: `open($x)`, `open(str($x))`, `open($x.__str__)`, `open($x.file_name)`."""
        if len(node.args) != 1 or node.keywords:
            return ()
        argument = node.args[0]
        if (
            isinstance(argument, ast.Call)
            and isinstance(argument.func, ast.Name)
            and argument.func.id in ("str", "unicode")
            and len(argument.args) == 1
        ):
            argument = argument.args[0]
        if isinstance(argument, ast.Call) and not argument.args and not argument.keywords:
            # `$x.get_file_name()`: the call of a name the template looks up.
            argument = argument.func
        path = self._looked_up_path(argument)
        if path is None:
            return ()
        parts = path.split(".")
        while len(parts) > 1 and parts[-1] in ("__str__", "file_name", "get_file_name"):
            parts.pop()
        value = self.resolve(".".join(parts), env, False)
        datasets = tuple(n for n in value.nodes if isinstance(n, Data) and not n.output)
        if not datasets or len(datasets) != len(value.nodes) or value.tainted:
            return ()
        return datasets

    @staticmethod
    def _looked_up_path(node: ast.expr) -> str | None:
        """The dotted name a Cheetah lookup reads: `VFFSL(SL, "a.b")`, `VFN(VFFSL(SL, "a"), "b")`."""
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and len(node.args) > 1):
            return None
        name = _const(node.args[1])
        if not isinstance(name, str):
            return None
        if node.func.id in ("VFFSL", "VFSL"):
            return name
        if node.func.id == "VFN":
            inner = TemplateAnalysis._looked_up_path(node.args[0])
            return f"{inner}.{name}" if inner is not None else None
        return None

    @staticmethod
    def _galaxy_file(node: ast.Call) -> bool:
        """``open()`` of a file that is not a dataset: a constant path, or one under a directory of Galaxy."""
        if not node.args or isinstance(node.args[0], ast.Constant):
            return True
        for inner in ast.walk(node.args[0]):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id in _NAME_MAPPER:
                path = _const(inner.args[1]) if len(inner.args) > 1 else None
                if isinstance(path, str) and path.split(".")[0] in SAFE_SPECIALS:
                    return True
        return False

    def _substitute(
        self, pattern: object, replacement: AV, replacement_node: ast.AST, text: AV, every_match: bool
    ) -> AV:
        replaced = stringify(replacement)
        literal = _const(replacement_node)
        plain = isinstance(literal, str) and "\\" not in literal
        added = replaced.chars | (charsets.probe(literal) if isinstance(literal, str) and text.tainted else set())
        self._introduce(text, frozenset(added) if isinstance(literal, str) and plain else charsets.PROBE)
        removed = charsets.regex_removed(pattern) if isinstance(pattern, str) and plain and every_match else None
        if removed is None or not isinstance(literal, str):
            return AV(chars=text.chars | added, sources=text.sources | replaced.sources)
        kept = text.chars - removed.everywhere
        before = (text.chars if text.lead is None else text.lead) - removed.everywhere
        lead: charsets.Chars | None = None
        if literal:
            # A replaced character at the start leaves the replacement there.
            lead = (before - removed.start) | charsets.probe(literal[0])
        elif removed.start_repeats and not removed.everywhere:
            # `^-+` deleted: the value now starts with whatever followed the dashes.
            lead = kept - removed.start
        return AV(chars=kept | added, sources=text.sources | replaced.sources, lead=lead)

    def call_bound(
        self,
        receiver: AV,
        name: str,
        args: list[AV],
        arg_nodes: list[ast.expr],
        env: Env,
        keywords: list[AV] | None = None,
        node: ast.Call | None = None,
    ) -> AV:
        keywords = keywords or []
        if name == "__value__":
            return receiver
        if name == "__lambda__":
            return join(receiver, *(contents(a) for a in args + keywords))
        if name == "__getattr__":
            attribute_name = _const(arg_nodes[0]) if arg_nodes else None
            if isinstance(attribute_name, str):
                return self._autocall(attribute(receiver, attribute_name), env)
        if name == "__preference__":
            # $__user__.extra_preferences.get('name', default)
            preference = _const(arg_nodes[0]) if arg_nodes else None
            found = user_preference(preference) if isinstance(preference, str) else stringify(receiver)
            return join(found, *(contents(a) for a in args[1:] + keywords))
        if name in _CLEAN_METHODS:
            return CLEAN
        if receiver.helper:
            return self.call_helper(receiver.helper, args, env)
        if name in ("group", "groups", "groupdict") and receiver.elem is not None:
            # A match object of re.match(pattern, value): its groups are pieces of the value.
            return receiver.elem
        if receiver.elem is not None or receiver.items is not None:
            if name in _NONE_METHODS:
                # list.reverse(), list.sort()...: they change the list in place and return None.
                return CLEAN
            if name in ("pop", "get", "copy", "setdefault"):
                return receiver if name == "copy" else element(receiver)
            if name in ("keys", "values", "items"):
                item = element(receiver)
                return AV(elem=AV(items=(item, item)) if name == "items" else item)
            if name in _MUTATORS:
                return CLEAN
            return receiver
        text = raw(receiver) if receiver.nodes else stringify(receiver)
        first_literal = _const(arg_nodes[0]) if arg_nodes else None
        if name in ("split", "rsplit", "splitlines", "partition", "rpartition"):
            if name == "splitlines":
                removed = {"\n"}
            elif not arg_nodes:
                removed = set(" \t\n")
            elif isinstance(first_literal, str) and len(first_literal) == 1:
                removed = {first_literal}
            else:
                removed = set()
            return AV(elem=AV(chars=text.chars - removed, sources=text.sources))
        if name == "replace" and len(args) >= 2:
            # str.replace(old, new, count) leaves the occurrences after the first `count`.
            every = len(args) == 2 and not keywords
            removed = {first_literal} if every and isinstance(first_literal, str) and len(first_literal) == 1 else set()
            second = _const(arg_nodes[1]) if len(arg_nodes) > 1 else None
            replacement = stringify(args[1])
            # What the template writes in: its literal text, and values no user controls. A user value
            # brings its own characters under its own source, which the job check reads too.
            written = _literal_chars(replacement) | (
                charsets.probe(second) if isinstance(second, str) else charsets.NONE
            )
            if not replacement.tainted:
                written = written | replacement.chars
            if text.tainted or replacement.tainted:
                introduced = frozenset(written) - _matched_chars(first_literal)
                self._introduce(text, introduced)
                self._introduce(replacement, introduced)
            else:
                written = charsets.NONE
            escaped = every and first_literal == '"' and second == '\\"' and "\\" not in text.chars
            kept = self._kept_escaping(text, name, arg_nodes, keywords) if not replacement.tainted else ""
            return AV(
                chars=(text.chars - removed) | replacement.chars | written,
                sources=text.sources | replacement.sources,
                quoted="dq-escaped" if escaped else kept,
            )
        if name == "lstrip" and isinstance(first_literal, str) and len(args) == 1:
            return AV(chars=text.chars, sources=text.sources, lead=text.chars - charsets.probe(first_literal))
        if name == "join" and args:
            item = stringify(element(args[0]))
            # Literal elements joined with a user value (`''.join(["'", x])`) put their text next to it,
            # in an order the element no longer shows.
            self._introduce(item, _literal_chars(args[0]) - _kept_literal_chars(item, receiver))
            if receiver.parts is not None or not receiver.tainted:
                # Two elements show the separator between values once.
                return concat([item, receiver, item])
            return join(text, item)
        if name in ("format", "format_map"):
            template = receiver.parts[0] if receiver.parts and len(receiver.parts) == 1 else None
            if isinstance(template, str) and not keywords and (formatted := _brace_format(template, args)) is not None:
                return formatted
            mixed = join(text, *(stringify(a) for a in args + keywords))
            for value in args + keywords:
                self._introduce(stringify(value), text.chars | charsets.probe(str(template or "")))
            return AV(chars=mixed.chars, sources=mixed.sources, whole=False)
        passed = join(*(contents(a) for a in args + keywords))
        if passed.tainted:
            # An unmodelled method given a user value (string.Template(...).substitute(x=value)).
            self._introduce(text)
            self._introduce(passed)
            return AV(chars=text.chars | passed.chars, sources=text.sources | passed.sources, whole=False)
        if name in ("encode", "decode") and not keywords and len(arg_nodes) <= 1:
            codec = _const(arg_nodes[0]) if arg_nodes else "utf-8"
            if isinstance(codec, str) and codec.lower().replace("_", "-") in ("utf-8", "utf8", "ascii"):
                # The bytes of the text in UTF-8, or the text of such bytes: the same characters.
                return AV(chars=text.chars, sources=text.sources, whole=text.whole, quoted=text.quoted)
        # strip, lower, encode... keep whatever the value could contain.
        if name not in _PRESERVING_METHODS:
            self._introduce(text)
        else:
            literals = [_const(node) for node in arg_nodes]
            self._introduce(text, charsets.probe("".join(lit for lit in literals if isinstance(lit, str))))
        return AV(
            chars=text.chars,
            sources=text.sources,
            whole=text.whole and text.parts is None,
            quoted=self._kept_escaping(text, name, arg_nodes, keywords),
        )

    @staticmethod
    def _kept_escaping(text: AV, name: str, arg_nodes: list[ast.expr], keywords: list[AV]) -> str:
        """The escaping a str method leaves in place: none of its arguments can add or take away a quote."""
        if not text.quoted or name not in _ESCAPE_KEEPING_METHODS or keywords:
            return ""
        if text.quoted not in ("sq-escaped", "dq-escaped"):
            # shlex, JSON and repr escaping depend on characters a replacement can add or remove
            # (shlex leaves `,` unquoted; JSON writes a newline as \n).
            return text.quoted if name in _CASE_METHODS or (name == "strip" and not arg_nodes) else ""
        literals = [_const(node) for node in arg_nodes]
        if all(isinstance(literal, str) and not _QUOTING.intersection(literal) for literal in literals):
            return text.quoted
        return ""


def unresolved_names(template: CompiledTemplate, model: Model) -> set[str]:
    """Names of the template's own machinery that it reads, which the analysis does not follow."""
    assigned: set[str] = set(template.helpers)
    for imported in template.imports:
        if isinstance(imported, (ast.Import, ast.ImportFrom)):
            assigned.update((alias.asname or alias.name).split(".")[0] for alias in imported.names)
    read: set[str] = set()
    methods = [template.main, *template.helpers.values()]
    for method in methods:
        assigned.update(method.args)
        for stmt in method.body:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    assigned.add(node.id)
                elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
                    key = _const(node.slice)
                    if isinstance(key, str):
                        assigned.add(key)
                elif (
                    isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("VFFSL", "VFSL")
                ):
                    path = _const(node.args[1]) if len(node.args) > 1 else None
                    if isinstance(path, str):
                        read.add(path.split(".")[0])
    return {
        name
        for name in read
        if name not in assigned and model.lookup(name) is None and name not in PY_NAMES and name in TEMPLATE_NAMES
    }


PY_NAMES = frozenset(
    (
        "str int float len bool list tuple set dict sorted reversed enumerate zip map filter range min max sum any"
        " all abs round repr format isinstance hasattr getattr type chr ord open print iter next True False None"
        " re os sys json math shlex time string itertools collections getVar varExists hasVar self unicode"
        " basestring"
    ).split()
) | frozenset(name for name in _CLEAN_FUNCTIONS | _STRING_FUNCTIONS | _CONTAINER_FUNCTIONS if "." not in name)

# Names a template resolves without the job: Python's builtins, the globals of the module Cheetah
# compiles a template into, the attributes of the template object and the locals of its method.
TEMPLATE_NAMES = (
    PY_NAMES
    | frozenset(dir(builtins))
    | frozenset(dir(Template))
    | frozenset(
        (
            "CacheRegion DummyResponse DummyResponseFailure DummyTransaction ErrorCatchers Filters NotFound Template"
            " TransformerResponse TransformerTransaction VFFSL VFN VFSL builtin currentTime exists getmtime logging"
            " os sys time types unicode valueForName valueFromFrameOrSearchList valueFromSearchList templateAPIClass"
            " SL trans write _filter _v _dummyTrans"
        ).split()
    )
)
