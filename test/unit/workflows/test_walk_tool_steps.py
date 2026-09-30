from galaxy import model


def _step(order_index: int, type: str = "tool", subworkflow: model.Workflow | None = None) -> model.WorkflowStep:
    step = model.WorkflowStep()
    step.order_index = order_index
    step.type = type
    step.tool_id = f"tool_{order_index}" if type == "tool" else None
    step.subworkflow = subworkflow
    return step


def _workflow(*steps: model.WorkflowStep) -> model.Workflow:
    workflow = model.Workflow()
    workflow.steps = list(steps)
    return workflow


def _paths(workflow: model.Workflow) -> list[tuple[int, ...]]:
    return [path for path, _ in workflow.walk_tool_steps()]


def test_walk_tool_steps_skips_non_tool_steps():
    workflow = _workflow(_step(0, type="data_input"), _step(1), _step(2, type="pause"), _step(3))
    assert _paths(workflow) == [(1,), (3,)]


def test_walk_tool_steps_recurses_into_subworkflows():
    inner = _workflow(_step(0), _step(1))
    workflow = _workflow(_step(0), _step(1, type="subworkflow", subworkflow=inner))
    walked = list(workflow.walk_tool_steps())
    assert [path for path, _ in walked] == [(0,), (1, 0), (1, 1)]
    assert walked[1][1] is inner.steps[0]


def test_walk_tool_steps_reports_every_occurrence_of_a_shared_subworkflow():
    inner = _workflow(_step(0))
    workflow = _workflow(
        _step(0, type="subworkflow", subworkflow=inner),
        _step(1, type="subworkflow", subworkflow=inner),
    )
    assert _paths(workflow) == [(0, 0), (1, 0)]


def test_walk_tool_steps_stops_on_recursive_subworkflows():
    workflow = _workflow(_step(0))
    workflow.steps.append(_step(1, type="subworkflow", subworkflow=workflow))
    assert _paths(workflow) == [(0,)]
