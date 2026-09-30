from typing import cast

import pytest

from galaxy.exceptions.utils import api_error_to_dict
from galaxy.managers.context import ProvidesUserContext
from galaxy.schema.schema import UnmetPrecondition
from galaxy.tools import Tool
from galaxy.tools.actions import DefaultToolAction
from galaxy.tools.actions.data_manager import DataManagerToolAction
from galaxy.tools.actions.data_source import DataSourceToolAction
from galaxy.tools.actions.model_operations import ModelOperationToolAction
from galaxy.tools.preconditions import (
    check_preconditions,
    TOOL_ACCESS_PRECONDITION,
    ToolExecutionContext,
    ToolExecutionPrecondition,
    ToolExecutionPreconditionUnmet,
)


class StubTool:
    id = "stub_tool"

    def __init__(self, accessible: bool = True, require_login: bool = False):
        self.accessible = accessible
        self.require_login = require_login

    def allow_user_access(self, user, attempting_access: bool = True) -> bool:
        return self.accessible


class StubTrans:
    user = None


class AlwaysUnmet(ToolExecutionPrecondition):
    def __init__(self, message: str, short_circuit: bool = False):
        self.message = message
        self.short_circuit = short_circuit

    def unmet(self, trans, tool, context):
        return UnmetPrecondition(kind="access", message=self.message)


class AlwaysMet(ToolExecutionPrecondition):
    def unmet(self, trans, tool, context):
        return None


def _check(preconditions, tool=None):
    check_preconditions(cast(ProvidesUserContext, StubTrans()), cast(Tool, tool or StubTool()), preconditions)


def test_all_met_does_not_raise():
    _check([AlwaysMet(), AlwaysMet()])


def test_collects_every_unmet_precondition():
    with pytest.raises(ToolExecutionPreconditionUnmet) as exc_info:
        _check([AlwaysUnmet("first"), AlwaysMet(), AlwaysUnmet("second")])
    assert [u.message for u in exc_info.value.unmet] == ["first", "second"]
    assert exc_info.value.err_msg == "first; second"


def test_short_circuit_skips_remaining_preconditions():
    with pytest.raises(ToolExecutionPreconditionUnmet) as exc_info:
        _check([AlwaysUnmet("gate", short_circuit=True), AlwaysUnmet("hidden")])
    assert [u.message for u in exc_info.value.unmet] == ["gate"]


def test_access_unmet_for_inaccessible_logged_out_tool_without_require_login():
    unmet = TOOL_ACCESS_PRECONDITION.unmet(
        cast(ProvidesUserContext, StubTrans()), cast(Tool, StubTool(accessible=False)), ToolExecutionContext()
    )
    assert unmet is not None
    assert unmet.message == "Tool 'stub_tool' is not accessible."
    assert unmet.remedy_route is None


def test_access_met_for_accessible_tool():
    assert (
        TOOL_ACCESS_PRECONDITION.unmet(
            cast(ProvidesUserContext, StubTrans()), cast(Tool, StubTool()), ToolExecutionContext()
        )
        is None
    )


def test_api_error_dict_includes_unmet():
    exception = ToolExecutionPreconditionUnmet(
        [
            UnmetPrecondition(
                kind="access", message="nope", details={"tool_id": "stub_tool"}, remedy_route="/login/start"
            )
        ]
    )
    error_dict = api_error_to_dict(exception=exception)
    assert error_dict["err_code"] == 403009
    assert error_dict["unmet"] == [
        {"kind": "access", "message": "nope", "details": {"tool_id": "stub_tool"}, "remedy_route": "/login/start"}
    ]


def test_action_subclass_replacing_execute_does_not_check_preconditions():
    class ReplacesExecute(DefaultToolAction):
        def execute(self, *args, **kwargs):
            raise NotImplementedError()

    class DefersExecute(DefaultToolAction):
        pass

    assert DefaultToolAction.checks_preconditions
    assert DefersExecute.checks_preconditions
    assert not ReplacesExecute.checks_preconditions
    assert DataManagerToolAction.checks_preconditions
    assert DataSourceToolAction.checks_preconditions
    assert not ModelOperationToolAction.checks_preconditions
