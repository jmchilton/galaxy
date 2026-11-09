import json
from typing import (
    Any,
    cast,
    TYPE_CHECKING,
)

import pytest
from pydantic import ValidationError

from galaxy.datatypes.registry import example_datatype_registry_for_sample
from galaxy.model import (
    Dataset,
    HistoryDatasetAssociation,
    Job,
    set_datatypes_registry,
    User,
)
from galaxy.model.unittest_utils import GalaxyDataTestApp
from galaxy.tool_util.parameters import input_models_for_tool_source
from galaxy.tool_util.parameters.factory import ParameterDefinitionError
from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util_models.parameters import ReferenceDataConfig
from galaxy.tools import create_tool_from_source
from galaxy.tools.data import ToolDataTableManager
from galaxy.tools.evaluation import UserToolEvaluator
from galaxy.tools.parameters.basic import (
    ParameterValueError,
    ReferenceDataToolParameter,
    ToolParameter,
)
from galaxy.tools.runtime import setup_for_reference_data
from galaxy.util import XML
from galaxy.util.bunch import Bunch
from galaxy.work.context import WorkRequestContext
from .test_evaluation import ComputeEnvironment

if TYPE_CHECKING:
    from galaxy.tools import Tool


TABLES = """<tables>
  <table name="open_refs" user_accessible="true">
    <columns>value, dbkey, name, path</columns>
    <file path="{loc}" />
  </table>
  <table name="closed_refs">
    <columns>value, dbkey, name, path</columns>
    <file path="{loc}" />
  </table>
  <table name="no_paths" user_accessible="true">
    <columns>value, name</columns>
    <file path="{names_loc}" />
  </table>
</tables>
"""

HG38_INPUT = {
    "class": "ReferenceData",
    "path": "/refs/hg38/hg38.fa",
    "basename": "hg38.fa",
    "nameroot": "hg38",
    "nameext": ".fa",
    "source": {"table": "open_refs", "value": "hg38"},
    "metadata": {"dbkey": "hg38", "name": "Human"},
}
MM10_INPUT = {
    "class": "ReferenceData",
    "path": "/refs/mm10/mm10.fa",
    "basename": "mm10.fa",
    "nameroot": "mm10",
    "nameext": ".fa",
    "source": {"table": "open_refs", "value": "mm10"},
    "metadata": {"dbkey": "mm10", "name": "Mouse"},
}


class ToolApp(GalaxyDataTestApp):
    tool_data_tables: ToolDataTableManager
    name = "galaxy"
    biotools_metadata_source = None
    job_search = None
    is_webapp = True


@pytest.fixture
def app(tmp_path):
    loc = tmp_path / "refs.loc"
    loc.write_text("hg38\thg38\tHuman\t/refs/hg38/hg38.fa\nmm10\tmm10\tMouse\t/refs/mm10/mm10.fa\n")
    names_loc = tmp_path / "names.loc"
    names_loc.write_text("a\tAlpha\n")
    config = tmp_path / "tables.xml"
    config.write_text(TABLES.format(loc=loc, names_loc=names_loc))
    app = ToolApp()
    app.tool_data_tables = ToolDataTableManager(tmp_path, str(config))
    return app


def _tool(app, tool_class="GalaxyUserTool", **input_fields) -> "Tool":
    inputs: list[dict[str, Any]] = [
        {"name": "reference", "type": "reference_data", "table": "open_refs", **input_fields}
    ]
    if "filter" in input_fields:
        inputs.insert(0, {"name": "reads", "type": "data", "format": "txt"})
    source = {
        "class": tool_class,
        "id": "reference_tool",
        "version": "1.0",
        "name": "reference_tool",
        "container": "busybox",
        "shell_command": "echo $(inputs.reference.path)",
        "inputs": inputs,
        "outputs": [],
    }
    tool_source = get_tool_source(tool_source_class="YamlToolSource", raw_tool_source=json.dumps(source))
    return create_tool_from_source(app, tool_source=tool_source)


def _parameter(tool) -> ReferenceDataToolParameter:
    return cast(ReferenceDataToolParameter, tool.inputs["reference"])


def _values(app, tool, other_values=None):
    trans = WorkRequestContext(app=app)
    return [option.value for option in _parameter(tool).get_options(trans, other_values or {})]


def _hda_with_dbkey(dbkey: str) -> HistoryDatasetAssociation:
    set_datatypes_registry(example_datatype_registry_for_sample())
    hda = HistoryDatasetAssociation(create_dataset=True, flush=False, name="reads", extension="txt")
    assert hda.dataset is not None
    hda.dataset.state = Dataset.states.OK
    hda.metadata.dbkey = dbkey
    return hda


def _job(value, validated_state: bool = False) -> Job:
    job = Job()
    job.add_parameter("reference", json.dumps(value))
    if validated_state:
        job.tool_state = {"reference": value}
    return job


def _evaluated_reference(app, tool, job, tmp_path, unstructured_path_rewrites=None):
    evaluator = UserToolEvaluator(app, tool, job, str(tmp_path))
    compute_environment = ComputeEnvironment(
        str(tmp_path), str(tmp_path), unstructured_path_rewrites=unstructured_path_rewrites
    )
    evaluator.set_compute_environment(cast(Any, compute_environment))
    return evaluator.param_dict["inputs"]["reference"]


def test_renders_as_a_select_offering_the_table_entries(app):
    as_dict = _parameter(_tool(app)).to_dict(WorkRequestContext(app=app))
    assert as_dict["type"] == "select"
    assert [option[1] for option in as_dict["options"]] == ["hg38", "mm10"]
    assert "/refs" not in json.dumps(as_dict)


def test_user_tool_is_offered_nothing_from_a_table_admins_have_not_opened(app):
    assert _values(app, _tool(app, table="closed_refs")) == []


def test_admin_installed_tool_can_read_any_table(app):
    assert _values(app, _tool(app, tool_class="GalaxyTool", table="closed_refs")) == ["hg38", "mm10"]


def test_user_tool_cannot_submit_a_value_from_a_closed_table(app):
    with pytest.raises(ParameterValueError):
        _parameter(_tool(app, table="closed_refs")).from_json("hg38", WorkRequestContext(app=app), {})


def test_history_bundles_are_not_offered_as_table_entries(app, monkeypatch):
    parameter = _parameter(_tool(app))
    # User bundles append the HDA after the configured table columns.
    bundle = ["bundle", "hg38", "Bundle", "/bundle/hg38.fa", HistoryDatasetAssociation(id=1)]
    monkeypatch.setattr(parameter.options, "get_user_options", lambda user: [bundle])
    options = parameter.get_options(WorkRequestContext(app=app, user=User()), {})
    assert [option.value for option in options] == ["hg38", "mm10"]


@pytest.mark.parametrize(
    "param_xml",
    [
        '<param name="reference" type="reference_data" table="open_refs"/>',
        '<param name="reference" type="reference_data" table="closed_refs"><options from_data_table="open_refs"/></param>',
    ],
    ids=["bare", "with_options"],
)
def test_xml_tools_cannot_declare_reference_data(app, param_xml):
    tool = cast("Tool", Bunch(app=app, profile=26.1))
    with pytest.raises(ParameterValueError, match="only supported in YAML tools"):
        ToolParameter.build(tool, XML(param_xml))


def test_parameter_models_reject_xml_reference_data():
    tool_source = get_tool_source(
        tool_source_class="XmlToolSource",
        raw_tool_source=(
            '<tool id="x" name="x" version="1"><command>x</command><inputs>'
            '<param name="reference" type="reference_data" table="open_refs"/></inputs></tool>'
        ),
    )
    with pytest.raises(ParameterDefinitionError, match="only supported in YAML tools"):
        input_models_for_tool_source(tool_source)


def test_filter_offers_only_entries_matching_the_selected_dataset(app):
    tool = _tool(app, filter={"from_input": "reads", "on_metadata": "dbkey"})
    assert _parameter(tool).get_dependencies() == ["reads"]
    assert _values(app, tool, {"reads": _hda_with_dbkey("mm10")}) == ["mm10"]


def test_table_this_instance_does_not_have_offers_nothing(app):
    tool = _tool(app, table="not_installed", filter={"from_input": "reads", "on_metadata": "dbkey"})
    assert _values(app, tool) == []


@pytest.mark.parametrize(
    "filter_def",
    [{"from_input": "reads"}, {"from_input": "reads", "on_metadata": "dbkey", "type": "regexp"}],
    ids=["missing_on_metadata", "extra_key"],
)
def test_malformed_filter_is_rejected_when_loading(app, filter_def):
    with pytest.raises(ValidationError):
        _tool(app, filter=filter_def)


def test_filter_on_a_missing_column_is_rejected_when_loading(app):
    with pytest.raises(ParameterValueError, match="no 'dbkey' column"):
        _tool(app, table="no_paths", filter={"from_input": "reads", "on_metadata": "dbkey"})


@pytest.mark.parametrize("validated_state", [False, True], ids=["job_parameters", "validated_state"])
@pytest.mark.parametrize(
    "value, multiple, expected_input",
    [
        ("hg38", False, HG38_INPUT),
        (["hg38", "mm10"], True, [HG38_INPUT, MM10_INPUT]),
    ],
    ids=["single", "multiple"],
)
def test_job_receives_the_entries(app, tmp_path, validated_state, value, multiple, expected_input):
    tool = _tool(app, multiple=multiple)
    assert _evaluated_reference(app, tool, _job(value, validated_state), tmp_path) == expected_input


@pytest.mark.parametrize(
    "value, multiple, validated_state",
    [(None, False, False), ([], True, False), (None, False, True), (None, True, True)],
    ids=["single-job_parameters", "multiple-job_parameters", "single-validated_state", "multiple-validated_state"],
)
def test_optional_input_with_nothing_selected_stays_empty(app, tmp_path, value, multiple, validated_state):
    tool = _tool(app, multiple=multiple, optional=True)
    assert _evaluated_reference(app, tool, _job(value, validated_state), tmp_path) == value


def test_path_is_rewritten_for_the_job(app, tmp_path):
    rewrites = {"/refs/hg38/hg38.fa": "/remote/hg38.fa"}
    assert _evaluated_reference(app, _tool(app), _job("hg38"), tmp_path, rewrites)["path"] == "/remote/hg38.fa"


def test_entry_of_a_table_without_paths_has_only_metadata(app, tmp_path):
    reference = _evaluated_reference(app, _tool(app, table="no_paths"), _job("a"), tmp_path)
    assert reference["path"] is None
    assert reference["metadata"] == {"name": "Alpha"}


@pytest.mark.parametrize("validated_state", [False, True], ids=["job_parameters", "validated_state"])
def test_job_fails_when_admins_close_the_table_after_it_was_submitted(app, tmp_path, validated_state):
    tool = _tool(app)
    job = _job("hg38", validated_state)
    app.tool_data_tables["open_refs"].user_accessible = False
    with pytest.raises(ParameterValueError, match="no legal values"):
        _evaluated_reference(app, tool, job, tmp_path)


@pytest.mark.parametrize(
    "table, value, message",
    [
        ("closed_refs", "hg38", "not available to user-defined tools"),
        ("not_installed", "hg38", "not configured"),
        ("open_refs", "removed", "no entry with value removed"),
    ],
)
def test_resolving_a_path_enforces_the_allowlist_and_the_entry(app, table, value, message):
    adapt = setup_for_reference_data(app, None, trusted=False)
    with pytest.raises(ValueError, match=message):
        adapt(ReferenceDataConfig(table=table), value)
