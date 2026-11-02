from unittest.mock import Mock
from uuid import uuid4

import pytest

from galaxy import model
from galaxy.exceptions import (
    ObjectNotFound,
    ToolMissingException,
)
from galaxy.jobs.handler import JobHandlerQueue


@pytest.mark.parametrize(
    "error",
    [
        ToolMissingException("Tool definition cannot be loaded."),
        ObjectNotFound("Failed to find a tool with uuid"),
    ],
)
def test_job_with_unavailable_user_tool_fails_at_startup(error, caplog):
    job = model.Job()
    job.id = 1
    job.tool_id = "user_tool"
    job.dynamic_tool = model.DynamicTool(tool_format="GalaxyUserTool", uuid=uuid4(), public=False, active=True)
    queue = Mock(spec=JobHandlerQueue)
    queue.app = Mock()
    queue.dispatcher = Mock()
    queue.app.toolbox.has_tool = Mock(side_effect=error)

    JobHandlerQueue._check_job_at_startup(queue, job)

    queue.job_wrapper.assert_called_once_with(job)
    queue.job_wrapper.return_value.fail.assert_called_once_with(
        "This tool was disabled before the job completed.  Please contact your Galaxy administrator."
    )
    queue.dispatcher.recover.assert_not_called()
    assert f"(uuid {job.dynamic_tool.uuid}) unavailable: {error}" in caplog.text
    assert "removed from tool config" not in caplog.text


def test_job_whose_tool_left_tool_config_fails_at_startup(caplog):
    job = model.Job()
    job.id = 1
    job.tool_id = "removed_tool"
    queue = Mock(spec=JobHandlerQueue)
    queue.app = Mock()
    queue.dispatcher = Mock()
    queue.app.toolbox.has_tool = Mock(return_value=False)

    JobHandlerQueue._check_job_at_startup(queue, job)

    queue.job_wrapper.return_value.fail.assert_called_once_with(
        "This tool was disabled before the job completed.  Please contact your Galaxy administrator."
    )
    queue.dispatcher.recover.assert_not_called()
    assert "(1) Tool 'removed_tool' removed from tool config, unable to recover job" in caplog.text
