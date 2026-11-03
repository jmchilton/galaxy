from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import (
    Any,
    cast,
)

import pytest
from sqlalchemy import event

from galaxy import model
from galaxy.managers.context import ProvidesHistoryContext
from galaxy.tool_util.parser import get_tool_source
from galaxy.tools import create_tool_from_source
from galaxy.workflow.step_parameter_overrides import apply_step_parameter_overrides
from .workflow_support import (
    MockTrans,
    yaml_to_model,
)

NESTED_CONDITIONAL_TOOL = """<tool id="nested_conditional" name="Nested conditional" version="1.0">
    <command>echo</command>
    <inputs>
        <param name="input1" type="data" format="txt" />
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


@dataclass
class ToolWorkflow:
    trans: MockTrans
    workflow_id: int

    def steps(self) -> list[model.WorkflowStep]:
        """The workflow's steps, freshly loaded - nothing is loaded for them but their own columns."""
        self.trans.sa_session.expunge_all()
        workflow = self.trans.sa_session.get(model.Workflow, self.workflow_id)
        assert workflow
        return list(workflow.steps)

    def step_id(self, order_index: int) -> int:
        return next(step.id for step in self.steps() if step.order_index == order_index)

    def apply(
        self, overrides: dict[str, Any], param_map: dict[int, Any], steps: list[model.WorkflowStep] | None = None
    ) -> dict[str, Any]:
        """``apply_step_parameter_overrides`` to the workflow's steps - freshly loaded, unless ``steps`` are given."""
        trans = cast(ProvidesHistoryContext, self.trans)
        return apply_step_parameter_overrides(trans, steps or self.steps(), overrides, param_map)


def _tool_workflow(tmp_path, tool_steps: int) -> ToolWorkflow:
    """A saved workflow of a data input and ``tool_steps`` steps of ``NESTED_CONDITIONAL_TOOL`` reading it."""
    trans = MockTrans()
    tool_path = tmp_path / "nested_conditional.xml"
    tool_path.write_text(NESTED_CONDITIONAL_TOOL)
    trans.app.toolbox.tools["nested_conditional"] = create_tool_from_source(
        trans.app, get_tool_source(str(tool_path)), config_file=str(tool_path)
    )
    workflow = yaml_to_model(
        {
            "steps": [{"type": "data_input", "tool_inputs": {"name": "input1"}}]
            + [
                {
                    "type": "tool",
                    "tool_id": "nested_conditional",
                    "tool_inputs": {"outer": {"mode": "a", "__current_case__": 0, "x": 1}},
                    "inputs": {"input1": {"connections": [{"@output_step": 0, "output_name": "output"}]}},
                    "workflow_outputs": [{"output_name": "out1", "label": f"out{i}"}],
                }
                for i in range(tool_steps)
            ]
        }
    )
    trans.save_workflow(workflow)
    return ToolWorkflow(trans, workflow.id)


@pytest.fixture
def one_tool_step(tmp_path) -> ToolWorkflow:
    return _tool_workflow(tmp_path, 1)


def test_switched_case_fills_nested_conditional_defaults(one_tool_step: ToolWorkflow):
    step_id = one_tool_step.step_id(1)
    overrides = {"1": {"outer": {"mode": "b"}}}
    param_map: dict[int, Any] = {}
    recorded = one_tool_step.apply(overrides, param_map)
    assert recorded == {"1": {"outer": {"mode": "b", "inner": {"kind": "k1", "p": "1"}}}}
    assert param_map == {step_id: {"outer|mode": "b", "outer|inner|kind": "k1", "outer|inner|p": "1"}}
    # The request's overrides are left as they were sent.
    assert overrides == {"1": {"outer": {"mode": "b"}}}


def test_switched_case_keeps_the_nested_case_parameters_select(one_tool_step: ToolWorkflow):
    step_id = one_tool_step.step_id(1)
    param_map: dict[int, Any] = {step_id: {"outer|mode": "a", "outer|inner|kind": "k2", "outer|inner|p": 7}}
    recorded = one_tool_step.apply({"1": {"outer": {"mode": "b"}}}, param_map)
    # The inner case legacy ``parameters`` select stays, and its defaults fill what they don't set.
    assert recorded == {"1": {"outer": {"mode": "b", "inner": {"q": "q2"}}}}
    assert param_map == {
        step_id: {"outer|mode": "b", "outer|inner|kind": "k2", "outer|inner|p": 7, "outer|inner|q": "q2"}
    }


@contextmanager
def _counting_queries(trans: MockTrans) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record(conn, cursor, statement, *args):
        statements.append(statement)

    engine = trans.sa_session.get_bind()
    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def _queries_overriding_every_tool_step(tool_workflow: ToolWorkflow) -> int:
    steps = tool_workflow.steps()
    overrides = {str(step.order_index): {"outer": {"x": 3}} for step in steps if step.type == "tool"}
    with _counting_queries(tool_workflow.trans) as statements:
        tool_workflow.apply(overrides, {}, steps)
    return len(statements)


def test_overriding_more_tool_steps_costs_no_more_queries(tmp_path):
    two_steps = _queries_overriding_every_tool_step(_tool_workflow(tmp_path, 2))
    six_steps = _queries_overriding_every_tool_step(_tool_workflow(tmp_path, 6))
    assert six_steps == two_steps
