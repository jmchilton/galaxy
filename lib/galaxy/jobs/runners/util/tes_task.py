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
from urllib.parse import (
    unquote,
    urlparse,
)

from pydantic import ValidationError

if TYPE_CHECKING:
    from pulsar.client.tes_job_config import TesJobParams
    from pydantictes.api import TesClient
    from pydantictes.models import (
        TesExecutorLog,
        TesTask,
        TesTaskLog,
    )

    from galaxy.jobs.runners import AsynchronousJobState

TES_TASK_NOT_FOUND = "NOT_FOUND"
"""Pseudo state for a task the TES server has no record of."""

TES_FINISHED_STATES = frozenset(
    ["COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED", "PREEMPTED", TES_TASK_NOT_FOUND]
)
"""States after which nothing in the task can report to Galaxy anymore."""

TES_NOTHING_TO_CANCEL_STATES = TES_FINISHED_STATES | {"CANCELING"}
"""States in which cancelling the task has nothing left to do."""

# A TES task's server URL and task id. Nothing in the TES spec makes task ids unique
# across servers (tesp-api's are MongoDB ObjectIds), and destinations can use different servers.
TesTaskKey = tuple[str | None, str]

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
# Leaves room in Job.info's 255 characters for the sentence before it with a 36-character task id.
SUMMARY_MAX_CHARACTERS = 130

# Reading why a TES server ended a task in SYSTEM_ERROR from its system logs. Funnel writes logfmt
# lines (level='error' msg='System error' error='...'), TESK the taskmaster's log ("<date> <time>
# ERROR: <message>"), and tesp-api one entry per failure: a reason line, then the job's stderr tail.
_LOGFMT_LEVEL = re.compile(r"\blevel='?([A-Za-z]+)")
_LOGFMT_ERROR = re.compile(r"\berror='([^']+)'")
_LOGFMT_MSG = re.compile(r"\bmsg='([^']+)'")
_LEVEL_NAME = re.compile(r"\b(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b:?\s*")
_ERROR_LEVELS = frozenset(["error", "critical", "fatal"])
_FAILURE_WORDS = re.compile(
    r"fail|error|refused|denied|too long|not found|exception|cannot|can't|unable", re.IGNORECASE
)


def tes_task_key(job_state: "AsynchronousJobState") -> TesTaskKey:
    task_id = job_state.job_id
    assert task_id
    return job_state.job_destination.params.get("tes_url"), task_id


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
    message: str
    """Why the job failed, naming the executor that failed, or ran last, or the task, and its exit code.

    It becomes ``Job.info``, which is cut at 255 characters, so it names the
    executor without its image; ``executor_stderr`` has the image.
    """
    executor_stderr: str
    """Redacted tail of that executor's stderr."""
    system_logs: str
    """Redacted tail of the TES server's system logs for the task, which describe its host and setup."""


def describe_tes_task_failure(
    task_id: str, task_state: str, task: "TesTask | None" = None, secrets: Iterable[str] = ()
) -> TesTaskFailure:
    """Describe a task that reached ``task_state`` without Pulsar reporting a final job status.

    ``task`` is its FULL view, when it could be read; only its last attempt is
    summarized. ``secrets`` and the arguments of Pulsar's own executors are
    redacted from the logs.
    """
    if task_state == TES_TASK_NOT_FOUND:
        return TesTaskFailure(
            f"The TES server has no record of task {task_id}, and Pulsar never reported a final job status.", "", ""
        )
    if task_state == "COMPLETE":
        message = f"TES task {task_id} completed, but Pulsar never reported a final job status."
    else:
        message = f"TES task {task_id} ended in state {task_state} before Pulsar reported a final job status."
    if task is None or not task.logs:
        return TesTaskFailure(message, "", "")
    secrets = [*secrets, *_pulsar_executor_arguments(task)]
    attempt = task.logs[-1]
    executor_logs = attempt.logs or []
    executor_stderr = ""
    summary = ""
    failing_log: TesExecutorLog | None = None
    if executor_logs:
        index = len(executor_logs) - 1
        for i, executor_log in enumerate(executor_logs):
            if executor_log.exit_code != 0:
                index = i
                break
        executor_log = failing_log = executor_logs[index]
        per_executor = _logs_are_per_executor(task, executor_logs)
        if per_executor:
            label = _executor_label(task, index)
            short_label = _executor_label(task, index, with_image=False)
        else:
            label = "Task"
            short_label = "The task"
        if executor_log.exit_code in (None, -255):
            # pydantic-tes fills in -255 when the server reports no exit code.
            summary = f"{short_label} reported no exit code."
        elif executor_log.exit_code == 0 and per_executor:
            summary = f"{short_label} ran last and exited with code 0."
        else:
            summary = f"{short_label} exited with code {executor_log.exit_code}."
        stderr = _tail(executor_log.stderr, STDERR_TAIL_LINES, secrets)
        if stderr:
            executor_stderr = f"{label} stderr, last lines:\n{stderr}"
    if task_state == "SYSTEM_ERROR":
        summary = _system_error_summary(summary, failing_log, attempt, secrets)
    if summary:
        message = f"{message} {summary}"
    system_logs = _tail("\n".join(attempt.system_logs or []), SYSTEM_LOG_TAIL_LINES, secrets)
    return TesTaskFailure(message, executor_stderr, system_logs)


def _system_error_summary(
    summary: str, executor_log: "TesExecutorLog | None", attempt: "TesTaskLog", secrets: Iterable[str]
) -> str:
    """The summary of a SYSTEM_ERROR task: the TES server's reason, after the exit code of an executor that failed.

    An executor log with exit code 0 doesn't explain a system error, and Funnel records 0
    for an executor it could not start at all, so that code is not reported.
    """
    executor_failed = executor_log is not None and executor_log.exit_code not in (0, None, -255)
    prefix = f"{summary} " if executor_failed else ""
    reason = _system_log_reason(attempt.system_logs or [], secrets)
    if reason:
        return _shorten(f"{prefix}System log: {reason}", SUMMARY_MAX_CHARACTERS)
    if executor_log is not None and executor_log.exit_code == 0:
        return "No executor reported a failure."
    return summary


def _system_log_reason(system_logs: list[str], secrets: Iterable[str]) -> str:
    """The last error line of the system logs, redacted, or ``""``.

    An entry whose first line is an unlabelled error (tesp-api's reason) is named before its last error line.
    """
    for entry in reversed(system_logs):
        lines = [line.strip() for line in redact(entry, secrets).splitlines() if line.strip()]
        for i in range(len(lines) - 1, -1, -1):
            if not _is_error_line(lines[i]):
                continue
            reason = _error_line_reason(lines[i])
            if i > 0 and _log_level(lines[0]) is None and _is_error_line(lines[0]):
                reason = f"{_error_line_reason(lines[0])}: {reason}"
            return reason
    return ""


def _log_level(line: str) -> str | None:
    match = _LOGFMT_LEVEL.search(line) or _LEVEL_NAME.search(line)
    return match.group(1).lower() if match else None


def _is_error_line(line: str) -> bool:
    level = _log_level(line)
    if level is not None:
        return level in _ERROR_LEVELS
    return bool(_FAILURE_WORDS.search(line))


def _error_line_reason(line: str) -> str:
    if _LOGFMT_LEVEL.search(line):
        match = _LOGFMT_ERROR.search(line) or _LOGFMT_MSG.search(line)
        return match.group(1) if match else line
    match = _LEVEL_NAME.search(line)
    return line[match.end() :] if match else line


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def tes_known_secrets(amqp_url: str | None, tes_params: "TesJobParams") -> list[str]:
    """Credentials the runner knows that may surface in a task's logs: the broker and TES passwords."""
    secrets = []
    if amqp_url:
        amqp_password = urlparse(amqp_url).password
        if amqp_password:
            secrets.append(unquote(amqp_password))
            secrets.append(amqp_password)
    if tes_params.basic_auth:
        secrets.append(tes_params.basic_auth.password)
    return secrets


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


def _logs_are_per_executor(task: "TesTask", executor_logs: list["TesExecutorLog"]) -> bool:
    """Whether the attempt's executor logs belong to the task's executors in order.

    Funnel, TESK and tesp-api with per-executor logs record the executors that ran,
    up to the one that failed. tesp-api without them records one log for the whole
    task. One log for several executors is therefore ambiguous and not attributed.
    """
    executor_count = len(task.executors or [])
    if len(executor_logs) > executor_count:
        return False
    return not (len(executor_logs) == 1 and executor_count > 1)


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
