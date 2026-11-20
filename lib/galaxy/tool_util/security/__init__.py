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

import sys

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
    Report,
)
from .template import (
    compile_template,
    CompiledTemplate,
    CompileTimeExecution,
)

__all__ = ("Finding", "Report", "review_tool_source")


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
    template = _compile(source, location, report)
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
        _analyse(content, f"configfile:{name}", language, model, report)

    xml_tree = getattr(tool_source, "xml_tree", None)
    if xml_tree is not None:
        audit_tool_xml(xml_tree, report)
    return report
