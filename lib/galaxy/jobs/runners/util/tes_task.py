"""Inspect the GA4GH TES tasks that Galaxy's Pulsar TES runner submits.

Pulsar inside the task reports job state over the message queue. If the task
dies before Pulsar reports, these helpers let the runner see that on the TES
server and say why.
"""

import re
from collections.abc import Iterable
from typing import (
    NamedTuple,
    TYPE_CHECKING,
)

from pydantic import ValidationError

if TYPE_CHECKING:
    from pydantictes.api import TesClient
    from pydantictes.models import TesTask

TES_TASK_NOT_FOUND = "NOT_FOUND"
"""Pseudo state for a task the TES server has no record of."""

TES_FINISHED_STATES = frozenset(
    ["COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED", "PREEMPTED", TES_TASK_NOT_FOUND]
)
"""States after which nothing in the task can report to Galaxy anymore."""

STDERR_TAIL_LINES = 20
SYSTEM_LOG_TAIL_LINES = 10
TAIL_MAX_CHARACTERS = 4000

# Pulsar passes its job description, including message queue credentials, to the
# task's executors as base64 arguments, which can surface in stderr and system logs.
# Known values are removed exactly; these patterns catch the rest.
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/_-]{32,}={0,2}")
_URL_USERINFO = re.compile(r"(\b[A-Za-z][A-Za-z0-9+.-]*://)\S+@")
_SECRET_ASSIGNMENT = re.compile(r"((?:key|token|secret|password)['\"]?\s*[=:]\s*['\"]?)[^&\s'\",}]+", re.IGNORECASE)
_BASIC_AUTH = re.compile(r"(\bBasic\s+)[A-Za-z0-9+/=]{4,}")
MINIMUM_SECRET_LENGTH = 6
REDACTED = "[redacted]"


def fetch_tes_task_state(tes_client: "TesClient", task_id: str) -> str:
    """Return the TES state name of a task, or ``TES_TASK_NOT_FOUND``.

    Any other failure to read the task is raised.
    """
    try:
        # pydantic-tes rejects the MINIMAL view, which omits executors.
        task = tes_client.get_task(task_id, "BASIC")
    except ValidationError as e:
        # pydantic-tes 0.4.0 predates TES 1.1's PREEMPTED and CANCELING states.
        for error in e.errors():
            state = error.get("input")
            if error["loc"] == ("state",) and isinstance(state, str):
                return state
        raise
    except Exception as e:
        if http_status_code(e) == 404:
            return TES_TASK_NOT_FOUND
        raise
    return task.state.value if task.state else "UNKNOWN"


def describe_tes_error(exception: Exception) -> str:
    """Describe a failure to read a TES task, for logs."""
    if isinstance(exception, ValidationError):
        # Pydantic's message quotes the task document, executor arguments included.
        return "TES task document or destination parameters failed validation"
    return redact(str(exception))[:500]


def http_status_code(exception: BaseException) -> int | None:
    """Status code of the HTTP response behind a pydantic-tes request error, if any."""
    for candidate in (exception, exception.__cause__):
        status_code = getattr(getattr(candidate, "response", None), "status_code", None)
        if isinstance(status_code, int):
            return status_code
    return None


class TesTaskFailure(NamedTuple):
    summary: str
    """Names the executor that failed, or ran last, and its exit code. Short enough for ``Job.info``."""
    executor_stderr: str
    """Redacted tail of that executor's stderr."""
    system_logs: str
    """Redacted tail of the TES server's system logs for the task, which describe its host and setup."""


def describe_tes_task_failure(task: "TesTask", secrets: Iterable[str] = ()) -> TesTaskFailure:
    """Summarize the last attempt of a FULL view TES task. Any field may be empty.

    ``secrets`` and the arguments of Pulsar's own executors are redacted from the logs.
    """
    secrets = [*secrets, *_pulsar_executor_arguments(task)]
    attempts = task.logs or []
    if not attempts:
        return TesTaskFailure("", "", "")
    attempt = attempts[-1]
    executor_logs = attempt.logs or []
    summary = ""
    executor_stderr = ""
    if executor_logs:
        index = len(executor_logs) - 1
        for i, executor_log in enumerate(executor_logs):
            if executor_log.exit_code != 0:
                index = i
                break
        executor_log = executor_logs[index]
        label = _executor_label(task, index)
        short_label = _executor_label(task, index, with_image=False)
        if executor_log.exit_code in (None, -255):
            # pydantic-tes fills in -255 when the server reports no exit code.
            summary = f"{short_label} reported no exit code."
        elif executor_log.exit_code == 0:
            summary = f"{short_label} ran last and exited with code 0."
        else:
            summary = f"{short_label} exited with code {executor_log.exit_code}."
        stderr = _tail(executor_log.stderr, STDERR_TAIL_LINES, secrets)
        if stderr:
            executor_stderr = f"{label} stderr, last lines:\n{stderr}"
    system_logs = _tail("\n".join(attempt.system_logs or []), SYSTEM_LOG_TAIL_LINES, secrets)
    return TesTaskFailure(summary, executor_stderr, system_logs)


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    for secret in sorted(secrets, key=len, reverse=True):
        if len(secret) >= MINIMUM_SECRET_LENGTH:
            text = text.replace(secret, REDACTED)
    text = _URL_USERINFO.sub(rf"\1{REDACTED}@", text)
    text = _SECRET_ASSIGNMENT.sub(rf"\1{REDACTED}", text)
    text = _BASIC_AUTH.sub(rf"\1{REDACTED}", text)
    return _BASE64_RUN.sub(_redact_base64_run, text)


def _redact_base64_run(match: re.Match[str]) -> str:
    run = match.group(0)
    # Keep paths, hex digests and identifiers; base64 mixes cases and digits.
    if re.search(r"[a-z]", run) and re.search(r"[A-Z]", run) and re.search(r"[0-9]", run):
        return REDACTED
    return run


def _pulsar_executor_arguments(task: "TesTask") -> list[str]:
    return [
        argument
        for executor in task.executors or []
        if executor.command and executor.command[0].startswith("pulsar-")
        for argument in executor.command[1:]
        if not argument.startswith("-")
    ]


def _executor_label(task: "TesTask", index: int, with_image: bool = True) -> str:
    executors = task.executors or []
    details = []
    if index < len(executors):
        executor = executors[index]
        command = executor.command or []
        # Pulsar's own executors run pulsar-submit and pulsar-finish. Only the
        # program name is shown; the arguments carry credentials.
        if command and command[0].startswith("pulsar-"):
            details.append(command[0])
        if with_image and executor.image:
            details.append(f"image {executor.image}")
    detail = f" ({', '.join(details)})" if details else ""
    return f"Executor {index}{detail}"


def _tail(text: str | None, lines: int, secrets: Iterable[str]) -> str:
    if not text:
        return ""
    # Redact before cutting, so no partial secret survives at the cut.
    tail = "\n".join(redact(text, secrets).rstrip().splitlines()[-lines:])
    return tail[-TAIL_MAX_CHARACTERS:]
