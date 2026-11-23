"""The access pattern of a capability finding, from its rule and expression."""

import pytest

from galaxy.tool_util.security.charsets import MEDIUM
from galaxy.tool_util.security.patterns import (
    pattern_of,
    PatternCode,
)
from galaxy.tool_util.security.report import (
    CAPABILITY,
    Finding,
)


def _finding(rule: str, expr: str) -> Finding:
    return Finding(rule=rule, kind=CAPABILITY, severity=MEDIUM, message="", expr=expr)


@pytest.mark.parametrize(
    "rule,expr,sanitized,code",
    [
        ("template-model-access", "$select_tool.input.creating_job.tool_version", True, PatternCode.JOB_METADATA),
        ("template-model-access", "$creating_job.tool_id", True, PatternCode.JOB_METADATA),
        ("template-model-access", "$creating_job", True, PatternCode.JOB_METADATA),
        ("template-model-access", "$input.creating_job.parameters", True, PatternCode.MODEL_ACCESS),
        ("template-model-access", "$file_list.unsanitized.metadata.column_names.index", True, PatternCode.MODEL_ACCESS),
        ("template-model-access", "__app__.security.encode_id", True, PatternCode.SERVER_CONFIG),
        ("template-app-access", "__app__.config.galaxy_infrastructure_url", True, PatternCode.SERVER_CONFIG),
        ("template-app-access", "__app__.model.context.query", True, PatternCode.APP_ACCESS),
        ("template-app-access", "__app__", True, PatternCode.APP_ACCESS),
        ("template-reflection", "getVar", True, PatternCode.REFLECTION),
        ("template-reflection", "getattr", True, PatternCode.REFLECTION),
        ("template-file-io", "open", True, PatternCode.FILE_ACCESS),
        ("template-exec", "import subprocess", True, PatternCode.TEMPLATE_CODE),
        ("template-app-access", "__user__.extra_preferences", True, None),
        ("template-app-access", "__user__.extra_preferences", False, PatternCode.USER_OBJECT),
        ("template-model-access", "__user__.obj.unsanitized", False, PatternCode.USER_OBJECT),
        ("template-import", "import json", True, None),
    ],
)
def test_pattern_of(rule, expr, sanitized, code):
    assert pattern_of(_finding(rule, expr), sanitized) == code
