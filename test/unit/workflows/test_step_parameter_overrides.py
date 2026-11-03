from sqlalchemy import event

from galaxy import model
from galaxy.app_unittest_utils.tools_support import UsesTools
from galaxy.util.bunch import Bunch
from galaxy.workflow.step_parameter_overrides import (
    _load_tool_step_relationships,
    _ToolStateWalker,
    flatten_tool_state,
)
from .workflow_support import (
    MockTrans,
    yaml_to_model,
)

NESTED_CONDITIONAL_TOOL = """<tool id="nested_conditional" name="Nested conditional" version="1.0">
    <command>echo</command>
    <inputs>
        <conditional name="outer">
            <param name="mode" type="select">
                <option value="a" selected="true">A</option>
                <option value="b">B</option>
            </param>
            <when value="a">
                <param name="x" type="integer" value="1" />
            </when>
            <when value="b">
                <conditional name="inner">
                    <param name="kind" type="select">
                        <option value="k1" selected="true">K1</option>
                        <option value="k2">K2</option>
                    </param>
                    <when value="k1">
                        <param name="p" type="integer" value="1" />
                    </when>
                    <when value="k2">
                        <param name="p" type="integer" value="2" />
                        <param name="q" type="text" value="q2" />
                    </when>
                </conditional>
            </when>
        </conditional>
    </inputs>
    <outputs>
        <data name="out1" format="txt" />
    </outputs>
</tool>
"""
SAVED_CASE_A = {"outer": {"mode": "a", "__current_case__": 0, "x": 1}}


class TestSwitchedConditionalCaseDefaults(UsesTools):
    def setup_method(self):
        self.setup_app()
        self.tool = self._init_tool(NESTED_CONDITIONAL_TOOL)
        self.trans = Bunch(app=self.app, user=None, history=None, workflow_building_mode=False)

    def teardown_method(self):
        self.tear_down_app()

    def _walk(self, overrides, pending):
        walker = _ToolStateWalker(self.trans, set(), pending)
        return walker.visit(self.tool.inputs, SAVED_CASE_A, overrides, "", ["1"])

    def test_switched_case_fills_nested_conditional_defaults(self):
        overrides = {"outer": {"mode": "b"}}
        normalized = self._walk(overrides, {})
        assert normalized == {"outer": {"mode": "b", "inner": {"kind": "k1", "p": "1"}}}
        assert flatten_tool_state(normalized) == {"outer|mode": "b", "outer|inner|kind": "k1", "outer|inner|p": "1"}
        # The request's overrides are left as they were sent.
        assert overrides == {"outer": {"mode": "b"}}

    def test_switched_case_keeps_nested_conditional_case_parameters_select(self):
        pending = {"outer|mode": "a", "outer|inner|kind": "k2", "outer|inner|p": 7}
        # The case ``parameters`` select for the inner conditional stays, and its defaults fill what they don't set.
        normalized = self._walk({"outer": {"mode": "b"}}, pending)
        assert normalized == {"outer": {"mode": "b", "inner": {"q": "q2"}}}
        assert flatten_tool_state(normalized) == {"outer|mode": "b", "outer|inner|q": "q2"}


TOOL_STEPS = 5

WORKFLOW_YAML = {
    "steps": [{"type": "data_input", "tool_inputs": {"name": "input1"}}]
    + [
        {
            "type": "tool",
            "tool_id": "cat1",
            "inputs": {"input1": {"connections": [{"@output_step": 0, "output_name": "output"}]}},
            "workflow_outputs": [{"output_name": "out_file1", "label": f"out{i}"}],
        }
        for i in range(TOOL_STEPS)
    ]
}


def _reloaded_tool_steps(trans: MockTrans, workflow_id: int) -> list[model.WorkflowStep]:
    trans.sa_session.expunge_all()
    reloaded = trans.sa_session.get(model.Workflow, workflow_id)
    assert reloaded
    return [step for step in reloaded.steps if step.type == "tool"]


def _queries_reading_relationships(trans: MockTrans, steps: list[model.WorkflowStep]) -> int:
    count = 0

    def _count(*args):
        nonlocal count
        count += 1

    engine = trans.sa_session.get_bind()
    event.listen(engine, "before_cursor_execute", _count)
    try:
        for step in steps:
            assert [connection.input_name for connection in step.input_connections] == ["input1"]
            assert len(step.workflow_outputs) == 1
            assert step.post_job_actions == []
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    return count


def test_load_tool_step_relationships_loads_them_for_all_steps_at_once():
    trans = MockTrans()
    workflow = yaml_to_model(WORKFLOW_YAML)
    trans.save_workflow(workflow)
    workflow_id = workflow.id
    # Read one by one, each step's connections, outputs and post-job actions cost a query or more.
    assert _queries_reading_relationships(trans, _reloaded_tool_steps(trans, workflow_id)) >= 3 * TOOL_STEPS
    steps = _reloaded_tool_steps(trans, workflow_id)
    _load_tool_step_relationships(trans, steps)
    assert _queries_reading_relationships(trans, steps) == 0
