"""Static security review of a Galaxy tool.

:func:`review_tool_source` reads a parsed tool and reports

* **vulnerabilities**: user-controlled values (text parameters, element identifiers, dataset
  names, values taken from the user's data) that reach the command line or a configfile in a
  place where the characters they may still contain change what is executed;
* **capabilities**: what the tool's author made it able to do on the server, such as Python
  that runs inside the Galaxy process, network access, or a request for the user's API key.

Nothing from the tool is executed. Templates are compiled to Python with Cheetah's compiler
and the resulting syntax tree is analysed, see :mod:`.template` for why that is safe.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import Counter
from dataclasses import replace
from functools import partial

from Cheetah.Parser import ParseError

from galaxy.tool_util.parser.interface import ToolSource
from galaxy.util import string_as_bool
from .capabilities import (
    audit_shell_events,
    audit_tool,
    PythonAudit,
)
from .charsets import (
    CRITICAL,
    INFO,
)
from .interp import (
    configfile_language,
    TemplateAnalysis,
    unresolved_names,
)
from .known_helpers import (
    namespace_names,
    self_contained,
)
from .model import (
    build_model,
    Model,
)
from .report import (
    CAPABILITY,
    Finding,
    NOT_ANALYSED,
    rendered,
    Report,
    RUNS_TEXT,
    RUNS_TEXT_RULES,
    sorted_refs,
    Source,
    SourceRef,
    VULNERABILITY,
)
from .rewrites import rewrite_template
from .template import (
    checked_module,
    compile_template,
    CompiledTemplate,
    CompileTimeExecution,
    MACRO_METHOD,
    source_includes,
)

__all__ = ("Finding", "Report", "review_tool_source", "Source", "SourceRef")

# A here-document (`<<WORD`, `<<-WORD`), not the here-string `<<<`. An arithmetic `<<` matches too.
_HEREDOC = re.compile(r"(?<!<)<<(?!<)")


# `#include source=$name#`, or without the closing `#` (then it takes the newline of its line).
_INCLUDE = re.compile(r"#include[ \t]+source[ \t]*=[ \t]*\$(\w+)(?![\w.\[(])([ \t]*#)?")
# Template macros one template reads in.
_MAX_MACROS = 100


def _include_templates(source: str, location: str, model: Model, report: Report) -> str:
    """The template with each ``#include source=$name#`` of a template macro read in as a ``#def`` of its text.

    A ``#def`` renders as Cheetah renders an include, with locals of its own; only where nothing but the macro answers.
    """
    macros = {
        name: text
        for name, text in model.templates.items()
        if model.lookup(name) is None and model.lookup(MACRO_METHOD + name) is None
    }
    if any(MACRO_METHOD in text for text in (source, *macros.values())):
        return source
    while True:
        try:
            read_in, included, misread = _read_in(source, macros)
            if included and not misread:
                tree = checked_module(read_in)
                names = {name for name, _ in included}
                misread = names - namespace_names(tree, names)
                defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
                if not {MACRO_METHOD + name for name in names} <= defined:
                    misread = names  # the end of the template took the methods in
        except Exception:
            return source  # a template can break Cheetah's parser; compiling it reports why
        if not misread:
            for name, line in included:
                report.add(
                    Finding(
                        rule="template-macro",
                        kind=CAPABILITY,
                        severity=INFO,
                        message=f"Includes the template macro `{name}`, reviewed in place.",
                        location=location,
                        line=line,
                        expr=name,
                    )
                )
            return read_in
        macros = {name: text for name, text in macros.items() if name not in misread}


def _read_in(source: str, macros: dict[str, str]) -> tuple[str, list[tuple[str, int | None]], set[str]]:
    """``source`` with the includes of ``macros`` read in, and the name and line (None in a macro) of each include;
    or ``source`` and the macros that cannot be read in."""
    texts: dict[str | None, str] = {}
    graph: dict[str | None, set[str]] = {}
    included: list[tuple[str, int | None]] = []
    misread: set[str] = set()
    pending: list[str | None] = [None]
    while pending:
        key = pending.pop()
        if key in graph:
            continue
        text = source if key is None else macros[key]
        tree = checked_module(text)
        matches = [match for match in _INCLUDE.finditer(text) if match.group(1) in macros]
        found = Counter(match.group(1) for match in matches)
        directives = source_includes(tree)
        # Include text in a comment, a #raw block or a string is not the directive.
        misread |= {name for name, count in found.items() if directives[name] != count}
        if key is not None and not self_contained(tree):
            misread.add(key)
        if len(graph) >= _MAX_MACROS:
            misread |= set(found)
        graph[key] = set(found)
        included += [(m.group(1), text.count("\n", 0, m.start()) + 1 if key is None else None) for m in matches]
        texts[key] = _INCLUDE.sub(lambda m: _call(m) if m.group(1) in macros else m.group(0), text)
        pending.extend(found)
    misread |= _cycles(graph)
    if misread:
        return source, [], misread
    methods = "".join(f"\n#def {MACRO_METHOD}{name}\n{_closed(text)}" for name, text in texts.items() if name)
    return f"{texts[None]}{methods}\n", included, set()


def _call(match: re.Match[str]) -> str:
    """The `#echo` of the macro's method: a directive like the include, so the newline after it renders the same."""
    return f"#echo ${MACRO_METHOD}{match.group(1)}(){'#' if match.group(2) else ''}"


def _closed(text: str) -> str:
    """``text`` and an ``#end def`` that renders nothing: on a line of its own after a directive, else on its line."""
    last = text.rsplit("\n", 1)[-1].strip()
    # A line of a directive or a comment alone renders nothing, not even its newline.
    lone = (last.startswith("#") and not last.endswith("#")) or last.endswith("#slurp")
    return f"{text}\n#end def" if lone else f"{text}#end def"


def _cycles(graph: dict[str | None, set[str]]) -> set[str]:
    """The macros that include themselves, through others too."""

    def reaches(start: str) -> set[str]:
        seen: set[str] = set()
        pending = list(graph.get(start, ()))
        while pending:
            if (name := pending.pop()) not in seen:
                seen.add(name)
                pending.extend(graph.get(name, ()))
        return seen

    return {name for name in graph if name is not None and name in reaches(name)}


def _compile(source: str, location: str, report: Report, model: Model) -> CompiledTemplate | None:
    try:
        return compile_template(source, partial(rewrite_template, model=model))
    except CompileTimeExecution as e:
        report.add(
            Finding(
                rule="template-compile-exec",
                kind=CAPABILITY,
                severity=CRITICAL,
                message=(
                    f"Uses the Cheetah directive #{e.directive}, which runs code while the template is compiled"
                    " (runs in the Galaxy server process). The template was not analysed further."
                ),
                location=location,
                line=e.line or None,
                expr=f"#{e.directive}",
            )
        )
    except (ParseError, SyntaxError, ValueError) as e:
        report.unanalyzed.append(f"{location}: template does not compile ({type(e).__name__})")
    except Exception as e:
        # A template can be written to break Cheetah's parser. The review must still return.
        report.unanalyzed.append(f"{location}: Cheetah failed on the template ({type(e).__name__})")
    return None


def _analyse(
    source: str,
    location: str,
    language: str,
    model: Model,
    report: Report,
    names: dict[str, tuple[set[str], set[str]]],
) -> TemplateAnalysis | None:
    template = _compile(_include_templates(source, location, model, report), location, report, model)
    if template is None:
        return None
    audit = PythonAudit(report, location, model, analysed=True)
    audit.template(template)
    names[location] = (audit.names, audit.job_parameter_names())
    for name in sorted(unresolved_names(template, model, audit.assigned | audit.stored_keys, audit.namespace_reads)):
        report.unanalyzed.append(f"{location}: ${name} is not a tool input, its value was not followed")
    analysis = TemplateAnalysis(model, template, report, location, language, audit.literal_rewrites)
    try:
        analysis.run()
    except RecursionError:
        report.unanalyzed.append(f"{location}: template nests too deeply to analyse, the review of it is incomplete")
    return analysis


def _keeps_undeclared_job_parameters(tool_source: ToolSource) -> bool:
    """A data source tool, or `<inputs check_values="false">`: Galaxy passes the request parameters as sent."""
    if (tool_source.parse_tool_type() or "").startswith("data_source"):
        return True
    input_elem = getattr(tool_source.parse_input_pages(), "input_elem", None)
    return input_elem is not None and not string_as_bool(input_elem.get("check_values", "true"))


def review_tool_source(
    tool_source: ToolSource,
    template_job_parameters: frozenset[str] | None = None,
    keeps_undeclared_job_parameters: bool | None = None,
    colors_validated: bool = True,
) -> Report:
    """The security review of a tool.

    ``template_job_parameters`` are the job parameters besides the tool's inputs that Galaxy passes
    to the tool's templates (``Tool.template_job_parameters``); None when they are not known, and
    then a job parameter of any name can reach them, as it does for a tool that keeps the job
    parameters that are not inputs (``Tool.keeps_undeclared_job_parameters``, a data source tool);
    None reads that from the tool's ``<inputs check_values>``. Such a job parameter also replaces the
    names Galaxy sets before it adds the job's parameters (``__galaxy_url__``, ...).

    ``colors_validated``: the Galaxy that runs the tool checks the values of color params as it
    renders them (release 25.1 and later). The default assumes such a Galaxy; False reviews the tool
    for an older one, which writes any value it is sent.

    The work on one template is bounded by the analysis' step budget: a template past it counts as
    not fully analysed.
    """
    report = Report(tool_id=tool_source.parse_id())
    if sys.version_info < (3, 9):
        # The analysis needs ast.unparse and the subscript syntax tree of Python 3.9.
        report.unanalyzed.append("the security review needs Python 3.9 or later")
        return report
    if keeps_undeclared_job_parameters is None:
        keeps_undeclared_job_parameters = _keeps_undeclared_job_parameters(tool_source)
    model = build_model(tool_source, template_job_parameters, keeps_undeclared_job_parameters, colors_validated)
    readers: dict[str, set[str]] = {}
    # The names each template mentions, and those it looks up where a job parameter can answer.
    names: dict[str, tuple[set[str], set[str]]] = {}

    command = tool_source.parse_command()
    if command:
        analysis = _analyse(command, "command", "shell", model, report, names)
        if analysis is not None:
            audit_shell_events(analysis.events, report, "command")
            readers = analysis.readers
    for name, content in model.configfiles.items():
        reader = sorted(readers.get(name, ()))
        language = configfile_language(content, reader[0] if reader else None)
        location = f"configfile:{name}"
        if language == "sh" and not _HEREDOC.search(content):
            # A shell script is read like the command, with its quoting and nested programs. The
            # body of a here-document is not shell code, and a quote in it would throw the rest
            # off: such a script is read string by string, a line at a time.
            analysis = _analyse(content, location, "shell", model, report, names)
            if analysis is not None:
                audit_shell_events(analysis.events, report, location)
        else:
            _analyse(content, location, language, model, report, names)

    _mark_unchecked_locations(report)
    for location, reason in report.unchecked_locations.items():
        if reason == NOT_ANALYSED:
            # Parts of the template were not followed: what it writes there is any input it names.
            reads = report.reads.setdefault(location, [])
            mentioned, looked_up = names.get(location, (set(), set()))
            reads.extend(ref for ref in model.sources(frozenset(mentioned), frozenset(looked_up)) if ref not in reads)
    audit_tool(tool_source, report)
    return report


def _mark_unchecked_locations(report: Report) -> None:
    """Make the findings of a template that a character test cannot judge not checkable.

    A template with parts that were not analysed can write values the analysis did not follow,
    and a template that pipes text into a shell runs whatever a value says, whatever characters
    it has.
    """
    for note in report.unanalyzed:
        location, separator, _ = note.partition(": ")
        if separator and rendered(location):
            report.unchecked_locations.setdefault(location, NOT_ANALYSED)
    for finding in report.findings:
        if finding.rule in RUNS_TEXT_RULES:
            report.unchecked_locations.setdefault(finding.location, RUNS_TEXT)
    if not report.unchecked_locations:
        return
    report.findings = [
        (
            replace(finding, unchecked=sorted_refs((*finding.unchecked, *finding.refs)))
            if finding.kind == VULNERABILITY and finding.location in report.unchecked_locations
            else finding
        )
        for finding in report.findings
    ]
    for location in report.unchecked_locations:
        report.writes.pop(location, None)
        report.closers.pop(location, None)
