"""A shell lexer that can be paused at a placeholder and resumed, and whose state can be compared.

The analysis walks the template's control flow and carries a *set* of lexer states: after an
``#if``/``#else`` the states of both branches are kept. At each placeholder every state answers
"where would this value land": unquoted, inside single or double quotes, in the program text
of ``sh -c``/``awk``/``python -c``, as the command word, or as a redirection target.

Galaxy joins the rendered lines of a command with spaces before running it, so a newline is
plain whitespace here, a ``#`` comment runs to the end of the command, and here-documents
cannot occur. A shell script configfile keeps its lines (:data:`SCRIPT`): a newline ends a
command and a comment. Scripts with here-documents are not read with this lexer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import (
    Any,
    NamedTuple,
    Optional,
    Tuple,
)

from .charsets import STRING_QUOTES
from .sed import (
    SedState,
    START as SED_START,
    step as sed_step,
)

_WORD_LIMIT = 48
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
_WRAPPER_ARG = re.compile(r"^(-.*|[0-9.]+[smhd]?|[A-Za-z_][A-Za-z0-9_]*=.*)$")

# Words after which the next word is still a command.
KEYWORDS = frozenset(
    ("if", "then", "else", "elif", "fi", "do", "done", "while", "until", "esac", "!", "{", "}", "time")
)
# Commands that run their arguments as another command.
WRAPPERS = frozenset(
    ("env", "nohup", "nice", "ionice", "exec", "command", "xargs", "parallel", "sudo", "stdbuf", "timeout", "setsid")
)
SHELLS = frozenset(("sh", "bash", "dash", "zsh", "ksh"))
_AWK = frozenset(("awk", "gawk", "mawk", "nawk"))
_SED = frozenset(("sed", "gsed"))
# Commands that take their program as an argument, so that a file they are given is data.
PROGRAM_IS_ARGUMENT = _AWK | _SED
_PYTHON = re.compile(r"^(python|pypy)[0-9.]*$")
# Commands whose arguments name files to create or replace.
FILE_COMMANDS = frozenset(("ln", "cp", "mv", "mkdir", "touch", "tee", "rm", "rmdir", "install", "rsync"))

_E_FLAG = re.compile(r"^-[A-Za-z0-9]*[eE]$")
_C_FLAG = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")


# Quote state of $'...': like single quotes, but a backslash escapes the next character.
ANSI = "$'"


class Frame(NamedTuple):
    """One command list: the top level, ``$(...)``, backticks or ``(...)``."""

    kind: str = "top"
    quote: str = ""
    inner: str = ""  # quote state inside the program text of a nested interpreter
    sed: Optional[SedState] = None  # where the program text of a sed command has got to
    sandbox: bool = False  # sed --sandbox: the program can neither run commands nor open files
    cmd: str | None = None  # "?" when the command word contains a placeholder
    wrapper: bool = False
    piped: bool = False
    expect: str = ""  # role forced on the next word: redir, optarg, code:<lang>
    script: str = ""  # the command still expects a program argument in this language
    code_all: str = ""  # every argument is program text (eval)
    word: str | None = None
    dynamic: bool = False
    role: str = ""
    lead: bool = False  # the current word began with a placeholder
    has_args: bool = False  # the command already has an argument that is not an option
    after_option: bool = False  # the previous word was an option, so this word may be its value


class ShellState(NamedTuple):
    frames: tuple[Frame, ...] = (Frame(),)
    esc: bool = False
    comment: bool = False
    last: str = ""
    amp: bool = False  # saw '&' that is a background operator unless '&' or '>' follows
    # A user value that can end in a backslash was written inside these quotes: it can escape the
    # closing quote, and the next quoted value then lands outside the quotes.
    escaped: str = ""
    # A script with lines of its own, not a command line.
    script: bool = False


@dataclass(frozen=True)
class Context:
    comment: bool
    quote: str
    role: str
    cmd: str | None
    lang: str
    inner: str
    lead: bool
    nested: bool
    first_arg: bool = False  # the first argument of the command that is not an option
    # The value starts an argument that does not follow an option: a leading dash makes it one.
    option_position: bool = False
    sed: Optional[SedState] = None  # where in a sed program the value lands
    sandbox: bool = False  # the sed program cannot run commands or open files

    def describe(self) -> str:
        where = {
            "": "unquoted",
            "'": "inside single quotes",
            '"': "inside double quotes",
            ANSI: "inside $'...' quotes",
        }[self.quote]
        if self.lang:
            inner = f", inside a {self.inner}...{self.inner} string of that program" if self.inner else ""
            what = f"in {self.lang} program text{inner}"
        elif self.role == "cmd":
            what = "as the command word"
        elif self.role == "redir":
            what = "as a redirection target"
        elif self.role == "stdin":
            what = "as the file redirected to standard input"
        elif self.cmd and self.cmd != "?":
            what = f"in an argument of `{self.cmd}`"
        else:
            what = "in an argument"
        if self.nested:
            what += " within a nested command"
        return f"{where}, {what}"


INITIAL = ShellState()
SCRIPT = ShellState(script=True)

Event = Tuple[str, ...]


class _Lexer:
    def __init__(self, state: ShellState, events: set[Event] | None):
        self.frames = list(state.frames)
        self.esc = state.esc
        self.comment = state.comment
        self.last = state.last
        self.amp = state.amp
        self.escaped = state.escaped
        self.script = state.script
        self.events = events

    def state(self) -> ShellState:
        return ShellState(tuple(self.frames), self.esc, self.comment, self.last, self.amp, self.escaped, self.script)

    @property
    def top(self) -> Frame:
        return self.frames[-1]

    def set(self, **changes: Any) -> None:
        self.frames[-1] = self.frames[-1]._replace(**changes)

    def event(self, *event: str) -> None:
        if self.events is not None:
            self.events.add(event)

    # -- words ---------------------------------------------------------------------------------

    def start_word(self, first: str) -> None:
        f = self.top
        if f.word is not None:
            return
        if f.expect:
            role = f.expect
            self.set(expect="")
        elif f.cmd is None:
            role = "cmd"
        elif f.code_all:
            role = f"code:{f.code_all}"
        elif f.script and first != "-":
            role = f"code:{f.script}"
            self.set(script="")
        else:
            role = "arg"
        self.set(word="", role=role, dynamic=False, lead=False, inner="", sed=SED_START if role == "code:sed" else None)

    def add(self, c: str) -> None:
        self.start_word(c)
        f = self.top
        if f.word is not None and len(f.word) < _WORD_LIMIT:
            self.set(word=f.word + c)
        if f.sed is not None:
            # Galaxy turns the newlines of a command line into spaces before it runs.
            self.set(sed=sed_step(f.sed, " " if c == "\n" and not self.script else c))

    def toggle_inner(self, c: str) -> None:
        """A quote in the program text of a nested interpreter starts or ends one of its strings."""
        f = self.top
        if c in STRING_QUOTES.get(f.role[5:], "'\""):
            self.set(inner="" if f.inner == c else c)

    def end_word(self) -> None:
        f = self.top
        if f.word is None:
            return
        text, dynamic, role = f.word, f.dynamic, f.role
        self.set(word=None, dynamic=False, role="", lead=False, inner="", sed=None)
        if not dynamic:
            self.event("word", text)
        if role == "cmd":
            self.end_command_word(text, dynamic)
        elif role == "arg":
            # `--name value`: the word after an option is taken as its value. `--` ends the options.
            self.set(after_option=text.startswith("-") and "=" not in text)
            if not text.startswith("-"):
                # A flag, not a count: a count would keep the states of two #if branches apart for good.
                self.set(has_args=True)
            if not dynamic:
                self.end_argument(text)

    def end_command_word(self, text: str, dynamic: bool) -> None:
        f = self.top
        if _ASSIGNMENT.match(text):
            return
        if not dynamic:
            if text in KEYWORDS:
                return
            if f.wrapper and _WRAPPER_ARG.match(text):
                return
        name = "?" if dynamic else text.rsplit("/", 1)[-1]
        self.event("command", name, "piped" if f.piped else "")
        if name in WRAPPERS:
            self.set(wrapper=True)
            return
        self.set(cmd=name, wrapper=False, has_args=False, sandbox=False)
        if name == "eval":
            self.set(code_all="sh")
        elif name in _AWK:
            self.set(script="awk")
        elif name in _SED:
            self.set(script="sed")

    def end_argument(self, text: str) -> None:
        cmd = self.top.cmd or ""
        # After its script operand, an interpreter passes every word to the script: `perl x.pl -e 1`.
        interpreter_option = not self.top.has_args
        if cmd in SHELLS and _C_FLAG.match(text) and interpreter_option:
            self.set(expect="code:sh")
        elif _PYTHON.match(cmd) and text == "-c" and interpreter_option:
            self.set(expect="code:python")
        elif cmd in ("perl", "ruby") and _E_FLAG.match(text) and interpreter_option:
            self.set(expect=f"code:{cmd}")
        elif cmd in ("Rscript", "R") and text == "-e" and interpreter_option:
            self.set(expect="code:R")
        elif cmd in ("node", "nodejs") and text in ("-e", "-p", "--eval", "--print") and interpreter_option:
            self.set(expect="code:javascript")
        elif cmd == "php" and text == "-r" and interpreter_option:
            self.set(expect="code:php")
        elif cmd in _AWK:
            if text in ("-v", "-F", "--assign", "--field-separator", "-i", "--include"):
                self.set(expect="optarg")
            elif text in ("-f", "--file"):
                self.set(expect="scriptfile", script="")
        elif cmd in _SED:
            if text in ("-e", "--expression"):
                self.set(expect="code:sed", script="")
            elif text in ("-f", "--file"):
                self.set(expect="scriptfile", script="")
            elif text == "--sandbox":
                self.set(sandbox=True)
        elif cmd == "find" and text in ("-exec", "-execdir", "-ok", "-okdir"):
            # What follows is a command of its own.
            self.set(cmd=None, has_args=False)

    def new_command(self, piped: bool = False) -> None:
        self.end_word()
        self.set(
            cmd=None,
            wrapper=False,
            piped=piped,
            expect="",
            script="",
            code_all="",
            has_args=False,
            after_option=False,
            sandbox=False,
        )

    # -- characters ----------------------------------------------------------------------------

    def push(self, kind: str) -> None:
        self.frames.append(Frame(kind=kind))

    def pop(self) -> None:
        self.end_word()
        if len(self.frames) > 1:
            self.frames.pop()

    def step(self, c: str) -> None:
        if self.comment:
            if self.script and c == "\n":
                self.comment = False
                self.last = ""
                self.new_command()
            return
        last, self.last = self.last, c
        if self.amp:
            self.amp = False
            if c not in "&>":
                self.event("background")
        f = self.top
        if self.esc:
            self.esc = False
            if f.quote == '"' and c == '"' and f.role.startswith("code:"):
                self.toggle_inner(c)
            if f.quote == '"' and c not in '$`"\\\n':
                # Inside double quotes the shell keeps a backslash that escapes nothing.
                self.add("\\")
            self.add(c)
            self.last = ""
            return
        if f.quote == ANSI:
            if c == "\\":
                self.esc = True
            elif c == "'":
                self.set(quote="")
            else:
                self.add(c)
            return
        if f.quote == "'":
            if c == "'":
                self.set(quote="")
            else:
                if c == '"' and f.role.startswith("code:"):
                    self.toggle_inner(c)
                self.add(c)
            return
        if c == "`":
            if f.kind == "bt":
                self.pop()
            else:
                self.start_word(c)
                self.push("bt")
            return
        if f.quote == '"':
            if c == "\\":
                self.esc = True
            elif c == '"':
                self.set(quote="")
            elif c == "(" and last == "$":
                self.push("cs")
            else:
                if c == "'" and f.role.startswith("code:"):
                    self.toggle_inner(c)
                self.add(c)
            return
        # Unquoted.
        if c == "\\":
            self.esc = True
            self.start_word(c)
        elif c in "'\"":
            self.start_word(c)
            self.set(quote=ANSI if c == "'" and last == "$" else c)
        elif c == "\n" and self.script:
            if f.cmd is None and f.word is None:
                # A line after `|` or `&&` continues the command list.
                self.end_word()
            else:
                self.new_command()
        elif c in " \t\n\r":
            self.end_word()
        elif c == "(":
            if last == "$":
                self.push("cs")
            else:
                if last in "<>":
                    self.set(expect="")
                self.end_word()
                self.push("sub")
        elif c == ")":
            if f.kind in ("cs", "sub") and len(self.frames) > 1:
                self.pop()
            else:
                self.end_word()
        elif c == ";":
            self.new_command()
        elif c == "|":
            self.new_command(piped=last != "|")
        elif c == "&":
            if last in "<>":
                self.add(c)
            else:
                self.new_command()
                self.amp = last != "&"
        elif c in "<>":
            if f.word is not None and f.word.isdigit() and not f.dynamic:
                self.set(word=None, role="")
            else:
                self.end_word()
            if c == ">":
                self.set(expect="redir")
            else:
                self.set(expect="optarg" if last == "<" else "stdin")
        elif c == "#" and f.word is None:
            self.comment = True
        else:
            self.add(c)

    def placeholder(self) -> Context:
        if self.comment:
            return Context(True, "", "", None, "", "", False, False)
        self.esc = False
        self.last = ""
        self.amp = False
        f = self.top
        lead = f.word is None or (f.word == "" and not f.dynamic)
        self.start_word("x")
        f = self.top
        self.set(dynamic=True, lead=f.lead or lead)
        f = self.top
        lang = inner = ""
        sed_state = None
        sandbox = False
        for frame in reversed(self.frames):
            if frame.role.startswith("code:"):
                lang, inner, sed_state, sandbox = frame.role[5:], frame.inner, frame.sed, frame.sandbox
                break
        role = f.role
        if role == "cmd" and _ASSIGNMENT.match(f.word or ""):
            # The value of a `NAME=value` prefix, not the command itself.
            role = "arg"
        first_arg = role == "arg" and not f.has_args and not (f.word or "").startswith("-")
        option_position = role == "arg" and f.lead and not f.after_option and bool(f.cmd) and f.cmd != "?"
        return Context(
            False,
            f.quote,
            role,
            f.cmd,
            lang,
            inner,
            f.lead,
            len(self.frames) > 1,
            first_arg,
            option_position,
            sed_state,
            sandbox,
        )


def feed(state: ShellState, text: str, events: set[Event] | None = None) -> ShellState:
    """Advance over literal template text."""
    lexer = _Lexer(state, events)
    for c in text:
        lexer.step(c)
    return lexer.state()


def placeholder(state: ShellState) -> tuple[Context, ShellState]:
    """Where a value written at this point lands, and the state after it."""
    lexer = _Lexer(state, None)
    context = lexer.placeholder()
    return context, lexer.state()


def finish(state: ShellState, events: set[Event] | None = None) -> ShellState:
    """End of the template: close the last word so its events are reported."""
    lexer = _Lexer(state, events)
    if not lexer.comment:
        if lexer.amp:
            lexer.event("background")
        while len(lexer.frames) > 1:
            lexer.pop()
        lexer.end_word()
    return lexer.state()
