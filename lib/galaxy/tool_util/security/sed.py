"""Where a value lands in a GNU sed program, from the program text before it.

GNU sed runs shell commands with the ``e`` command and the ``e`` flag of ``s``, and writes
files with ``w``. Where the program expects a command, letters alone can be one, so no
character test decides the value. Inside the pattern or replacement of ``s`` (or ``y``), or
inside a regular expression address, the value stays there unless it brings the delimiter, a
backslash, or a newline. sed has no string literals: quotes are plain characters to it.
"""

from __future__ import annotations

from typing import NamedTuple

from .charsets import (
    Chars,
    HIGH,
    PROBE,
    Verdict,
)

COMMAND = "command"  # where a command or its address starts
WAIT_ADDRESS = "wait-address"  # after `\` in an address: the next character is the delimiter
ADDRESS = "address"  # inside a regular expression address
WAIT_S = "wait-s"  # after `s`: the next character is the delimiter
WAIT_Y = "wait-y"
PATTERN = "pattern"  # the first part of s or y
REPLACEMENT = "replacement"  # the second part of s or y
FLAGS = "flags"  # after s///
TEXT = "text"  # the text of a, i or c, to the end of the line
LABEL = "label"  # the label of b, t, T or :
FILE = "file"  # the file name of r, R, w, W or of the w flag
EXEC = "exec"  # the command of e
COMMENT = "comment"


class SedState(NamedTuple):
    kind: str = COMMAND
    delimiter: str = ""
    command: str = ""  # s or y, in PATTERN and REPLACEMENT
    escaped: bool = False
    # 1: right after `[` or `[^`, where `]` is literal; 2: inside the bracket expression.
    bracket: int = 0


START = SedState()

_ONE_LINE = {"a": TEXT, "i": TEXT, "c": TEXT, "b": LABEL, "t": LABEL, "T": LABEL, ":": LABEL}
_TO_END_OF_LINE = {"r": FILE, "R": FILE, "w": FILE, "W": FILE, "e": EXEC, "#": COMMENT}


def step(state: SedState, c: str) -> SedState:
    """The state after one more character of program text."""
    kind = state.kind
    if state.escaped:
        return state._replace(escaped=False)
    if kind == COMMAND:
        if c == "/":
            return SedState(ADDRESS, "/")
        if c == "\\":
            return SedState(WAIT_ADDRESS)
        if c == "s":
            return SedState(WAIT_S)
        if c == "y":
            return SedState(WAIT_Y)
        if c in _ONE_LINE:
            return SedState(_ONE_LINE[c])
        if c in _TO_END_OF_LINE:
            return SedState(_TO_END_OF_LINE[c])
        # Line numbers, `$`, `,`, `!`, `{`, `}`, `;`, whitespace and one-letter commands.
        return state
    if kind == WAIT_ADDRESS:
        return SedState(ADDRESS, c)
    if kind in (WAIT_S, WAIT_Y):
        return SedState(PATTERN, c, "s" if kind == WAIT_S else "y")
    if kind in (ADDRESS, PATTERN, REPLACEMENT):
        if c == "\\":
            return state._replace(escaped=True)
        regex = kind != REPLACEMENT and state.command != "y"
        if regex and state.bracket:
            if c == "^" and state.bracket == 1:
                return state
            if c == "]" and state.bracket == 2:
                return state._replace(bracket=0)
            return state._replace(bracket=2)
        if regex and c == "[":
            return state._replace(bracket=1)
        if c != state.delimiter:
            return state
        if kind == ADDRESS:
            return START
        if kind == PATTERN:
            return state._replace(kind=REPLACEMENT)
        return SedState(FLAGS) if state.command == "s" else START
    if kind == FLAGS:
        if c in "wW":
            return SedState(FILE)
        if c in ";\n}":
            return START
        return state
    if kind == TEXT:
        if c == "\\":
            # A backslash and a newline continue the text on the next line.
            return state._replace(escaped=True)
        return START if c == "\n" else state
    if kind == LABEL:
        return START if c in ";\n" else state
    # FILE, EXEC, COMMENT
    return START if c == "\n" else state


def breakout(state: SedState) -> Chars | None:
    """Characters one of which a value must bring to leave where it lands; None when letters are enough."""
    kind = state.kind
    if kind in (ADDRESS, PATTERN, REPLACEMENT):
        if state.delimiter not in PROBE:
            # A letter or digit delimiter: no probe character decides it.
            return None
        return frozenset((state.delimiter, "\\", "\n", "]"))
    if kind == TEXT:
        return frozenset("\n\\")
    if kind == LABEL:
        return frozenset(";\n} \t")
    if kind == COMMENT:
        return frozenset("\n")
    # A command, a delimiter, s flags, a file name or a command for `e`.
    return None


def verdict(chars: Chars, state: SedState) -> Verdict | None:
    leaves = breakout(state)
    if leaves is None:
        return Verdict(
            "nested-interpreter",
            HIGH,
            chars,
            "is read as sed commands, which can run a shell command (`e`) or write a file (`w`)",
            frozenset(),
        )
    if hit := chars & leaves:
        return Verdict(
            "nested-interpreter",
            HIGH,
            hit,
            "can end its place in the sed program and add a command, which can run a shell command (`e`)",
        )
    return None
