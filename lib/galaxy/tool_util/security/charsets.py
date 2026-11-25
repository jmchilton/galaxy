"""Which characters of a user-controlled value can survive, and what they can do where.

The analysis tracks, for every value, the set of "probe" characters (punctuation and
whitespace) that may still be present when the value is written into a command or a
configfile. Letters and digits are never tracked: they cannot change how a shell or an
interpreter parses its input.

Sanitizers are not re-modelled here. :func:`sanitized` runs the real
:class:`~galaxy.tool_util.parser.sanitize.ToolParameterSanitizer` (or Galaxy's default
``sanitize_param``) on each probe character and records what comes out.
"""

from __future__ import annotations

import re
import string
from typing import (
    Any,
    FrozenSet,
    NamedTuple,
    Optional,
)

from galaxy.tool_util.parser.sanitize import ToolParameterSanitizer
from galaxy.util import (
    mapped_chars,
    sanitize_param,
)

try:
    import re._constants as sre_constants  # type: ignore[import-not-found, unused-ignore]
    import re._parser as sre_parse  # type: ignore[import-not-found, unused-ignore]
except ImportError:  # Python < 3.11
    import sre_constants  # type: ignore[no-redef, unused-ignore]
    import sre_parse  # type: ignore[no-redef, unused-ignore]

Chars = FrozenSet[str]

PROBE: Chars = frozenset(string.punctuation + " \t\n")
NONE: Chars = frozenset()

# Start a new command, a substitution or a redirection in an unquoted shell word.
SHELL_EXEC: Chars = frozenset(";&|$`<>")
# And a newline, in a shell script.
SCRIPT_EXEC: Chars = SHELL_EXEC | {"\n"}
WHITESPACE: Chars = frozenset(" \t\n")
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


# What a value that leaves its place can do, which decides the level of tool_security_review that
# refuses it: become code, stop being the data it is meant to be, or split into more words.
CODE = "code"
DATA = "data"
ALL = "all"
LEVELS = (CODE, DATA, ALL)
_SEVERITY_LEVELS = {CRITICAL: CODE, HIGH: CODE, MEDIUM: DATA, LOW: ALL}


def level_of(severity: str) -> str | None:
    """The level of a finding of this severity, unless its verdict says otherwise."""
    return _SEVERITY_LEVELS.get(severity)


def enforced(level: str | None, at: str) -> bool:
    """Whether a finding of ``level`` is refused at the enforcement level ``at``."""
    return level is not None and LEVELS.index(level) <= LEVELS.index(at)


def stricter(a: str | None, b: str | None) -> str | None:
    if a is None or b is None:
        return a or b
    return a if LEVELS.index(a) <= LEVELS.index(b) else b


# Marks the job check adds to the characters of a value for what no single character tells: a word
# of it can be read as an option or expands to a home directory. A quote before the dash is removed
# by the shell (`'$x'` with `a' '-rf`).
LEADING_DASH = "a leading -"
DASH_WORD = "a word starting with -"
TILDE_WORD = "a word starting with ~"
_LEADING_DASH = re.compile(r"""^['"]*-""")
_DASH_WORD = re.compile(r"""(?:^|\s)['"]*-""")
_TILDE_WORD = re.compile(r"(?:^|\s)~")
# Where a value splits into words or closes its quotes, what it must also hold to stop being data:
# a word that is an option or a home directory, a path, a glob or a brace expansion.
DATA_HARM: Chars = frozenset((DASH_WORD, TILDE_WORD, "/", "*", "?", "[", "{"))


def marks(value: str) -> frozenset[str]:
    """The marks of a value (see LEADING_DASH)."""
    found = set()
    if _LEADING_DASH.search(value):
        found.add(LEADING_DASH)
    if _DASH_WORD.search(value):
        found.add(DASH_WORD)
    if _TILDE_WORD.search(value):
        found.add(TILDE_WORD)
    return frozenset(found)


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
    # Characters at least one of which a value must contain to do what `why` says; None when that
    # is any of `chars`, empty when no character decides it.
    breakout: Optional[Chars] = None
    # When not empty, the value must also contain one of these: closing single quotes starts a
    # command only with a command character after the quote.
    requires: Chars = frozenset()
    # The level that refuses the finding, when it is not the one of its severity (level_of).
    level: Optional[str] = None
    # At the data level, the value must also contain one of these (DATA_HARM): splitting into
    # plain words is refused only at the level of all.
    data_requires: Chars = frozenset()


# Characters that can leave a value's place somewhere: in the shell, in a string of a program, or
# unquoted in Python or R code, where a call needs no quotes (eval(chr(105) + chr(100))). Not "?":
# it is Galaxy's unknown dbkey, and in the shell it only globs.
NOT_PLAIN = frozenset("'\"`$;&|<>\\\n\r\t(){}[]%#*")
# Galaxy's sanitizer writes these for the characters it maps; templates often turn them back.
_SANITIZER_TOKENS = re.compile("|".join(re.escape(token) for token in sorted(set(mapped_chars.values()))))
_TOKEN_CHARS = {token: char for char, token in mapped_chars.items()}
# A word that starts with a dash can be read as an option.
_OPTION_WORD = re.compile(r"(?:^|\s)-")


def default_chars(sanitize: bool) -> Chars:
    """What a text value can hold as Galaxy writes it: through the default sanitizer, or anything."""
    return DEFAULT_SANITIZED if sanitize else PROBE


def not_plain(value: str) -> frozenset[str]:
    """What keeps a value from being plain: its characters, or "-" for a word read as an option.

    A sanitizer token counts as the character it stands for, which is what the user wrote.
    """
    harm = set(value) & NOT_PLAIN
    if _OPTION_WORD.search(value):
        harm.add("-")
    harm.update(_TOKEN_CHARS[token] for token in _SANITIZER_TOKENS.findall(value))
    return frozenset(harm)


def unquoted(chars: Chars, word_first: Chars | None = None, script: bool = False) -> Verdict | None:
    """``word_first``: probe characters a word of the value can begin with, when narrower than ``chars``.

    ``script``: the value is in a shell script, where a newline ends the command. Galaxy writes the
    command of a tool on one line.
    """
    if hit := chars & (SCRIPT_EXEC if script else SHELL_EXEC):
        return Verdict("shell-injection", HIGH, hit, "can start another command")
    if hit := chars & SHELL_SPLIT:
        dash = "-" in (chars if word_first is None else word_first)
        if hit <= WHITESPACE and not dash and "/" not in chars:
            # A list of plain words: none of them can be an option or name a file elsewhere.
            return Verdict("argument-injection", LOW, hit, "can split the word into extra plain words")
        return Verdict(
            "argument-injection",
            MEDIUM,
            hit,
            "can split the word into extra arguments or globs",
            data_requires=DATA_HARM,
        )
    return None


def single_quoted(chars: Chars, script: bool = False) -> Verdict | None:
    if "'" not in chars:
        return None
    after = unquoted(chars, script=script)
    if after and after.rule == "shell-injection":
        return Verdict(
            "shell-injection",
            HIGH,
            after.chars | {"'"},
            "can close the single quotes and start a command",
            frozenset("'"),
            after.chars,
        )
    return Verdict("argument-injection", MEDIUM, frozenset("'"), "can close the single quotes", data_requires=DATA_HARM)


def double_quoted(chars: Chars, script: bool = False) -> Verdict | None:
    exec_chars = SCRIPT_EXEC if script else SHELL_EXEC
    if "`" in chars or ("$" in chars and "(" in chars):
        hit = chars & frozenset("`$(")
        breakout = hit - {"("}
        if '"' in chars and chars & exec_chars:
            # Or close the quotes, which starts a command only with a command character after them.
            # `$` and the backtick are command characters themselves.
            return Verdict(
                "shell-injection",
                HIGH,
                hit,
                "can run a command substitution inside the double quotes",
                breakout | {'"'},
                chars & exec_chars,
            )
        return Verdict(
            "shell-injection", HIGH, hit, "can run a command substitution inside the double quotes", breakout
        )
    if '"' in chars:
        after = unquoted(chars, script=script)
        if after and after.rule == "shell-injection":
            return Verdict(
                "shell-injection",
                HIGH,
                after.chars | {'"'},
                "can close the double quotes and start a command",
                frozenset('"'),
                after.chars,
            )
        return Verdict(
            "argument-injection", MEDIUM, frozenset('"'), "can close the double quotes", data_requires=DATA_HARM
        )
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
# The quotes that start a string literal in a language, where they differ from '...' and "...".
STRING_QUOTES = {"sed": "", "awk": '"'}
_CODE_DEFAULT: tuple[Chars, Chars] = (frozenset("'\"`;()"), PROBE - frozenset("_-.,:=+@%/^"))
# Languages whose code needs no quote or bracket to run a command: Perl's qx/id/ or `system id`,
# Ruby's %x[id]. Letters alone can be code there.
_LETTER_CODE = frozenset(("perl", "ruby"))
# Characters that run code inside a "..." string of a language that interpolates expressions:
# Perl's @{[ ... ]} and ${\ ... }, Ruby's #{...}, PHP's {${...}}.
_INTERPOLATION = {"perl": frozenset("$@"), "ruby": frozenset("#"), "php": frozenset("${")}


def code(lang: str, chars: Chars, quote: str = "") -> Verdict | None:
    """Value written into a program text that another interpreter parses (``sh -c``, ``awk``, a script)."""
    high, medium = _CODE_BREAK.get(lang, _CODE_DEFAULT)
    if quote not in STRING_QUOTES.get(lang, "'\""):
        # Not a string in this language: sed has none, awk only "...".
        quote = ""
    if quote and lang != "sh":
        # Inside a string literal of the nested program only its delimiter and the escape character
        # matter, and in a "..." string of a language that interpolates, what starts an expression.
        interpolation = _INTERPOLATION.get(lang, frozenset()) if quote == '"' else frozenset()
        if hit := chars & (interpolation | {quote}):
            why = (
                f"can end the string and inject {lang} code"
                if quote in hit
                else f"can run {lang} code inside the string"
            )
            return Verdict("nested-interpreter", HIGH, hit, why)
        if "\\" in chars:
            # A syntax error by itself; code only when a second user-controlled string follows on the line.
            return Verdict("nested-interpreter", LOW, frozenset("\\"), "can escape the closing quote of the string")
        return None
    if lang in _LETTER_CODE:
        return Verdict(
            "nested-interpreter",
            HIGH,
            chars,
            f"is read as {lang} code, where letters alone can run a command",
            frozenset(),
        )
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


def _flag(value: int, name: str) -> bool:
    return bool(value & getattr(sre_constants, f"SRE_FLAG_{name}"))


def _end_anchor(items: Any, multiline: bool = False) -> str | None:
    """How the expression is anchored at the end: "string" (``\\Z``), "line" (``$``) or None.

    With MULTILINE, ``$`` matches before any newline: it does not anchor the end.
    """
    items = list(items)
    if not items:
        return None
    op, arg = items[-1]
    if op is sre_constants.AT:
        if arg == sre_constants.AT_END_STRING:
            return "string"
        return "line" if arg == sre_constants.AT_END and not multiline else None
    if op is sre_constants.BRANCH:
        anchors = [_end_anchor(alternative, multiline) for alternative in arg[1]]
        if None in anchors:
            return None
        return "line" if "line" in anchors else "string"
    if op is sre_constants.SUBPATTERN:
        _group, add_flags, del_flags, pattern = arg
        inner = (multiline or _flag(add_flags, "MULTILINE")) and not _flag(del_flags, "MULTILINE")
        return _end_anchor(pattern, inner)
    return None


def _parsed_flags(parsed: Any) -> int:
    state = getattr(parsed, "state", None) or getattr(parsed, "pattern", None)
    return getattr(state, "flags", 0)


def _end_anchored(items: Any) -> bool:
    return _end_anchor(items, _flag(_parsed_flags(items), "MULTILINE")) is not None


def regex_anchored_start(expression: str) -> bool:
    """``re.search`` with this expression only matches at the start of the value.

    Every alternative must begin with ``^`` or ``\\A``, and ``^`` must not be MULTILINE.
    """
    try:
        parsed = sre_parse.parse(expression)
    except Exception:
        return False
    multiline = _flag(_parsed_flags(parsed), "MULTILINE")

    def anchored(items: Any) -> bool:
        items = list(items)
        if not items:
            return False
        op, arg = items[0]
        if op is sre_constants.AT:
            if arg == sre_constants.AT_BEGINNING_STRING:
                return True
            return arg == sre_constants.AT_BEGINNING and not multiline
        if op is sre_constants.BRANCH:
            return all(anchored(alternative) for alternative in arg[1])
        if op is sre_constants.SUBPATTERN:
            _group, add_flags, _del_flags, pattern = arg
            return not _flag(add_flags, "MULTILINE") and anchored(pattern)
        return False

    return anchored(parsed)


def regex_universe(expression: str) -> Chars:
    """Probe characters a value accepted by a Galaxy ``regex`` validator may contain.

    Galaxy applies the expression with ``re.match``: anchored at the start only. Without a
    final ``$`` the tail of the value is unconstrained, so every character is possible. A
    final ``$`` also matches before a newline that ends the value.
    """
    try:
        parsed = sre_parse.parse(expression)
    except Exception:
        return PROBE
    flags = _parsed_flags(parsed)
    anchor = _end_anchor(parsed, _flag(flags, "MULTILINE"))
    if anchor is None:
        return PROBE
    consumed = _consumed(parsed)
    if _flag(flags, "DOTALL"):
        # `.` also matches a newline.
        consumed = consumed | {"\n"}
    return consumed | {"\n"} if anchor == "line" and consumed != PROBE else consumed


# Stands for any character that is not a probe character (a letter, a digit, non-ASCII text).
_OTHER = "\x00"


def _one_or_other(op: Any, arg: Any) -> Chars | None:
    """Like :func:`_one`, plus :data:`_OTHER` when the item also matches characters that are not probes."""
    one = _one(op, arg)
    if one is None:
        return None
    if op is sre_constants.LITERAL:
        return one if one else frozenset(_OTHER)
    if op is sre_constants.IN:
        negated = any(o is sre_constants.NEGATE for o, _ in arg)
        letters = any(
            (o is sre_constants.LITERAL and chr(a) not in PROBE)
            or (o is sre_constants.RANGE and any(chr(c) not in PROBE for c in range(a[0], a[1] + 1)))
            or (o is sre_constants.CATEGORY and not str(a).endswith("CATEGORY_SPACE"))
            for o, a in arg
        )
        return one | {_OTHER} if negated or letters else one
    if op is sre_constants.CATEGORY:
        return one if str(arg).endswith("CATEGORY_SPACE") else one | {_OTHER}
    return one | {_OTHER}


class _Follow(NamedTuple):
    first: frozenset[str]
    # Each character a match can end with, with what a negative lookahead after it keeps from following.
    last: frozenset[tuple[str, frozenset[str]]]
    nullable: bool
    pairs: frozenset[tuple[str, str]]  # (a, b): b can come right after a
    pending: frozenset[str]  # for a match that can be empty: what its lookaheads keep from following


_EMPTY_FOLLOW = _Follow(frozenset(), frozenset(), True, frozenset(), frozenset())


def _sequence(a: _Follow, b: _Follow) -> _Follow:
    pairs = a.pairs | b.pairs | frozenset((x, y) for x, blocked in a.last for y in b.first - blocked)
    first = a.first | (b.first - a.pending if a.nullable else frozenset())
    last = b.last | (frozenset((x, blocked | b.pending) for x, blocked in a.last) if b.nullable else frozenset())
    pending = a.pending | b.pending if a.nullable and b.nullable else frozenset()
    return _Follow(first, last, a.nullable and b.nullable, pairs, pending)


def _follow(items: Any) -> _Follow | None:
    """First, last and adjacent characters of what a regex matches (Glushkov), None when unsupported."""
    out = _EMPTY_FOLLOW
    for op, arg in items:
        one = _one_or_other(op, arg)
        if one is not None:
            part = _Follow(one, frozenset((c, frozenset()) for c in one), False, frozenset(), frozenset())
        elif op is sre_constants.AT or op is sre_constants.ASSERT:
            continue
        elif op is sre_constants.ASSERT_NOT:
            direction, pattern = arg
            pattern = list(pattern)
            excluded = _one(*pattern[0]) if direction == 1 and len(pattern) == 1 else None
            part = _EMPTY_FOLLOW._replace(pending=excluded or frozenset())
        elif op is sre_constants.BRANCH:
            alternatives = [_follow(alternative) for alternative in arg[1]]
            known = [alternative for alternative in alternatives if alternative is not None]
            if len(known) != len(alternatives):
                return None
            part = _Follow(
                frozenset().union(*(f.first for f in known)),
                frozenset().union(*(f.last for f in known)),
                any(f.nullable for f in known),
                frozenset().union(*(f.pairs for f in known)),
                # A match through an alternative without a lookahead keeps nothing from following.
                (
                    frozenset.intersection(*(f.pending for f in known if f.nullable))
                    if any(f.nullable for f in known)
                    else frozenset()
                ),
            )
        elif op is sre_constants.SUBPATTERN:
            inner = _follow(arg[-1])
            if inner is None:
                return None
            part = inner
        elif op in _REPEATS:
            low, high, pattern = arg
            inner = _follow(pattern)
            if inner is None:
                return None
            pairs = inner.pairs
            if high is sre_constants.MAXREPEAT or high > 1:
                pairs = pairs | frozenset((x, y) for x, blocked in inner.last for y in inner.first - blocked)
            # Zero repetitions keep nothing from following.
            part = _Follow(
                inner.first, inner.last, inner.nullable or low < 1, pairs, inner.pending if low >= 1 else frozenset()
            )
        else:
            return None
        out = _sequence(out, part)
    return out


def regex_word_first(expression: str) -> Chars:
    """Probe characters that can begin a word (the value, or the text after whitespace) of an accepted value."""
    try:
        parsed = sre_parse.parse(expression)
    except Exception:
        return PROBE
    universe = regex_universe(expression)
    found = _follow(parsed) if universe != PROBE else None
    if found is None:
        return PROBE
    after_space = frozenset(b for a, b in found.pairs if a in WHITESPACE)
    return (regex_first(expression) | after_space) & PROBE


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


class LiteralRewrite(NamedTuple):
    """A rewrite with literal text: it adds the probe characters ``added`` only to a value that holds
    a character of ``trigger``."""

    trigger: Chars
    added: Chars


# A backslash before a letter or digit in a re.sub replacement: a group reference or an escape.
_REPLACEMENT_ESCAPE = re.compile(r"\\[0-9A-Za-z]")


def literal_rewrite(old: object, new: object, regex: bool) -> LiteralRewrite | None:
    """What ``value.replace(old, new)`` (``re.sub(old, new, value)`` with ``regex``) adds, and when.

    None when that is not known: text that is not literal, a match that can be empty or a character
    that is not a probe (a letter of a sanitizer token), a group reference in the replacement, new text
    with a character that is neither a probe nor a letter or digit (a carriage return).
    """
    if not isinstance(old, str) or not isinstance(new, str) or not old:
        return None
    if any(not c.isalnum() and c not in PROBE for c in new):
        return None
    if regex:
        if _REPLACEMENT_ESCAPE.search(new):
            return None
        try:
            if re.compile(old).match(""):
                return None
            matched = _listed(sre_parse.parse(old))
        except Exception:
            return None
    else:
        matched = frozenset(old)
    if not matched or not matched <= PROBE:
        return None
    return LiteralRewrite(matched, probe(new))


def _listed(items: Any) -> Chars | None:
    """Every character a regex can match, when the regex lists each one; None for a class like ``\\s``."""
    chars: set[str] = set()
    for op, arg in items:
        if op is sre_constants.LITERAL:
            chars.add(chr(arg))
        elif op is sre_constants.IN:
            for item, value in arg:
                if item is sre_constants.LITERAL:
                    chars.add(chr(value))
                elif item is sre_constants.RANGE and value[1] - value[0] < 256:
                    chars.update(chr(c) for c in range(value[0], value[1] + 1))
                else:
                    return None
        elif op in (sre_constants.BRANCH, sre_constants.SUBPATTERN) or op in _REPEATS:
            if op is sre_constants.BRANCH:
                inner = arg[1]
            elif op is sre_constants.SUBPATTERN:
                inner = [arg[-1]]
            else:
                inner = [arg[2]]
            for alternative in inner:
                found = _listed(alternative)
                if found is None:
                    return None
                chars.update(found)
        elif op is not sre_constants.AT:
            return None
    return frozenset(chars)


def plain_text(text: str) -> bool:
    """Literal template text that cannot turn a plain value into one that is not."""
    return not not_plain(text) and "-" not in text and not any(c.isspace() for c in text)
