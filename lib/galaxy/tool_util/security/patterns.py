"""Access patterns: the ways a template reads data that the job check cannot see.

Each capability finding of the review that reads data (``CODE_CAPABILITIES``) gets one pattern code. Most
codes bypass the job check: it compares the job's values with the review's findings, and a value read
this way is no value of the job. A job of such a tool is refused only when the review also sees the read
value written where it can do harm. The other codes read values the server sets.
"""

import re
from enum import Enum
from typing import (
    Dict,
    List,
    Optional,
)

from galaxy.tool_util.security.report import (
    CODE_CAPABILITIES,
    Finding,
    Report,
    SANITIZE_OFF,
)


class PatternCode(str, Enum):
    # The job check cannot see the value read.
    REFLECTION = "reflection"
    MODEL_ACCESS = "model-access"
    APP_ACCESS = "app-access"
    USER_OBJECT = "user-object"
    FILE_ACCESS = "file-access"
    TEMPLATE_CODE = "template-code"
    # The value read is set by the server.
    JOB_METADATA = "job-metadata"
    SERVER_CONFIG = "server-config"


SERVER_VALUES = frozenset((PatternCode.JOB_METADATA, PatternCode.SERVER_CONFIG))

DESCRIPTIONS = {
    PatternCode.REFLECTION: "Reaches objects by name (`getattr`, `__getattribute__`, `getVar` with a computed name,"
    " Python or Cheetah internals). The review loses track of what is read, `.unsanitized` values included.",
    PatternCode.MODEL_ACCESS: "Reads Galaxy's database objects (`.unsanitized`, `.dataset`, `.creating_job`, ...):"
    " names, metadata and parameters as users set them, without the sanitizer.",
    PatternCode.APP_ACCESS: "Reads Galaxy's application object beyond its configuration (`$__app__.model`, ...),"
    " which reaches any data of the server.",
    PatternCode.USER_OBJECT: "Reads the user object with the sanitizer off. A preference read by its name is"
    " checked; anything else read from the user object is not.",
    PatternCode.FILE_ACCESS: "Reads or inspects files on the server (`open()`, `os.path`, ...). The review traces"
    " `open()` of an input dataset as its content; any other file is not a value of the job.",
    PatternCode.TEMPLATE_CODE: "Runs Python the review cannot follow (`exec`, `compile`, imports of modules that"
    " start processes or open connections, `#include` of anything but a template macro, a lambda that reads more"
    " than its arguments or changes a value).",
    PatternCode.JOB_METADATA: "Checks for the job that made a dataset, or reads its tool id or version, which the"
    " server sets.",
    PatternCode.SERVER_CONFIG: "Reads the server's configuration or encodes ids (`$__app__.config`,"
    " `$__app__.security`).",
}

# `$input.creating_job`, as the review writes the expression, with the tool id or version of that job.
_JOB_METADATA = re.compile(r"(^\$?|\.)creating_job(\.tool_(id|version))?$")
_SERVER_CONFIG_ATTRIBUTES = frozenset(("config", "security"))


def access_patterns(report: Report) -> Dict[PatternCode, List[Finding]]:
    """The findings of the report that read data the job does not carry, by pattern code."""
    sanitized = not any(f.rule == SANITIZE_OFF for f in report.findings)
    patterns: Dict[PatternCode, List[Finding]] = {}
    for finding in report.findings:
        code = pattern_of(finding, sanitized)
        if code is not None:
            patterns.setdefault(code, []).append(finding)
    return patterns


def pattern_of(finding: Finding, sanitized: bool) -> Optional[PatternCode]:
    if finding.rule not in CODE_CAPABILITIES:
        return None
    expr = finding.expr or ""
    parts = expr.lstrip("$").split(".")
    if parts[0] == "__user__":
        # Galaxy sanitizes what a template reads from the user object, unless the tool turns that off.
        return None if sanitized else PatternCode.USER_OBJECT
    if parts[0] == "__app__":
        server = len(parts) > 1 and parts[1] in _SERVER_CONFIG_ATTRIBUTES
        return PatternCode.SERVER_CONFIG if server else PatternCode.APP_ACCESS
    if finding.rule == "template-model-access":
        return PatternCode.JOB_METADATA if _JOB_METADATA.search(expr) else PatternCode.MODEL_ACCESS
    if finding.rule == "template-reflection":
        return PatternCode.REFLECTION
    if finding.rule == "template-file-io":
        return PatternCode.FILE_ACCESS
    return PatternCode.TEMPLATE_CODE
