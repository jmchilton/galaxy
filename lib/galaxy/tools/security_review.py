"""Review the templates of loaded tools, store the reviews, and check the values of jobs against them.

The review (:mod:`galaxy.tool_util.security`) finds places where a value a user controls can leave
the quotes or the argument it is written into. It runs once per tool version and analyser version,
in the background after the toolbox loads or on the first job of a tool, and never on a request.
Reviews are stored as one JSON file per tool in ``tool_security_review_cache_dir``, which every
Galaxy process of an installation may share.
"""

import errno
import fcntl
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Iterable,
    Optional,
    TYPE_CHECKING,
)

from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.parser.interface import ToolSource
from galaxy.tool_util.parser.xml import XmlToolSource
from galaxy.tool_util.parser.yaml import YamlToolSource
from galaxy.tool_util.security import (
    ANALYSER_VERSION,
    Finding,
    Report,
    review_tool_source,
    ReviewTimeout,
)
from galaxy.tool_util.security.charsets import (
    CRITICAL,
    HIGH,
)
from galaxy.tool_util.security.report import VULNERABILITY

if TYPE_CHECKING:
    from galaxy.tools import Tool

log = logging.getLogger(__name__)

OFF = "off"
LOG = "log"
ENFORCE = "enforce"
MODES = (OFF, LOG, ENFORCE)

# Findings whose characters are checked in the values of a job. Medium findings (a value that can
# split into more arguments, close quotes without starting a command, or name another path) are
# not: the characters they name, a space, a slash or a quote, are common in element identifiers and
# dataset names, and a warning for each such job would bury the warnings that matter.
CHECKED_SEVERITIES = frozenset((HIGH, CRITICAL))

ANALYSED = "analysed"
NOT_ANALYSED = "not_analysed"

# Tool types whose command Galaxy writes itself or that have no Cheetah template.
_UNREVIEWED_TOOL_TYPES = frozenset(("user_defined", "expression"))


@dataclass(frozen=True)
class ToolReview:
    """The stored outcome of reviewing one tool version."""

    status: str
    tool_id: Optional[str] = None
    tool_version: Optional[str] = None
    reason: Optional[str] = None
    seconds: float = 0.0
    report: Optional[Report] = None

    @property
    def checked_findings(self) -> list[Finding]:
        """The findings whose characters are compared with the values of a job."""
        if self.report is None:
            return []
        return [
            f
            for f in self.report.findings
            if f.kind == VULNERABILITY and f.severity in CHECKED_SEVERITIES and f.breakout and f.refs
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyser_version": ANALYSER_VERSION,
            "status": self.status,
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
            "reason": self.reason,
            "seconds": self.seconds,
            "report": self.report.to_dict() if self.report is not None else None,
        }

    @classmethod
    def from_dict(cls, as_dict: dict[str, Any]) -> "ToolReview":
        report = as_dict.get("report")
        return cls(
            status=as_dict["status"],
            tool_id=as_dict.get("tool_id"),
            tool_version=as_dict.get("tool_version"),
            reason=as_dict.get("reason"),
            seconds=float(as_dict.get("seconds") or 0.0),
            report=Report.from_dict(report) if report is not None else None,
        )


def reviewed_tool_source(tool: "Tool") -> Optional[ToolSource]:
    """The source the review reads: the tool as parsed, macros expanded; None for a tool without a template."""
    if tool.tool_type_local or tool.tool_type in _UNREVIEWED_TOOL_TYPES or not tool.command:
        return None
    source = tool.tool_source
    if not isinstance(source, (XmlToolSource, YamlToolSource)):
        return None
    return source


def review_key(tool_source: ToolSource) -> str:
    """Names the review of this tool text by this analyser."""
    digest = hashlib.sha256()
    for part in (ANALYSER_VERSION, type(tool_source).__name__, tool_source.to_string()):
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


class ReviewCache:
    """Reviews in a directory, one JSON file each, written so that concurrent readers see whole files."""

    def __init__(self, directory: str) -> None:
        self.directory = directory

    def path(self, key: str) -> str:
        return os.path.join(self.directory, key[:2], f"{key}.json")

    def get(self, key: str) -> Optional[ToolReview]:
        """The stored review; None when there is none or it cannot be read."""
        path = self.path(key)
        try:
            with open(path) as fh:
                as_dict = json.load(fh)
            if as_dict.get("analyser_version") != ANALYSER_VERSION:
                return None
            return ToolReview.from_dict(as_dict)
        except FileNotFoundError:
            return None
        except Exception as e:
            log.debug("Ignoring unreadable tool security review %s: %s", path, e)
            return None

    def put(self, key: str, review: ToolReview) -> None:
        path = self.path(key)
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        # Write to a file of its own and rename it into place: os.replace is atomic, so another
        # process reads either no review or a whole one.
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=f".{key}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(review.to_dict(), fh)
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


class ToolSecurityReviewer:
    """Reviews tools on demand or in the background."""

    def __init__(self, mode: str, cache_dir: str, timeout: float) -> None:
        if mode not in MODES:
            raise ValueError(f"tool_security_review must be one of {', '.join(MODES)}, not '{mode}'")
        self.mode = mode
        self.cache = ReviewCache(cache_dir)
        self.timeout = timeout
        self._reviews: dict[str, ToolReview] = {}
        self._lock = threading.Lock()
        self._key_locks: dict[str, threading.Lock] = {}
        self._warm_up_thread: Optional[threading.Thread] = None
        self._warm_up_again = False
        self._stop = threading.Event()

    @classmethod
    def from_config(cls, config: Any) -> "ToolSecurityReviewer":
        return cls(
            mode=config.tool_security_review,
            cache_dir=config.tool_security_review_cache_dir,
            timeout=float(config.tool_security_review_timeout),
        )

    @property
    def enabled(self) -> bool:
        return self.mode != OFF

    # -- reviews -------------------------------------------------------------------------------

    def review(self, tool: "Tool", compute: bool = True) -> Optional[ToolReview]:
        """The review of a tool: from memory, from the cache directory, or computed within the timeout.

        None when reviews are off, the tool has no template to review, or ``compute`` is false
        and no review is stored.
        """
        if not self.enabled:
            return None
        try:
            tool_source = reviewed_tool_source(tool)
            if tool_source is None:
                return None
            key = review_key(tool_source)
        except Exception as e:
            log.warning("Cannot review tool %s for security: %s", tool.id, e)
            return None
        if (review := self._reviews.get(key)) is not None:
            return review
        with self._key_lock(key):
            if (review := self._reviews.get(key)) is not None:
                return review
            review = self.cache.get(key)
            if review is None:
                if not compute:
                    return None
                review = self._compute(tool, tool_source)
                self._store(key, review)
            self._reviews[key] = review
        return review

    def _key_lock(self, key: str) -> threading.Lock:
        with self._lock:
            return self._key_locks.setdefault(key, threading.Lock())

    def _compute(self, tool: "Tool", tool_source: ToolSource) -> ToolReview:
        started = time.monotonic()
        try:
            # The tool's own source dropped its XML tree after parsing; parse the text it kept.
            fresh = get_tool_source(
                tool_source_class=type(tool_source).__name__, raw_tool_source=tool_source.to_string()
            )
            report = review_tool_source(fresh, timeout=self.timeout)
        except ReviewTimeout:
            log.warning(
                "Security review of tool %s version %s took longer than %ss, the tool is not reviewed",
                tool.id,
                tool.version,
                self.timeout,
            )
            return ToolReview(NOT_ANALYSED, tool.id, tool.version, reason="timeout", seconds=time.monotonic() - started)
        except Exception as e:
            log.warning("Security review of tool %s version %s failed: %s", tool.id, tool.version, e)
            log.debug("Security review of tool %s failed", tool.id, exc_info=True)
            return ToolReview(
                NOT_ANALYSED,
                tool.id,
                tool.version,
                reason=f"error: {type(e).__name__}",
                seconds=time.monotonic() - started,
            )
        review = ToolReview(ANALYSED, tool.id, tool.version, seconds=time.monotonic() - started, report=report)
        self._log_summary(review)
        return review

    def _store(self, key: str, review: ToolReview) -> None:
        try:
            self.cache.put(key, review)
        except Exception as e:
            log.warning("Cannot store the security review of tool %s: %s", review.tool_id, e)

    @staticmethod
    def _log_summary(review: ToolReview) -> None:
        serious = [
            f
            for f in (review.report.sorted() if review.report else [])
            if f.kind == VULNERABILITY and f.severity in CHECKED_SEVERITIES
        ]
        if not serious:
            return
        counts = ", ".join(
            f"{sum(1 for f in serious if f.severity == severity)} {severity}"
            for severity in (CRITICAL, HIGH)
            if any(f.severity == severity for f in serious)
        )
        examples = "; ".join(f"{f.rule} at {f.location} line {f.line}: {f.source}" for f in serious[:3])
        log.info(
            "Security review of tool %s version %s: %s finding(s), e.g. %s",
            review.tool_id,
            review.tool_version,
            counts,
            examples,
        )

    # -- warm-up -------------------------------------------------------------------------------

    def warm_up(self, get_tools: Callable[[], Iterable["Tool"]]) -> None:
        """Review the tools ``get_tools`` returns in a background thread.

        A call while a warm-up runs makes it go over the tools again once it is done, so that a
        reloaded toolbox is covered.
        """
        if not self.enabled:
            return
        with self._lock:
            if self._warm_up_thread is not None and self._warm_up_thread.is_alive():
                self._warm_up_again = True
                return
            self._warm_up_thread = threading.Thread(
                target=self._warm_up_loop, args=(get_tools,), name="ToolSecurityReview", daemon=True
            )
            self._warm_up_thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        thread = self._warm_up_thread
        if thread is not None:
            thread.join(5)

    def _warm_up_loop(self, get_tools: Callable[[], Iterable["Tool"]]) -> None:
        while True:
            try:
                self._warm_up_pass(get_tools)
            except Exception:
                log.exception("Tool security review warm-up failed")
            with self._lock:
                if not self._warm_up_again or self._stop.is_set():
                    self._warm_up_thread = None
                    return
                self._warm_up_again = False

    def _warm_up_pass(self, get_tools: Callable[[], Iterable["Tool"]]) -> None:
        with _exclusive(os.path.join(self.cache.directory, "warm-up.lock")) as acquired:
            if not acquired:
                log.debug("Another Galaxy process is reviewing tools, skipping the warm-up here")
                return
            started = time.monotonic()
            reviewed = 0
            not_analysed = 0
            for tool in get_tools():
                if self._stop.is_set():
                    return
                before = len(self._reviews)
                review = self.review(tool)
                if review is not None:
                    reviewed += 1
                    not_analysed += review.status != ANALYSED
                if len(self._reviews) != before:
                    # Let request and job threads have the interpreter between tools.
                    time.sleep(0.001)
            log.info(
                "Tool security review warm-up: %d tool(s) reviewed or read from %s, %d not reviewed, in %.1fs",
                reviewed,
                self.cache.directory,
                not_analysed,
                time.monotonic() - started,
            )


class _exclusive:
    """A non-blocking exclusive lock on a file, shared by the Galaxy processes of a host or shared filesystem."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._fh: Optional[Any] = None

    def __enter__(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._fh = open(self.path, "a")
            fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                self._close()
                return False
            # A filesystem without locks: review here, the cache stays consistent either way.
            log.debug("Cannot lock %s: %s", self.path, e)
            self._close()
        return True

    def __exit__(self, *exc: Any) -> None:
        self._close()

    def _close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
