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

import re
import sys
from dataclasses import replace

from Cheetah.Parser import ParseError

from galaxy.tool_util.parser.interface import ToolSource
from .capabilities import (
    audit_shell_events,
    audit_tool_xml,
    PythonAudit,
)
from .charsets import CRITICAL
from .interp import (
    configfile_language,
    TemplateAnalysis,
    unresolved_names,
)
from .model import (
    build_model,
    Model,
)
from .report import (
    CAPABILITY,
    Finding,
    NOT_ANALYSED,
    Report,
    RUNS_TEXT,
    RUNS_TEXT_RULES,
    sorted_refs,
    Source,
    SourceRef,
    VULNERABILITY,
)
from .template import (
    compile_template,
    CompiledTemplate,
    CompileTimeExecution,
)

__all__ = ("Finding", "Report", "review_tool_source", "Source", "SourceRef")

# A here-document (`<<WORD`, `<<-WORD`), not the here-string `<<<`. An arithmetic `<<` matches too.
_HEREDOC = re.compile(r"(?<!<)<<(?!<)")


# `#include source=$name#` (or `${name}`, ending at the line end without the closing `#`).
_INCLUDE = re.compile(r"#include[ \t]+source[ \t]*=[ \t]*\$(?:\{(\w+)\}|(\w+)(?![\w.\[(]))[ \t]*#?")


def _include_templates(source: str, templates: dict[str, str]) -> str:
    """The template with each ``#include`` of a template macro replaced by the macro's text.

    Cheetah reads the included text as template code, so it is analysed in place. Lines after an
    include are numbered in the expanded text.
    """
    if not templates:
        return source
    for _ in range(10):
        expanded = _INCLUDE.sub(lambda m: templates.get(m.group(1) or m.group(2), m.group(0)), source)
        if expanded == source:
            break
        source = expanded
    return source


def _compile(source: str, location: str, report: Report) -> CompiledTemplate | None:
    try:
        return compile_template(source)
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


def _analyse(source: str, location: str, language: str, model: Model, report: Report) -> TemplateAnalysis | None:
    template = _compile(_include_templates(source, model.templates), location, report)
    if template is None:
        return None
    PythonAudit(report, location, model).template(template)
    for name in sorted(unresolved_names(template, model)):
        report.unanalyzed.append(f"{location}: ${name} is not a tool input, its value was not followed")
    analysis = TemplateAnalysis(model, template, report, location, language)
    try:
        analysis.run()
    except RecursionError:
        report.unanalyzed.append(f"{location}: template nests too deeply to analyse, the review of it is incomplete")
    return analysis


def review_tool_source(tool_source: ToolSource) -> Report:
    """The security review of a tool.

    The work on one template is bounded by the analysis' step budget: a template past it counts as
    not fully analysed.
    """
    report = Report(tool_id=tool_source.parse_id())
    if sys.version_info < (3, 9):
        # The analysis needs ast.unparse and the subscript syntax tree of Python 3.9.
        report.unanalyzed.append("the security review needs Python 3.9 or later")
        return report
    model = build_model(tool_source)
    readers: dict[str, set[str]] = {}

    command = tool_source.parse_command()
    if command:
        analysis = _analyse(command, "command", "shell", model, report)
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
            analysis = _analyse(content, location, "shell", model, report)
            if analysis is not None:
                audit_shell_events(analysis.events, report, location)
        else:
            _analyse(content, location, language, model, report)

    _mark_unchecked_locations(report)
    xml_tree = getattr(tool_source, "xml_tree", None)
    if xml_tree is not None:
        audit_tool_xml(xml_tree, report)
    return report


def _mark_unchecked_locations(report: Report) -> None:
    """Make the findings of a template that a character test cannot judge not checkable.

    A template with parts that were not analysed can write values the analysis did not follow,
    and a template that pipes text into a shell runs whatever a value says, whatever characters
    it has.
    """
    for note in report.unanalyzed:
        location, separator, _ = note.partition(": ")
        if separator and (location == "command" or location.startswith("configfile:")):
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
