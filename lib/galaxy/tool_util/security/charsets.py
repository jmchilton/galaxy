"""Which characters of a user-controlled value can survive, and what they can do where.

The analysis tracks, for every value, the set of "probe" characters (punctuation and
whitespace) that may still be present when the value is written into a command or a
configfile. Letters and digits are never tracked: they cannot change how a shell or an
interpreter parses its input.

Sanitizers are not re-modelled here. :func:`sanitized` runs the real
:class:`~galaxy.tool_util.parser.sanitize.ToolParameterSanitizer` (or Galaxy's default
``sanitize_param``) on each probe character and records what comes out.
"""

import string
from typing import (
    Any,
    NamedTuple,
)

from galaxy.tool_util.parser.sanitize import ToolParameterSanitizer
from galaxy.util import sanitize_param

try:
    import re._constants as sre_constants  # type: ignore[import-not-found, unused-ignore]
    import re._parser as sre_parse  # type: ignore[import-not-found, unused-ignore]
except ImportError:  # Python < 3.11
    import sre_constants  # type: ignore[no-redef, unused-ignore]
    import sre_parse  # type: ignore[no-redef, unused-ignore]

Chars = frozenset[str]

PROBE: Chars = frozenset(string.punctuation + " \t\n")
NONE: Chars = frozenset()

# Start a new command, a substitution or a redirection in an unquoted shell word.
SHELL_EXEC: Chars = frozenset(";&|$`<>")
_WHITESPACE: Chars = frozenset(" \t\n")
# Split or rewrite an unquoted word: extra arguments, globs, quotes, comments.
SHELL_SPLIT: Chars = frozenset(" \t\n*?[]{}()~#!'\"\\")

CRITICAL = "critical"
HIGH = "high"
MEDIUM = "medium"
LOW = "low"
INFO = "info"
SEVERITIES = (INFO, LOW, MEDIUM, HIGH, CRITICAL)


def worst(a: str, b: str) -> str:
    return a if SEVERITIES.index(a) >= SEVERITIES.index(b) else b


def probe(text: str) -> Chars:
    return PROBE.intersection(text)


def sanitized(chars: Chars, sanitizer: ToolParameterSanitizer | None = None) -> Chars:
    """Probe characters left after Galaxy sanitizes a value that may contain ``chars``."""
    out: set[str] = set()
    for c in chars:
        text = sanitizer.sanitize_param(c) if sanitizer is not None else sanitize_param(c)
        out.update(probe(text))
    return frozenset(out)


DEFAULT_SANITIZED: Chars = sanitized(PROBE)


def show(chars: Chars) -> str:
    names = {" ": "space", "\t": "tab", "\n": "newline"}
    return " ".join(names.get(c, c) for c in sorted(chars))


class Verdict(NamedTuple):
    rule: str
    severity: str
    chars: Chars
    why: str


def unquoted(chars: Chars) -> Verdict | None:
    if hit := chars & SHELL_EXEC:
        return Verdict("shell-injection", HIGH, hit, "can start another command")
    if hit := chars & SHELL_SPLIT:
        if hit <= _WHITESPACE and not chars & frozenset("-/"):
            # A list of plain words: none of them can be an option or name a file elsewhere.
            return Verdict("argument-injection", LOW, hit, "can split the word into extra plain words")
        return Verdict("argument-injection", MEDIUM, hit, "can split the word into extra arguments or globs")
    return None


def single_quoted(chars: Chars) -> Verdict | None:
    if "'" not in chars:
        return None
    after = unquoted(chars)
    if after and after.rule == "shell-injection":
        return Verdict("shell-injection", HIGH, after.chars | {"'"}, "can close the single quotes and start a command")
    return Verdict("argument-injection", MEDIUM, frozenset("'"), "can close the single quotes")


def double_quoted(chars: Chars) -> Verdict | None:
    if "`" in chars or ("$" in chars and "(" in chars):
        hit = chars & frozenset("`$(")
        return Verdict("shell-injection", HIGH, hit, "can run a command substitution inside the double quotes")
    if '"' in chars:
        after = unquoted(chars)
        if after and after.rule == "shell-injection":
            return Verdict(
                "shell-injection", HIGH, after.chars | {'"'}, "can close the double quotes and start a command"
            )
        return Verdict("argument-injection", MEDIUM, frozenset('"'), "can close the double quotes")
    if "$" in chars:
        return Verdict(
            "argument-injection", MEDIUM, frozenset("$"), "can expand shell variables inside the double quotes"
        )
    if "\\" in chars:
        return Verdict("argument-injection", LOW, frozenset("\\"), "can escape the closing double quote")
    return None


# Characters that let a value leave a string or an expression of a nested program.
_CODE_BREAK: dict[str, tuple[Chars, Chars]] = {
    # language: (high, medium)
    "sh": (SHELL_EXEC | frozenset("'\"\\"), SHELL_SPLIT),
    "awk": (frozenset("'\";|`$"), frozenset("(){}/ \t\n")),
    "sed": (frozenset("'\";`\n"), frozenset("/")),
}
_CODE_DEFAULT: tuple[Chars, Chars] = (frozenset("'\"`;()"), PROBE - frozenset("_-.,:=+@%/^"))


def code(lang: str, chars: Chars, quote: str = "") -> Verdict | None:
    """Value written into a program text that another interpreter parses (``sh -c``, ``awk``, a script)."""
    high, medium = _CODE_BREAK.get(lang, _CODE_DEFAULT)
    if quote and lang != "sh":
        # Inside a string literal of the nested program only its delimiter and the escape character matter.
        if quote in chars:
            return Verdict("nested-interpreter", HIGH, frozenset(quote), f"can end the string and inject {lang} code")
        if "\\" in chars:
            # A syntax error by itself; code only when a second user-controlled string follows on the line.
            return Verdict("nested-interpreter", LOW, frozenset("\\"), "can escape the closing quote of the string")
        return None
    if hit := chars & high:
        return Verdict("nested-interpreter", HIGH, hit, f"can inject {lang} code")
    if hit := chars & medium:
        return Verdict("nested-interpreter", MEDIUM, hit, f"can change the {lang} program")
    return None


def _category(cat: Any) -> Chars:
    name = str(cat)
    if name.endswith("NOT_DIGIT"):
        return PROBE
    if name.endswith("NOT_WORD"):
        return PROBE - {"_"}
    if name.endswith("NOT_SPACE"):
        return PROBE - frozenset(" \t\n")
    if name.endswith("DIGIT"):
        return NONE
    if name.endswith("WORD"):
        return frozenset("_")
    if name.endswith("SPACE"):
        return frozenset(" \t\n")
    return PROBE


def _in_set(items: Any) -> Chars:
    negate = False
    chars: set[str] = set()
    for op, arg in items:
        if op is sre_constants.NEGATE:
            negate = True
        elif op is sre_constants.LITERAL:
            chars.add(chr(arg))
        elif op is sre_constants.RANGE:
            lo, hi = arg
            chars.update(c for c in PROBE if lo <= ord(c) <= hi)
        elif op is sre_constants.CATEGORY:
            chars.update(_category(arg))
        else:
            return PROBE
    found = PROBE.intersection(chars)
    return PROBE - found if negate else found


def _one(op: Any, arg: Any) -> Chars | None:
    """Probe characters a single-character regex item matches, None if it is not one."""
    if op is sre_constants.LITERAL:
        return probe(chr(arg))
    if op is sre_constants.NOT_LITERAL:
        return PROBE - {chr(arg)}
    if op is sre_constants.ANY:
        return PROBE - {"\n"}
    if op is sre_constants.IN:
        return _in_set(arg)
    if op is sre_constants.CATEGORY:
        return _category(arg)
    return None


_REPEATS = tuple(
    getattr(sre_constants, name)
    for name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT")
    if hasattr(sre_constants, name)
)


def _consumed(items: Any) -> Chars:
    chars: set[str] = set()
    for op, arg in items:
        one = _one(op, arg)
        if one is not None:
            chars.update(one)
        elif op is sre_constants.BRANCH:
            for alternative in arg[1]:
                chars.update(_consumed(alternative))
        elif op is sre_constants.SUBPATTERN:
            chars.update(_consumed(arg[-1]))
        elif op in _REPEATS:
            chars.update(_consumed(arg[2]))
        elif op in (sre_constants.AT, sre_constants.ASSERT, sre_constants.ASSERT_NOT, sre_constants.GROUPREF):
            continue
        else:
            return PROBE
    return frozenset(chars)


def _end_anchored(items: Any) -> bool:
    items = list(items)
    if not items:
        return False
    op, arg = items[-1]
    if op is sre_constants.AT:
        return arg in (sre_constants.AT_END, sre_constants.AT_END_STRING)
    if op is sre_constants.BRANCH:
        return all(_end_anchored(alternative) for alternative in arg[1])
    if op is sre_constants.SUBPATTERN:
        return _end_anchored(arg[-1])
    return False


def regex_universe(expression: str) -> Chars:
    """Probe characters a value accepted by a Galaxy ``regex`` validator may contain.

    Galaxy applies the expression with ``re.match``: anchored at the start only. Without a
    final ``$`` the tail of the value is unconstrained, so every character is possible.
    """
    try:
        parsed = sre_parse.parse(expression)
    except Exception:
        return PROBE
    if not _end_anchored(parsed):
        return PROBE
    return _consumed(parsed)


def _first(items: Any) -> tuple[Chars, bool, Chars]:
    """Probe characters a match can begin with, whether it can be empty, and what a lookahead excludes."""
    chars: set[str] = set()
    excluded: set[str] = set()
    for op, arg in items:
        if op is sre_constants.AT or op is sre_constants.ASSERT:
            continue
        if op is sre_constants.ASSERT_NOT:
            direction, pattern = arg
            pattern = list(pattern)
            one = _one(*pattern[0]) if direction == 1 and len(pattern) == 1 else None
            if one is not None:
                excluded.update(one)
            continue
        one = _one(op, arg)
        if one is not None:
            return frozenset(chars | (one - excluded)), False, frozenset(excluded)
        if op is sre_constants.BRANCH:
            firsts = [_first(alternative) for alternative in arg[1]]
            chars.update(*(first - excluded for first, _, _ in firsts))
            nullable = any(empty for _, empty, _ in firsts)
        elif op is sre_constants.SUBPATTERN:
            first, nullable, _ = _first(arg[-1])
            chars.update(first - excluded)
        elif op in _REPEATS:
            first, nullable, _ = _first(arg[2])
            chars.update(first - excluded)
            nullable = nullable or arg[0] < 1
        else:
            return PROBE, True, NONE
        if not nullable:
            return frozenset(chars), False, frozenset(excluded)
    return frozenset(chars), True, frozenset(excluded)


def regex_first(expression: str) -> Chars:
    """Probe characters a value accepted by a Galaxy ``regex`` validator may begin with.

    ``re.match`` anchors the expression at the start, so this holds without a final ``$``.
    """
    try:
        parsed = sre_parse.parse(expression)
    except Exception:
        return PROBE
    first, nullable, excluded = _first(parsed)
    if nullable and not _end_anchored(parsed):
        # The expression matches the empty string at the start of any value.
        return PROBE - excluded
    return first


class Removed(NamedTuple):
    """What ``re.sub(pattern, text, value)`` replaces: characters anywhere, and characters at the start."""

    everywhere: Chars
    start: Chars
    start_repeats: bool  # the pattern at the start takes every leading occurrence (``^-+``)


def regex_removed(pattern: str) -> Removed | None:
    """The characters a cleaning pattern replaces, None for a pattern that is not one.

    A cleaning pattern matches one character of a class at a time, anywhere
    (``[^\\w.-]``) or at the start of the value (``^-``), or is an alternation of such
    patterns (``^-|[^\\w.-]``).
    """
    try:
        parsed = list(sre_parse.parse(pattern))
    except Exception:
        return None
    alternatives = [parsed]
    if len(parsed) == 1 and parsed[0][0] is sre_constants.BRANCH:
        alternatives = [list(alternative) for alternative in parsed[0][1][1]]
    everywhere: set[str] = set()
    start: set[str] = set()
    start_repeats = True
    for items in alternatives:
        anchored = bool(items) and items[0][0] is sre_constants.AT and "BEGINNING" in str(items[0][1])
        if anchored:
            items = items[1:]
        if len(items) != 1:
            return None
        op, arg = items[0]
        repeats = False
        if op in _REPEATS:
            low, high, inner = arg
            inner = list(inner)
            if low < 1 or len(inner) != 1:
                return None
            repeats = high is sre_constants.MAXREPEAT
            op, arg = inner[0]
        one = _one(op, arg)
        if one is None:
            return None
        if anchored:
            start.update(one)
            start_repeats = start_repeats and repeats
        else:
            everywhere.update(one)
    return Removed(frozenset(everywhere), frozenset(start), start_repeats and bool(start))
