"""Retries of TES task cancels that failed because the TES server was unreachable.

Each request to an unreachable server can wait for a connection timeout, so the
retries back off per server rather than per task: an attempt tries the server's
pending cancels oldest first and stops at the first that finds it unreachable, and
the rest wait with it for its next attempt. However many of its tasks wait to be
cancelled, an unreachable server is asked once per backoff interval.

Cancels are kept per server because nothing in the TES spec makes task ids unique
across servers: two destinations' servers can each run a task with the same id.
"""

import threading
from collections.abc import Callable
from dataclasses import (
    dataclass,
    field,
)
from time import monotonic
from typing import Any

FIRST_DELAY = 10.0
MAX_DELAY = 120.0


@dataclass
class PendingTesCancel:
    task_id: str
    job_id_tag: str
    destination_params: dict[str, Any]
    give_up_at: float
    last_error: str
    attempts: int
    """Cancel requests sent for this task so far."""

    @property
    def tes_url(self) -> str | None:
        return self.destination_params.get("tes_url")


@dataclass
class _ServerRetries:
    """One TES server's pending cancels, oldest first, and when to try them next."""

    next_attempt: float
    delay: float = FIRST_DELAY
    cancels: dict[str, PendingTesCancel] = field(default_factory=dict)


class TesCancelRetries:
    """The pending cancels, keyed by TES server URL, then task id.

    Any thread stopping a job adds and discards cancels; the monitor thread retries them.
    """

    def __init__(self, timeout: float):
        self.timeout = timeout
        self._servers: dict[str | None, _ServerRetries] = {}
        self._lock = threading.Lock()

    def add(self, task_id: str, job_id_tag: str, destination_params: dict[str, Any], error: str, attempts: int) -> bool:
        """Retry cancelling a task for ``timeout`` seconds. Return ``False`` if it is already retried."""
        now = monotonic()
        cancel = PendingTesCancel(task_id, job_id_tag, dict(destination_params), now + self.timeout, error, attempts)
        with self._lock:
            server = self._servers.get(cancel.tes_url)
            if server is None:
                server = _ServerRetries(next_attempt=now + min(FIRST_DELAY, self.timeout))
                self._servers[cancel.tes_url] = server
            elif task_id in server.cancels:
                return False
            server.cancels[task_id] = cancel
        return True

    def discard(self, task_id: str, destination_params: dict[str, Any]) -> None:
        tes_url = destination_params.get("tes_url")
        with self._lock:
            server = self._servers.get(tes_url)
            if server is None:
                return
            server.cancels.pop(task_id, None)
            if not server.cancels:
                del self._servers[tes_url]

    def pending(self) -> list[PendingTesCancel]:
        with self._lock:
            return [cancel for server in self._servers.values() for cancel in server.cancels.values()]

    def retry_due(self, cancel: Callable[[PendingTesCancel], str | None]) -> list[PendingTesCancel]:
        """Retry the cancels of each server that is due. Return the cancels given up on.

        ``cancel`` sends one cancel request and returns the error if the server
        was unreachable, or ``None`` when there is nothing more to do.
        """
        now = monotonic()
        with self._lock:
            due = [
                (tes_url, list(server.cancels.values()))
                for tes_url, server in self._servers.items()
                if server.next_attempt <= now
            ]
        given_up = []
        for tes_url, cancels in due:
            done = []
            error = None
            for pending in cancels:
                pending.attempts += 1
                error = cancel(pending)
                if error is not None:
                    break
                done.append(pending.task_id)
            given_up.extend(self._record_attempt(tes_url, done, error))
        return given_up

    def _record_attempt(self, tes_url: str | None, done: list[str], error: str | None) -> list[PendingTesCancel]:
        now = monotonic()
        given_up = []
        with self._lock:
            server = self._servers.get(tes_url)
            if server is None:
                # A later stop cancelled the server's last task meanwhile.
                return []
            for task_id in done:
                server.cancels.pop(task_id, None)
            if error is not None:
                for pending in list(server.cancels.values()):
                    pending.last_error = error
                    if now >= pending.give_up_at:
                        given_up.append(server.cancels.pop(pending.task_id))
                server.delay = min(server.delay * 2, MAX_DELAY)
                if server.cancels:
                    # The last attempt for a task comes at its deadline.
                    earliest_give_up = min(pending.give_up_at for pending in server.cancels.values())
                    server.next_attempt = min(now + server.delay, earliest_give_up)
            if not server.cancels:
                del self._servers[tes_url]
        return given_up
