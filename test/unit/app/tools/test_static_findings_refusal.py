import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import (
    cast,
    TYPE_CHECKING,
)

import pytest

from galaxy.config import (
    GALAXY_APP_NAME,
    GALAXY_CONFIG_SCHEMA_PATH,
    GalaxyAppConfiguration,
    STATIC_FINDINGS_SEVERITIES,
)
from galaxy.config.schema import AppSchema
from galaxy.exceptions import ConfigurationError
from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.patches import load_tool_patch_database
from galaxy.tool_util.security import review_tool_source
from galaxy.tool_util.security.charsets import (
    INFO,
    SEVERITIES,
)
from galaxy.tool_util.security.refusal import StaticReview
from galaxy.tool_util.unittest_utils import functional_test_tool_path
from galaxy.tool_util.unittest_utils.tool_patches import (
    replace_text_op,
    security_patch,
    write_collection,
)
from galaxy.tools import static_findings
from galaxy.tools.security_refusal import (
    built_tool_type,
    ToolInputRejected,
)
from galaxy.tools.static_findings import (
    check_static_findings,
    patch_and_review_tool_source,
    REVIEW_VERSION,
    static_review_is_current,
    with_static_review,
)

if TYPE_CHECKING:
    from galaxy.tools import Tool

TOOL = functional_test_tool_path("identifier_single_unsanitized.xml")
TOOLS_DIR = os.path.dirname(static_findings.__file__)
SET_METADATA_TOOL = os.path.join(TOOLS_DIR, os.pardir, "datatypes", "set_metadata_tool.xml")
GALAXY_UPLOAD_TOOL = os.path.join(TOOLS_DIR, "bundled", "data_source", "upload.xml")
# nested-interpreter is high while the sanitizer lets `;` through, medium once the patch takes it out.
AWK_TOOL = """<tool id="static_lowered" name="static_lowered" version="1.0">
    <command><![CDATA[awk 'BEGIN { print $x }' > '$out']]></command>
    <inputs>
        <param name="x" type="text" value="a">
            <sanitizer invalid_char=""><valid initial="string.letters"><add value=";"/></valid></sanitizer>
        </param>
    </inputs>
    <outputs><data name="out" format="txt"/></outputs>
</tool>
"""
LOWERING = security_patch(
    [
        {
            "replace_element": {
                "path": "inputs/param[@name='x']/sanitizer/valid/add",
                "old": '<add value=";"/>',
                "new": '<add value="/"/>',
                "occurrences": 1,
            }
        }
    ],
    "ordinary_inputs",
    "Jobs whose value of x held ';' now run without it.",
)


@dataclass
class RefusalConfig:
    tool_security_refuse_static_findings: bool = True
    tool_security_refuse_static_findings_severity: str = "high"


@dataclass
class ReviewedTool:
    static_review: StaticReview
    name: str = "Cat"
    id: str = "cat1"
    version: str = "1.0"


def _config(refuse: bool = True, severity: str = "high") -> "GalaxyAppConfiguration":
    return cast("GalaxyAppConfiguration", RefusalConfig(refuse, severity))


def _tool(severities: dict[str, str]) -> "Tool":
    return cast("Tool", ReviewedTool(StaticReview(severities=severities, version=REVIEW_VERSION)))


def test_refuses_a_job_naming_the_rules_at_or_above_the_severity() -> None:
    tool = _tool({"argument-injection": "medium", "shell-injection": "high", "template-exec": "critical"})
    with pytest.raises(ToolInputRejected) as e:
        check_static_findings(tool, _config())
    assert str(e.value) == (
        "[static-findings] This job was not run: the security review of this tool reports shell-injection,"
        " template-exec, and this Galaxy server does not run such tools. Please contact the administrators of this"
        " server. Tool 'Cat' (cat1 version 1.0)."
    )


@pytest.mark.parametrize("refuse, severity", [(False, "high"), (True, "critical")], ids=["off", "below"])
def test_runs_a_job_without_a_finding_that_refuses(refuse: bool, severity: str) -> None:
    check_static_findings(_tool({"shell-injection": "high"}), _config(refuse, severity))


def test_reviews_the_patched_source_only_when_refusals_are_on(tmp_path: Path) -> None:
    tool = tmp_path / "static_lowered.xml"
    tool.write_text(AWK_TOOL)
    db = load_tool_patch_database([str(write_collection(tmp_path / "c", {"_local/static_lowered/1.0.yml": LOWERING}))])

    def review(config: "GalaxyAppConfiguration") -> StaticReview | None:
        return patch_and_review_tool_source(config, db, get_tool_source(str(tool)), None, tool).static_review

    assert review(_config()) == StaticReview(severities={"nested-interpreter": "medium"}, version=REVIEW_VERSION)
    assert review(_config(refuse=False)) is None


def _logged(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == static_findings.__name__]


def _built(path: str | Path) -> str | None:
    tool_type: str | None = built_tool_type(get_tool_source(str(path)))
    return tool_type


@pytest.mark.parametrize("path", [GALAXY_UPLOAD_TOOL, SET_METADATA_TOOL], ids=os.path.basename)
def test_galaxy_own_tools_are_not_reviewed(path: str, caplog: pytest.LogCaptureFixture) -> None:
    # Which tools are Galaxy's own is is_galaxy_own_tool's, tested with it; here, that the review leaves them out.
    # upload1's $paramfile is option-injection at low, though Galaxy sets it to a path in the job directory.
    caplog.set_level(logging.INFO, logger=static_findings.__name__)
    assert with_static_review(_config(severity="low"), get_tool_source(path), path).static_review is None
    assert static_review_is_current(_config(severity="low"), None, path, _built(path), None)
    # Galaxy says so at load, once and naming the tool, while refusals are on.
    (said,) = _logged(caplog)
    assert path in said and "it is one of Galaxy's own tools" in said
    caplog.clear()
    assert with_static_review(_config(refuse=False), get_tool_source(path), path).static_review is None
    assert _logged(caplog) == []


INTERACTIVE_TOOL = """<tool id="interactive_api_key" name="interactive_api_key" tool_type="interactive" version="1.0">
    <entry_points><entry_point name="Notebook"><port>8888</port></entry_point></entry_points>
    <environment_variables><environment_variable name="API_KEY" inject="api_key"/></environment_variables>
    <command><![CDATA[start-notebook.sh]]></command>
    <inputs/>
    <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


YAML_INTERACTIVE_TOOL = (
    "class: GalaxyTool\nid: interactive_yaml\nname: interactive_yaml\nversion: '1.0'\n"
    "tool_type: interactive\ncommand: echo $word\ninputs:\n- name: word\n  type: text\noutputs: {}\n"
)


@pytest.mark.parametrize(
    "name,contents,severity",
    [
        # capability-api-key, high.
        ("interactive.xml", INTERACTIVE_TOOL, "high"),
        # In any tool format: argument-injection, medium.
        ("interactive.yml", YAML_INTERACTIVE_TOOL, "medium"),
    ],
)
def test_interactive_tools_are_not_refused(
    tmp_path: Path, name: str, contents: str, severity: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=static_findings.__name__)
    tool = tmp_path / name
    tool.write_text(contents)
    # Reviewed as any other tool, its findings would refuse it.
    review = StaticReview.of(review_tool_source(get_tool_source(str(tool))), REVIEW_VERSION)
    assert review.refused_rules(severity)
    config = _config(severity=severity)
    # Even when a store built before the tool was left out kept that review on its index entry.
    assert with_static_review(config, get_tool_source(str(tool)), tool, kept=review).static_review is None
    assert static_review_is_current(config, None, tool, _built(tool), None)
    (said,) = _logged(caplog)
    assert str(tool) in said and "it is an interactive tool" in said


@pytest.mark.parametrize(
    "contents",
    [
        # Entry points and the API key, but no tool_type="interactive".
        INTERACTIVE_TOOL.replace(' tool_type="interactive"', ""),
        # tool_type="interactive", but the <type> element makes Galaxy build a plain Tool.
        INTERACTIVE_TOOL.replace("<entry_points>", '<type class="Tool" module="galaxy.tools"/><entry_points>', 1),
    ],
    ids=["lookalike", "type_element"],
)
def test_tools_galaxy_builds_as_ordinary_tools_are_refused(tmp_path: Path, contents: str) -> None:
    tool = tmp_path / "ordinary.xml"
    tool.write_text(contents)
    review = with_static_review(_config(), get_tool_source(str(tool)), tool).static_review
    assert review is not None and "capability-api-key" in review.refused_rules("high")
    assert static_review_is_current(_config(), review, tool, _built(tool), None)
    assert not static_review_is_current(_config(), None, tool, _built(tool), None)


def test_cwl_tools_are_not_refused() -> None:
    # The review reads a CWL tool's $__cwl_command as an unquoted command; a CWL tool has no Cheetah template.
    path = functional_test_tool_path("parameters/cwl_int.cwl")
    assert StaticReview.of(review_tool_source(get_tool_source(path)), REVIEW_VERSION).refused_rules("high")
    assert with_static_review(_config(severity="low"), get_tool_source(path), path).static_review is None
    assert static_review_is_current(_config(severity="low"), None, path, _built(path), None)


@pytest.mark.parametrize(
    "path",
    [
        # Under lib/galaxy, which the review left out before Galaxy's own tools were listed: the collection
        # operations, sample sheet tools and converters beside them, and the spec tools.
        os.path.join(TOOLS_DIR, "unzip_collection.xml"),
        os.path.join(TOOLS_DIR, "sample_sheet_to_tabular.xml"),
        os.path.join(TOOLS_DIR, os.pardir, "datatypes", "converters", "bam_to_bai.xml"),
        os.path.join(TOOLS_DIR, os.pardir, "tool_util", "security", "spec", "tools", "command_position.xml"),
    ],
    ids=os.path.basename,
)
def test_other_tools_galaxy_ships_are_reviewed(path: str) -> None:
    review = with_static_review(_config(severity="low"), get_tool_source(path), path).static_review
    assert review is not None and review.error is None
    assert static_review_is_current(_config(severity="low"), review, path, _built(path), None)
    assert not static_review_is_current(_config(severity="low"), None, path, _built(path), None)


def test_the_unsafe_test_tool_is_refused() -> None:
    # The red case of these tests and of the integration tests, whose refused job's info names exactly this rule.
    review = with_static_review(_config(), get_tool_source(TOOL), TOOL).static_review
    assert review is not None and review.refused_rules("high") == ["shell-injection"]


def test_failed_review_is_kept_and_refuses_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(tool_source):
        raise RecursionError()

    monkeypatch.setattr(static_findings, "review_tool_source", fail)
    review = with_static_review(_config(), get_tool_source(TOOL), TOOL).static_review
    assert review == StaticReview(error="RecursionError", version=REVIEW_VERSION)
    assert review.refused_rules("low") == []


def _app_config(refuse: bool, severity: str) -> GalaxyAppConfiguration:
    return GalaxyAppConfiguration(
        override_tempdir=False,
        tool_security_refuse_static_findings=refuse,
        tool_security_refuse_static_findings_severity=severity,
    )


@pytest.mark.parametrize("severity", ["High", "info"])
def test_unknown_severity_is_a_configuration_error(severity: str) -> None:
    _app_config(False, severity)
    with pytest.raises(ConfigurationError, match=f"not '{severity}'"):
        _app_config(True, severity)


def test_configurable_severities_are_the_findings_severities_but_info() -> None:
    assert STATIC_FINDINGS_SEVERITIES == tuple(reversed(SEVERITIES[1:]))
    assert SEVERITIES[0] == INFO
    schema = AppSchema(GALAXY_CONFIG_SCHEMA_PATH, GALAXY_APP_NAME)
    assert (
        tuple(schema.get_app_option("tool_security_refuse_static_findings_severity")["enum"])
        == STATIC_FINDINGS_SEVERITIES
    )


@pytest.mark.parametrize("name", ["upload.xml", "data_source/upload.xml"])
def test_upload_tool_lookalike_is_reviewed(tmp_path: Path, name: str, caplog: pytest.LogCaptureFixture) -> None:
    # The same id and action, from a path that is not Galaxy's: a Tool Shed or local copy.
    caplog.set_level(logging.WARNING, logger=static_findings.__name__)
    copy = tmp_path / name
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text(Path(GALAXY_UPLOAD_TOOL).read_text())
    review = with_static_review(_config(severity="low"), get_tool_source(str(copy)), copy).static_review
    assert review is not None and "option-injection" in review.refused_rules("low")
    assert not static_review_is_current(_config(severity="low"), None, copy, _built(copy), None)
    # Said once, naming Galaxy's own upload tool.
    warnings = [m for m in caplog.messages if "declares Galaxy's upload tool" in m]
    assert len(warnings) == 1
    assert os.path.realpath(GALAXY_UPLOAD_TOOL) in warnings[0] and str(copy) in warnings[0]


def test_patched_galaxy_upload_tool_is_reviewed(tmp_path: Path) -> None:
    # A tool patch that applies changes the template Galaxy ships: the patched source is reviewed.
    patch = security_patch(
        [replace_text_op("command", "'$paramfile'", "'$paramfile' && true")],
        "ordinary_inputs",
        "Jobs run an extra true.",
    )
    db = load_tool_patch_database([str(write_collection(tmp_path / "c", {"_local/upload1/1.1.7.yml": patch}))])
    config = _config(severity="low")
    patched = patch_and_review_tool_source(config, db, get_tool_source(GALAXY_UPLOAD_TOOL), None, GALAXY_UPLOAD_TOOL)
    assert patched.patch_state is not None and patched.static_review is not None
    assert "option-injection" in patched.static_review.refused_rules("low")
    assert not static_review_is_current(
        config, None, GALAXY_UPLOAD_TOOL, patched.parse_tool_type(), patched.patch_state
    )
    assert static_review_is_current(
        config, patched.static_review, GALAXY_UPLOAD_TOOL, patched.parse_tool_type(), patched.patch_state
    )
