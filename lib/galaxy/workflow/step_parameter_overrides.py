"""Validate and translate the ``step_parameter_overrides`` of a workflow invocation request.

Overrides are keyed by step ``order_index``. A tool step takes nested tool state - objects for
sections and conditionals, lists for repeats - and a subworkflow step takes the inner workflow's
overrides in the same shape. They translate into the per-step parameter map legacy ``parameters``
produce (flat ``a|b`` names keyed by step id, nested by inner step id for subworkflows), so
scheduling applies both the same way.
"""

import json
from typing import (
    Any,
    TYPE_CHECKING,
)

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from galaxy.exceptions import RequestParameterInvalidException
from galaxy.model import (
    WorkflowRequestInputParameter,
    WorkflowStep,
    WorkflowStepInput,
)
from galaxy.tools.parameters import ToolInputsT
from galaxy.tools.parameters.basic import (
    BaseDataToolParameter,
    ToolParameter,
)
from galaxy.tools.parameters.grouping import (
    Conditional,
    Repeat,
    Section,
)
from galaxy.workflow.modules import (
    module_factory,
    ToolModule,
)

if TYPE_CHECKING:
    from galaxy.managers.context import ProvidesHistoryContext
    from galaxy.model import WorkflowInvocation

StepParameterOverrides = dict[str, Any]
# Name of the meta request parameter the overrides are recorded as.
STEP_PARAMETER_OVERRIDES_PARAMETER = "step_parameter_overrides"


def _invalid(path: list[str], reason: str) -> RequestParameterInvalidException:
    location = "/".join(path)
    return RequestParameterInvalidException(
        f"Invalid step_parameter_overrides entry '{location}': {reason}", err_data={location: reason}
    )


def apply_step_parameter_overrides(
    trans: "ProvidesHistoryContext",
    steps: list["WorkflowStep"],
    overrides: StepParameterOverrides,
    param_map: dict[int, Any],
) -> StepParameterOverrides:
    """Validate ``overrides`` against ``steps`` and merge them into ``param_map`` (keyed by step id).

    Returns the overrides to record with the request: a copy of ``overrides`` that also sets the
    defaults of conditional cases they switch to. Each tool step's part of it is what
    ``flatten_tool_state`` merges into ``param_map``.

    Raises ``RequestParameterInvalidException`` for anything that isn't a tool parameter value the
    steps' saved state can take.
    """
    return _apply(trans, steps, overrides, param_map, [])


def _apply(
    trans: "ProvidesHistoryContext",
    steps: list["WorkflowStep"],
    overrides: Any,
    param_map: dict[int, Any],
    path: list[str],
) -> StepParameterOverrides:
    if not isinstance(overrides, dict):
        raise _invalid(path, "must be an object keyed by step index")
    steps_by_index = {str(step.order_index): step for step in steps}
    _load_tool_step_relationships(
        trans, [step for index in overrides if (step := steps_by_index.get(index)) and step.type == "tool"]
    )
    normalized: StepParameterOverrides = {}
    for index, step_overrides in overrides.items():
        step_path = [*path, index]
        step = steps_by_index.get(index)
        if step is None:
            raise _invalid(step_path, "no step with this index")
        if not isinstance(step_overrides, dict):
            raise _invalid(step_path, "must be an object")
        existing = param_map.get(step.id) or {}
        if step.type == "tool":
            normalized[index] = _tool_step_overrides(trans, step, step_overrides, existing, step_path)
            if flat := flatten_tool_state(normalized[index]):
                param_map[step.id] = {**existing, **flat}
        elif step.type == "subworkflow":
            assert step.subworkflow
            inner = dict(existing)
            normalized[index] = _apply(trans, step.subworkflow.steps, step_overrides, inner, step_path)
            if inner:
                param_map[step.id] = inner
        else:
            raise _invalid(step_path, f"a {step.type} step takes no parameter overrides, set it in 'inputs'")
    return normalized


def _load_tool_step_relationships(trans: "ProvidesHistoryContext", steps: list["WorkflowStep"]) -> None:
    """Load what building ``steps``' modules and finding their connected inputs reads, for all of them at once.

    Otherwise each step lazy-loads its inputs, their connections, its workflow outputs and its post-job actions.
    """
    if len(steps) < 2:
        return
    trans.sa_session.scalars(
        select(WorkflowStep)
        .where(WorkflowStep.id.in_([step.id for step in steps]))
        .options(
            selectinload(WorkflowStep.inputs).selectinload(WorkflowStepInput.connections),
            selectinload(WorkflowStep.workflow_outputs),
            selectinload(WorkflowStep.post_job_actions),
        )
    ).all()


def _tool_step_overrides(
    trans: "ProvidesHistoryContext",
    step: "WorkflowStep",
    overrides: dict[str, Any],
    pending: dict[str, Any],
    path: list[str],
) -> dict[str, Any]:
    module = module_factory.from_workflow_step(trans, step)
    if not isinstance(module, ToolModule) or not module.tool:
        raise _invalid(path, f"tool '{step.tool_id}' is not installed")
    walker = _ToolStateWalker(trans, {connection.input_name for connection in step.input_connections}, pending)
    return walker.visit(module.tool.inputs, module.state.inputs, overrides, "", path)


def _case_inputs(input: Conditional, case_index: int) -> ToolInputsT:
    inputs: ToolInputsT = input.cases[case_index].inputs or {}
    return inputs


class _ToolStateWalker:
    """Validate a tool step's nested overrides against the tool's inputs and the step's saved state.

    Each method returns the overrides it validated, with the defaults of any conditional case they switch to.
    ``prefix`` is the flat ``a|b`` name prefix of the inputs being walked.
    """

    def __init__(self, trans: "ProvidesHistoryContext", connected: set[str], pending: dict[str, Any]):
        self.trans = trans
        # Flat names of the inputs connected to other steps' outputs.
        self.connected = connected
        # Flat values ``parameters`` already set for this step - they may switch a conditional's case.
        self.pending = pending

    def visit(
        self, inputs: ToolInputsT, saved: dict[str, Any], overrides: dict[str, Any], prefix: str, path: list[str]
    ) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for name, value in overrides.items():
            value_path = [*path, name]
            if name.startswith("__"):
                raise _invalid(value_path, "not a tool parameter, post-job actions and internal keys can't be set")
            input = inputs.get(name)
            if input is None:
                raise _invalid(value_path, "unknown parameter")
            flat_name = f"{prefix}{name}"
            if isinstance(input, Repeat):
                if instances := self._repeat(input, saved.get(name) or [], value, flat_name, value_path):
                    normalized[name] = instances
            elif isinstance(input, Section):
                if not isinstance(value, dict):
                    raise _invalid(value_path, "a section takes an object")
                normalized[name] = self.visit(input.inputs, saved.get(name) or {}, value, f"{flat_name}|", value_path)
            elif isinstance(input, Conditional):
                normalized[name] = self._conditional(input, saved.get(name) or {}, value, flat_name, value_path)
            elif isinstance(input, ToolParameter):
                normalized[name] = self._leaf(input, value, flat_name, value_path)
            else:
                raise _invalid(value_path, f"{type(input).__name__} parameters can't be overridden")
        return normalized

    def _repeat(
        self, input: Repeat, instances: list[dict[str, Any]], value: Any, flat_name: str, path: list[str]
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise _invalid(path, "a repeat takes a list of objects, one per instance")
        if len(value) > len(instances):
            raise _invalid(
                path, f"the step has {len(instances)} instance(s) of this repeat, overrides can't add instances"
            )
        normalized = []
        for i, instance_overrides in enumerate(value):
            if not isinstance(instance_overrides, dict):
                raise _invalid([*path, str(i)], "a repeat instance takes an object")
            normalized.append(
                self.visit(input.inputs, instances[i], instance_overrides, f"{flat_name}_{i}|", [*path, str(i)])
            )
        return normalized

    def _conditional(
        self, input: Conditional, saved: dict[str, Any], value: Any, flat_name: str, path: list[str]
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise _invalid(path, "a conditional takes an object")
        test_param = input.test_param
        assert test_param
        test_name = test_param.name
        prefix = f"{flat_name}|"
        saved_case = saved.get("__current_case__")
        if test_name in value:
            self._leaf(test_param, value[test_name], f"{prefix}{test_name}", [*path, test_name])
            case_index = self._case_for(input, value[test_name], [*path, test_name])
            if case_index != saved_case:
                # The step has no saved values for the new case - its parameters start at their defaults.
                value = self._with_defaults(_case_inputs(input, case_index), value, prefix, path)
        elif f"{prefix}{test_name}" in self.pending:
            case_index = self._case_for(input, self.pending[f"{prefix}{test_name}"], [*path, test_name])
        elif saved_case is not None:
            case_index = saved_case
        else:
            case_index = self._case_for(input, saved.get(test_name), [*path, test_name])
        case_inputs = _case_inputs(input, case_index)
        case_overrides = {name: case_value for name, case_value in value.items() if name != test_name}
        for name in case_overrides:
            if name not in case_inputs and any(name in (case.inputs or {}) for case in input.cases):
                raise _invalid(
                    [*path, name],
                    f"not in the active case '{input.cases[case_index].value}' of this conditional, "
                    f"set '{test_name}' to switch cases",
                )
        case_saved = saved if case_index == saved_case else {}
        normalized = self.visit(case_inputs, case_saved, case_overrides, prefix, path)
        if test_name in value:
            normalized = {test_name: value[test_name], **normalized}
        return normalized

    def _with_defaults(
        self, inputs: ToolInputsT, value: dict[str, Any], prefix: str, path: list[str]
    ) -> dict[str, Any]:
        """``value`` with defaults for the ``inputs`` neither it nor the ``parameters`` set, recursing into groups.

        Repeats are skipped - they start with no instances to override.
        """
        filled = dict(value)
        for name, input in inputs.items():
            flat_name = f"{prefix}{name}"
            if isinstance(input, Repeat) or isinstance(input, BaseDataToolParameter) or flat_name in self.connected:
                continue
            if isinstance(input, Section):
                section = filled.get(name, {})
                if isinstance(section, dict):
                    filled[name] = self._with_defaults(input.inputs, section, f"{flat_name}|", [*path, name])
            elif isinstance(input, Conditional):
                conditional = filled.get(name, {})
                if not isinstance(conditional, dict):
                    continue
                test_param = input.test_param
                assert test_param
                if test_param.name in conditional:
                    test_value = conditional[test_param.name]
                elif (pending_test_name := f"{flat_name}|{test_param.name}") in self.pending:
                    # The ``parameters`` select this case - keep it, as for any other parameter they set.
                    test_value = self.pending[pending_test_name]
                else:
                    test_value = self._default(test_param)
                    conditional = {test_param.name: test_value, **conditional}
                case_index = self._case_for(input, test_value, [*path, name, test_param.name])
                filled[name] = self._with_defaults(
                    _case_inputs(input, case_index), conditional, f"{flat_name}|", [*path, name]
                )
            elif isinstance(input, ToolParameter) and name not in filled and flat_name not in self.pending:
                filled[name] = self._default(input)
        return filled

    def _default(self, input: ToolParameter) -> Any:
        return input.value_to_basic(input.get_initial_value(self.trans, {}), self.trans.app)

    def _case_for(self, input: Conditional, test_value: Any, path: list[str]) -> int:
        test_param = input.test_param
        assert test_param
        try:
            case_index: int = input.get_current_case(test_param.from_json(test_value, self.trans, {}))
            return case_index
        except (ValueError, KeyError):
            raise _invalid(path, f"'{test_value}' selects no case of this conditional")

    def _leaf(self, input: ToolParameter, value: Any, flat_name: str, path: list[str]) -> Any:
        if isinstance(input, BaseDataToolParameter):
            raise _invalid(path, "data and collection parameters are set through workflow 'inputs'")
        if flat_name in self.connected:
            raise _invalid(path, "this parameter is connected to another step's output")
        if isinstance(value, dict):
            if value.get("__class__") == "Batch" or "batch" in value:
                raise _invalid(path, "batch values are not supported")
            raise _invalid(path, "takes a parameter value, not an object")
        if isinstance(value, list) and any(isinstance(item, (dict, list)) for item in value):
            raise _invalid(path, "takes a parameter value or a list of values")
        return value


def recorded_step_parameter_overrides(invocation: "WorkflowInvocation") -> StepParameterOverrides | None:
    """The step parameter overrides recorded with ``invocation``'s request, if any."""
    for parameter in invocation.input_parameters:
        if (
            parameter.type == WorkflowRequestInputParameter.types.META_PARAMETERS
            and parameter.name == STEP_PARAMETER_OVERRIDES_PARAMETER
            and parameter.value
        ):
            overrides: StepParameterOverrides = json.loads(parameter.value)
            return overrides
    return None


def request_parameters_without_step_parameter_overrides(
    invocation: "WorkflowInvocation", overrides: StepParameterOverrides | None
) -> list[WorkflowRequestInputParameter]:
    """``invocation``'s request parameters, with the values ``overrides`` set left out of its step parameter rows.

    Recorded overrides are merged into the step parameter rows too, because scheduling reads them from
    there. Rows are compared as stored - keyed by step id, nested by inner step id for subworkflow steps -
    before anything re-keys them for a request. A row with values left is returned as a copy, detached from
    the invocation's parameters, and a row with none is dropped. Rows that don't parse are returned as they
    are, for the caller to report.
    """
    parameters = list(invocation.input_parameters)
    if not overrides:
        return parameters
    stored_overrides = stored_step_parameter_overrides(invocation.workflow.steps, overrides)
    remaining: list[WorkflowRequestInputParameter] = []
    for parameter in parameters:
        step_overrides = None
        if parameter.type == WorkflowRequestInputParameter.types.STEP_PARAMETERS and parameter.name is not None:
            step_overrides = stored_overrides.get(parameter.name)
        try:
            step_parameters = json.loads(parameter.value) if step_overrides and parameter.value else None
        except ValueError:
            step_parameters = None
        if not step_overrides or not isinstance(step_parameters, dict):
            remaining.append(parameter)
            continue
        if kept := _without_overrides(step_parameters, step_overrides):
            kept_parameter = WorkflowRequestInputParameter(
                name=parameter.name, value=json.dumps(kept), type=parameter.type
            )
            # Set without the relationship's backref, which would add the copy to the invocation's parameters.
            set_committed_value(kept_parameter, "workflow_invocation", parameter.workflow_invocation)
            remaining.append(kept_parameter)
    return remaining


def stored_step_parameter_overrides(steps: list["WorkflowStep"], overrides: StepParameterOverrides) -> dict[str, Any]:
    """Flatten validated ``overrides`` to the form step parameter rows store, keyed by step id.

    A tool step's overrides flatten as ``flatten_tool_state`` does, and a subworkflow step's nest by
    inner step id. Keys are strings, as in the stored JSON. Overrides naming steps not in ``steps``
    are skipped.
    """
    steps_by_index = {str(step.order_index): step for step in steps}
    stored: dict[str, Any] = {}
    for index, step_overrides in overrides.items():
        step = steps_by_index.get(index)
        if step is None or not isinstance(step_overrides, dict):
            continue
        if step.type == "subworkflow" and step.subworkflow:
            flat = stored_step_parameter_overrides(step.subworkflow.steps, step_overrides)
        else:
            flat = flatten_tool_state(step_overrides)
        if flat:
            stored[str(step.id)] = flat
    return stored


def _without_overrides(step_parameters: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """``step_parameters`` without the values ``overrides`` (in the same stored form) set to the same value.

    Recurses into subworkflow parameters, nested by inner step id - flattened tool state values are
    never objects.
    """
    kept: dict[str, Any] = {}
    for name, value in step_parameters.items():
        if name not in overrides:
            kept[name] = value
        elif isinstance(value, dict) and isinstance(overrides[name], dict):
            if inner := _without_overrides(value, overrides[name]):
                kept[name] = inner
        elif overrides[name] != value:
            kept[name] = value
    return kept


def flatten_tool_state(state: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested tool state to ``a|b`` names, with ``name_<i>|`` for each repeat instance.

    A list of objects is a repeat; any other list is a multiple-value parameter's value.

    >>> flatten_tool_state({"a": 1, "s": {"b": 2}, "r": [{}, {"c": 3}], "m": ["x", "y"]})
    {'a': 1, 's|b': 2, 'r_1|c': 3, 'm': ['x', 'y']}
    """
    flat: dict[str, Any] = {}
    for name, value in state.items():
        if isinstance(value, dict):
            flat.update(flatten_tool_state(value, f"{prefix}{name}|"))
        elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            for i, instance in enumerate(value):
                flat.update(flatten_tool_state(instance, f"{prefix}{name}_{i}|"))
        else:
            flat[f"{prefix}{name}"] = value
    return flat
