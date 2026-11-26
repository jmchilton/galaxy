"""Review the templates of tools and check the values of jobs against the reviews.

The review (:mod:`galaxy.tool_util.security`) finds places where a value a user controls can leave
the quotes or the argument it is written into. A process that prepares jobs reviews a tool when it
prepares the tool's first job and keeps the review as long as it keeps the tool: a reloaded tool is
a new object and is reviewed again. A review takes a few milliseconds and at most about two seconds
of CPU for the largest templates known; it has no time limit, since it runs once per tool and process,
and the analyser's step budget bounds the work on any one template. It is never stored.

Before a job's command line is built, :meth:`ToolSecurityReviewer.check_job` compares the values of
the job's inputs with the tool's high and critical findings: a value that contains a character that
can leave its place is logged (``log``) or fails the job (``enforce_code`` and the stricter levels).

A job that the review cannot check (a finding no character test can decide, an error in the check)
gets a stricter check instead, unless ``when_unsure`` says otherwise: every value the job carries must
be plain, without a character that can leave its place anywhere. The values come from the same
sources the findings name, read the same way. No value is plain, and the job is refused outright,
when the review failed, when the review found template code that can turn a plain value into an
unsafe one or read text the job does not carry, where letters alone can be code, or where a template
writes a value the review cannot trace to an input.
"""

import logging
import threading
import time
from collections.abc import (
    Iterable,
    Iterator,
)
from contextlib import contextmanager
from dataclasses import dataclass
from typing import (
    Any,
    TYPE_CHECKING,
)
from weakref import WeakKeyDictionary

from galaxy.model.metadata import FileParameter
from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.parser.interface import ToolSource
from galaxy.tool_util.parser.xml import XmlToolSource
from galaxy.tool_util.parser.yaml import YamlToolSource
from galaxy.tool_util.security import (
    Finding,
    Report,
    review_tool_source,
    SourceRef,
)
from galaxy.tool_util.security.charsets import (
    ALL,
    CODE,
    CRITICAL,
    DASH_WORD,
    DATA,
    HIGH,
    LEADING_DASH,
    marks,
    MEDIUM,
    not_plain,
    NOT_PLAIN,
    PROBE,
    show,
    stricter,
    TILDE_WORD,
    WHITESPACE,
)
from galaxy.tool_util.security.classify import (
    Uncheckable,
    uncheckable_reasons,
    unchecked_locations,
    WHY,
)
from galaxy.tool_util.security.codes import RefusalCode
from galaxy.tool_util.security.report import (
    DATASET_ATTRIBUTE,
    DATASET_CONTENT,
    ELEMENT_IDENTIFIER,
    GROUP_TAGS,
    METADATA,
    OPAQUE,
    RAW,
    RAW_DATASET_ATTRIBUTE,
    RAW_METADATA,
    serious_findings,
    SPECIAL,
    TEXT,
    USER_PREFERENCE,
    VULNERABILITY,
)
from galaxy.tools.security_refusal import ToolInputRejected
from galaxy.tools.wrappers import (
    DatasetCollectionWrapper,
    DatasetFilenameWrapper,
    DatasetListWrapper,
    ToolParameterValueWrapper,
)

if TYPE_CHECKING:
    from galaxy.tools import Tool
    from galaxy.tools.evaluation import ToolEvaluator

log = logging.getLogger(__name__)

OFF = "off"
LOG = "log"
# The levels of enforcement, each refusing what the one before it does and more.
ENFORCE_CODE = "enforce_code"
ENFORCE_DATA = "enforce_data"
ENFORCE_ALL = "enforce_all"
ENFORCING = (ENFORCE_CODE, ENFORCE_DATA, ENFORCE_ALL)
MODES = (OFF, LOG, *ENFORCING)

# What to do with a job the review cannot check (tool_security_review_when_unsure).
STRICT = "strict"
REFUSE = "refuse"
WHEN_UNSURE = (STRICT, REFUSE, LOG)

# The findings each mode acts on: log warns of everything enforce_all refuses.
_LEVELS = {LOG: ALL, ENFORCE_CODE: CODE, ENFORCE_DATA: DATA, ENFORCE_ALL: ALL}

ANALYSED = "analysed"
NOT_ANALYSED = "not_analysed"

# Tool types whose command Galaxy writes itself or that have no Cheetah template.
_UNREVIEWED_TOOL_TYPES = frozenset(("user_defined", "expression"))


@contextmanager
def _keeping_consumes(evaluator: "ToolEvaluator") -> Iterator[None]:
    """Reading identifiers and names through the wrappers marks the job as consuming them, which
    changes how the job cache matches it: the check must not."""
    consumes = (evaluator.consumes_names, evaluator.consumes_identifiers)
    try:
        yield
    finally:
        evaluator.consumes_names, evaluator.consumes_identifiers = consumes


@dataclass(frozen=True)
class ToolReview:
    """The outcome of reviewing one tool."""

    status: str
    tool_id: str | None = None
    tool_version: str | None = None
    reason: str | None = None
    seconds: float = 0.0
    report: Report | None = None

    @property
    def checked_findings(self) -> list[Finding]:
        """The findings whose characters are compared with the values of a job at the code level."""
        return self.checked_at(CODE)

    @property
    def unchecked_findings(self) -> list[Finding]:
        """Findings of the code level that no character test on job values can decide."""
        return self.unchecked_at(CODE)

    def checked_at(self, level: str) -> list[Finding]:
        return [f for f in self._enforced(level) if f.checkable]

    def unchecked_at(self, level: str) -> list[Finding]:
        return [f for f in self._enforced(level) if not f.checkable]

    def _enforced(self, level: str) -> list[Finding]:
        return _enforced_findings(self.report, level) if self.report is not None else []

    @property
    def unchecked_locations(self) -> dict[str, str]:
        """Templates whose values no character test can judge, with the reason."""
        return self.report.unchecked_locations if self.report is not None else {}


def reviewed_tool_source(tool: "Tool") -> ToolSource | None:
    """The source the review reads: the tool as parsed, macros expanded; None for a tool without a template."""
    if tool.tool_type_local or tool.tool_type in _UNREVIEWED_TOOL_TYPES or not tool.command:
        return None
    source = tool.tool_source
    if not isinstance(source, (XmlToolSource, YamlToolSource)):
        return None
    return source


class ToolSecurityReviewer:
    """Reviews tools when their jobs are prepared, and checks job values against the reviews."""

    def __init__(self, mode: str, when_unsure: str = STRICT) -> None:
        if mode not in MODES:
            raise ValueError(f"tool_security_review must be one of {', '.join(MODES)}, not '{mode}'")
        if when_unsure not in WHEN_UNSURE:
            raise ValueError(
                f"tool_security_review_when_unsure must be one of {', '.join(WHEN_UNSURE)}, not '{when_unsure}'"
            )
        self.mode = mode
        self.when_unsure = when_unsure
        # The level of the findings the check acts on.
        self.level = _LEVELS.get(mode, CODE)
        # Keyed by the Tool object: a review lives as long as the tool it is about.
        self._reviews: WeakKeyDictionary[Tool, ToolReview] = WeakKeyDictionary()
        self._tool_locks: WeakKeyDictionary[Tool, threading.Lock] = WeakKeyDictionary()
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, config: Any) -> "ToolSecurityReviewer":
        return cls(
            mode=config.tool_security_review,
            when_unsure=config.tool_security_review_when_unsure,
        )

    @property
    def enabled(self) -> bool:
        return self.mode != OFF

    @property
    def enforcing(self) -> bool:
        return self.mode in ENFORCING

    # -- reviews -------------------------------------------------------------------------------

    def review(self, tool: "Tool") -> ToolReview | None:
        """The review of a tool, computed on first use.

        None when reviews are off or the tool has no template to review.
        """
        if not self.enabled:
            return None
        if (review := self._reviews.get(tool)) is not None:
            return review
        try:
            tool_source = reviewed_tool_source(tool)
        except Exception as e:
            log.warning("Cannot review tool %s for security: %s", tool.id, e)
            review = ToolReview(NOT_ANALYSED, tool.id, tool.version, reason=f"error: {type(e).__name__}")
            # Kept like a failed review, so the next job does not try again.
            self._reviews[tool] = review
            return review
        if tool_source is None:
            return None
        with self._lock:
            tool_lock = self._tool_locks.setdefault(tool, threading.Lock())
        with tool_lock:
            # Another thread preparing a job of the same tool may have reviewed it meanwhile.
            if (review := self._reviews.get(tool)) is None:
                review = self._compute(tool, tool_source)
                self._reviews[tool] = review
        return review

    def _compute(self, tool: "Tool", tool_source: ToolSource) -> ToolReview:
        started = time.monotonic()
        try:
            # The tool's own source dropped its XML tree after parsing; parse the text it kept.
            fresh = get_tool_source(
                tool_source_class=type(tool_source).__name__, raw_tool_source=tool_source.to_string()
            )
            report = review_tool_source(fresh)
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

    @staticmethod
    def _log_summary(review: ToolReview) -> None:
        for location, reason in sorted(review.unchecked_locations.items()):
            log.info(
                "Security review of tool %s version %s: values written in %s are not checked, %s",
                review.tool_id,
                review.tool_version,
                location,
                reason,
            )
        serious = serious_findings(review.report) if review.report else []
        if not serious:
            return
        counts = ", ".join(
            f"{sum(1 for f in serious if f.severity == severity)} {severity}"
            for severity in (CRITICAL, HIGH)
            if any(f.severity == severity for f in serious)
        )
        examples = "; ".join(f"{f.rule} at {f.location} line {f.line}: {f.source}" for f in serious[:3])
        unchecked = len(review.unchecked_findings)
        log.info(
            "Security review of tool %s version %s: %s finding(s)%s, e.g. %s",
            review.tool_id,
            review.tool_version,
            counts,
            f" ({unchecked} cannot be checked against job values)" if unchecked else "",
            examples,
        )

    # -- job values ----------------------------------------------------------------------------

    def check_job(self, tool: "Tool", evaluator: "ToolEvaluator") -> None:
        """Compare the job values in the evaluator's param_dict with the tool's findings.

        Logs each value that contains a breakout character; raises :class:`ToolInputRejected`
        in an enforcing mode.
        """
        if not self.enabled:
            return
        review = self.review(tool)
        job_id = evaluator.job.id
        if review is None:
            return
        if review.status != ANALYSED or review.report is None:
            self._cannot_check(
                tool, evaluator, None, "the security review of this tool failed", RefusalCode.UNCHECKABLE_REVIEW_FAILED
            )
            return
        violations: list[Violation] = []
        if review.checked_at(self.level) or review.report.writes or self.level != CODE:
            try:
                with _keeping_consumes(evaluator):
                    violations = list(find_violations(review.report, evaluator.param_dict, self.level))
            except Exception:
                # With when_unsure log, the check must never be the reason a job fails.
                log.exception("Job %s: checking values against the security review of tool %s failed", job_id, tool.id)
                self._cannot_check(
                    tool,
                    evaluator,
                    review.report,
                    "checking the job's values against the security review failed",
                    RefusalCode.NOT_PLAIN_CHECK_ERROR,
                )
                return
        for violation in violations:
            log.warning(
                "Tool security review (%s): job %s of tool %s version %s: %s of input '%s' contains [%s],"
                " which can leave its place in the %s (%s)",
                violation.rule,
                job_id,
                tool.id,
                tool.version,
                violation.ref.accessor + (f" '{violation.ref.key}'" if violation.ref.key else ""),
                violation.ref.param or violation.ref.key,
                show(violation.chars),
                violation.location,
                violation.severity,
            )
        if violations and self.enforcing:
            # A rule without a code fails the job unexpectedly rather than letting it run.
            raise ToolInputRejected(rejection_message(tool, violations), (RefusalCode(v.rule) for v in violations))
        # The code level's unchecked locations, and those of the findings a stricter level acts on.
        unchecked = sorted(
            set(unchecked_locations(review.report)) | {f.location for f in review.unchecked_at(self.level)}
        )
        # Log mode warns of both; an enforcing mode has refused a job with violations already.
        if unchecked:
            self._cannot_check(
                tool,
                evaluator,
                review.report,
                f"this tool writes values in places that no check of their characters can judge ({', '.join(unchecked)})",
                RefusalCode.NOT_PLAIN_UNCHECKED_PLACE,
                unchecked,
            )

    def _cannot_check(
        self,
        tool: "Tool",
        evaluator: "ToolEvaluator",
        report: Report | None,
        reason: str,
        code: RefusalCode,
        locations: list[str] | None = None,
    ) -> None:
        """A job the review cannot judge: with when_unsure strict its values must all be plain, with refuse it
        is refused, with log what strict would refuse is only logged.

        ``code`` names the refusal of a job with a value that is not plain.
        """
        job_id = evaluator.job.id
        refuses = self.enforcing and self.when_unsure != LOG
        if self.when_unsure == REFUSE:
            log.warning(
                "Tool security review (%s): job %s of tool %s version %s cannot be checked, %s",
                RefusalCode.UNCHECKABLE_WHEN_UNSURE.value,
                job_id,
                tool.id,
                tool.version,
                reason,
            )
            if refuses:
                raise ToolInputRejected(
                    unchecked_message(tool, reason, ["this server refuses every job it cannot check"]),
                    [RefusalCode.UNCHECKABLE_WHEN_UNSURE],
                )
            return
        if no_plain := _no_plain_value(report):
            codes = sorted({code.value for code, _ in no_plain})
            why = [text for _, text in no_plain]
            log.warning(
                "Tool security review (%s): job %s of tool %s version %s cannot be checked, %s, and %s",
                ", ".join(codes),
                job_id,
                tool.id,
                tool.version,
                reason,
                "; ".join(why),
            )
            if refuses:
                raise ToolInputRejected(unchecked_message(tool, reason, why), (code for code, _ in no_plain))
            return
        assert report is not None  # _no_plain_value refuses a job without a report
        try:
            with _keeping_consumes(evaluator):
                harmful = list(strict_violations(report, locations, evaluator.param_dict, self.level))
        except Exception:
            # Only an enforcing mode may fail a job, and then with a message for the user.
            log.exception(
                "Tool security review (%s): the strict check of the values of job %s of tool %s failed",
                RefusalCode.UNCHECKABLE_STRICT_CHECK_ERROR.value,
                job_id,
                tool.id,
            )
            if refuses:
                raise ToolInputRejected(
                    unchecked_message(tool, reason, ["checking its values strictly failed"]),
                    [RefusalCode.UNCHECKABLE_STRICT_CHECK_ERROR],
                )
            return
        if not harmful:
            log.debug("Job %s of tool %s: %s, and every value is plain", job_id, tool.id, reason)
            return
        for ref, chars in harmful:
            log.warning(
                "Tool security review (%s): job %s of tool %s version %s cannot be checked, %s, and %s contains [%s]",
                code.value,
                job_id,
                tool.id,
                tool.version,
                reason,
                _describe(ref),
                show(chars),
            )
        if refuses:
            raise ToolInputRejected(strict_message(tool, reason, harmful, self.level), [code])


@dataclass(frozen=True)
class Violation:
    ref: SourceRef
    chars: frozenset[str]
    rule: str
    severity: str
    location: str


def _refused_at(level: str | None, at: str) -> bool:
    """Whether a finding of ``level`` is refused at the enforcement level ``at``."""
    return level is not None and stricter(level, at) == level


def _enforced_findings(report: Report, level: str) -> list[Finding]:
    """The vulnerability findings the enforcement ``level`` refuses jobs for, most severe first."""
    return [f for f in report.sorted() if f.kind == VULNERABILITY and _refused_at(f.level, level)]


def _added_by_rewrites(report: Report, ref: SourceRef, chars: Iterable[str]) -> frozenset[str]:
    """What the literal rewrites of a source add to a value of it that holds ``chars``."""
    held = frozenset(chars)
    return frozenset().union(*(added for trigger, added in report.rewritten.get(ref, ()) if held & trigger))


def _param_path(ref: SourceRef) -> tuple[str, ...]:
    return tuple(ref.param.split(".")) if ref.param else ()


def find_violations(report: Report, param_dict: dict[str, Any], level: str = CODE) -> Iterator[Violation]:
    """The sources whose job values do what a finding the enforcement ``level`` refuses says, or free other values.

    A finding applies when its own values bring a breakout character (and a required one). And
    when any value of a template can close the quotes it is written in (a finding with a quote
    in ``breakout``, at any severity), the quoting of the rest of the line flips, so every value
    the template writes counts with the characters that do harm in it outside quotes. The
    characters of all values of a source, and of all sources of a finding, count together: a
    template can join them into one string. A backslash escapes the character after it, which is
    template text only after the last one: it counts only when a value ends in an odd number of
    them. Marks (``charsets.marks``) stand for what no character tells, such as a word that starts
    with a dash.
    """
    chars_by_ref: dict[SourceRef, frozenset[str]] = {}

    def chars_of(ref: SourceRef) -> frozenset[str]:
        if ref not in chars_by_ref:
            chars: set[str] = set()
            escapes_template = False
            for value in source_values(ref, param_dict):
                chars.update(value)
                chars.update(marks(value))
                escapes_template = escapes_template or (len(value) - len(value.rstrip("\\"))) % 2 == 1
            if "\r" in chars:
                # Templates turn carriage returns into newlines (replace("\\r", "\\n")).
                chars.add("\n")
            added = _added_by_rewrites(report, ref, chars)
            if not escapes_template:
                chars.discard("\\")
            if "-" in chars and added & WHITESPACE:
                # Added whitespace splits the value into words, one of which can start with its dash.
                chars.add(DASH_WORD)
            chars_by_ref[ref] = frozenset(chars) | added
        return chars_by_ref[ref]

    def own(finding: Finding) -> dict[SourceRef, frozenset[str]]:
        return {ref: chars_of(ref) for ref in finding.refs if ref.accessor != OPAQUE and ref not in finding.unchecked}

    vulnerabilities = [f for f in report.findings if f.kind == VULNERABILITY]
    seen: set[SourceRef] = set()

    def first(violation: Violation) -> bool:
        # One report per source is enough for the log and for the user.
        if violation.ref in seen:
            return False
        seen.add(violation.ref)
        return True

    closers: dict[str, dict[SourceRef, set[str]]] = {}
    for finding in vulnerabilities:
        if not finding.checkable:
            continue
        quotes = finding.closes
        for ref, chars in own(finding).items() if quotes else ():
            if chars & quotes:
                closers.setdefault(finding.location, {}).setdefault(ref, set()).update(chars & quotes)
    for location, by_ref in report.closers.items():
        for ref, quotes in by_ref.items():
            if ref.accessor != OPAQUE and chars_of(ref) & quotes:
                closers.setdefault(location, {}).setdefault(ref, set()).update(chars_of(ref) & quotes)

    for finding in vulnerabilities:
        if not _refused_at(finding.level, level) or not finding.checkable:
            continue
        if finding.needs_closer and not closers.get(finding.location):
            # No value of the job escapes the quote this finding is about.
            continue
        values = own(finding)
        present = frozenset().union(*values.values())
        if not present & finding.breakout or (finding.requires and not present & finding.requires):
            continue
        # Splitting into plain words or closing the quotes alone is refused only at the level of all.
        data_requires = finding.data_requires if level == DATA else frozenset()
        if data_requires and not present & data_requires:
            continue
        wanted = finding.breakout | finding.requires | data_requires
        for ref, chars in values.items():
            violation = Violation(ref, chars & wanted, finding.rule, finding.severity, finding.location)
            if violation.chars and first(violation):
                yield violation

    if level != CODE:
        for location, refs in report.reads.items():
            for ref in refs:
                if ref.accessor == ELEMENT_IDENTIFIER or (ref.accessor == DATASET_ATTRIBUTE and ref.key == "name"):
                    if (harm := _path_like(source_values(ref, param_dict))) and first(
                        violation := Violation(ref, harm, RefusalCode.PATH_LIKE_NAME, MEDIUM, location)
                    ):
                        yield violation

    for location, quoted in closers.items():
        freed = []
        for ref, harm in report.writes.get(location, {}).items():
            if ref.accessor != OPAQUE and chars_of(ref) & harm:
                freed.append(Violation(ref, chars_of(ref) & harm, RefusalCode.STRAY_QUOTE, HIGH, location))
        if freed:
            for ref, closing in quoted.items():
                freed.append(Violation(ref, frozenset(closing), RefusalCode.STRAY_QUOTE, HIGH, location))
            for violation in freed:
                if first(violation):
                    yield violation


def _path_like(names: Iterable[str]) -> frozenset[str]:
    """What makes names a path or an option: a slash, a leading dash or a leading tilde."""
    harm: set[str] = set()
    for name in names:
        if "/" in name:
            harm.add("/")
        if LEADING_DASH in marks(name):
            harm.add(LEADING_DASH)
        if name.lstrip().startswith("~"):
            harm.add("~")
    return frozenset(harm)


def source_values(ref: SourceRef, param_dict: dict[str, Any]) -> Iterator[str]:
    """The strings a template reads from a source in this job."""
    if ref.accessor == SPECIAL:
        if ref.key and (value := param_dict.get(ref.key)) is not None:
            yield str(value)
        return
    if ref.accessor == USER_PREFERENCE:
        if ref.key and (value := _preferences(param_dict).get(ref.key)) is not None:
            yield str(value)
        return
    for value in _resolve(param_dict, _param_path(ref)):
        try:
            yield from _accessor_values(ref, value)
        except Exception as e:
            # A value the wrappers cannot give (an optional input without a dataset) is not written either.
            log.debug("Cannot read %s of input %s: %s", ref.accessor, ref.param, e)


def _resolve(node: Any, path: tuple[str, ...]) -> Iterator[Any]:
    if not path:
        if node is not None:
            yield node
        return
    if isinstance(node, list) and not isinstance(node, DatasetListWrapper):
        # The instances of a repeat.
        for item in node:
            yield from _resolve(item, path)
        return
    if isinstance(node, dict) and path[0] in node:
        yield from _resolve(node[path[0]], path[1:])


def _accessor_values(ref: SourceRef, value: Any) -> Iterator[str]:
    accessor = ref.accessor
    if accessor == TEXT:
        yield str(value)
    elif accessor == RAW:
        raw = value.value if isinstance(value, ToolParameterValueWrapper) else value
        for item in raw if isinstance(raw, (list, tuple)) else [raw]:
            if item is not None:
                yield str(item)
    elif accessor == ELEMENT_IDENTIFIER:
        yield from _identifiers(value)
    elif accessor in (DATASET_ATTRIBUTE, RAW_DATASET_ATTRIBUTE) and ref.key:
        for dataset in _datasets(value):
            attribute = getattr(dataset.unsanitized if accessor == RAW_DATASET_ATTRIBUTE else dataset, ref.key, None)
            if attribute is not None and not callable(attribute):
                yield str(attribute)
    elif accessor in (METADATA, RAW_METADATA) and ref.key:
        for dataset in _datasets(value):
            holder = dataset.unsanitized if accessor == RAW_METADATA else dataset
            metadata = getattr(holder.metadata, ref.key, None)
            if callable(metadata):
                continue
            for item in metadata if isinstance(metadata, (list, tuple)) else [metadata]:
                if item is not None:
                    yield str(item)
    elif accessor == GROUP_TAGS:
        for dataset in _datasets(value):
            yield from (str(group) for group in dataset.groups)
    elif accessor == DATASET_CONTENT:
        for dataset in _datasets(value):
            hda = dataset.unsanitized
            if (hda.get_size() or 0) > CONTENT_LIMIT:
                yield "".join(sorted(PROBE))
                continue
            # The template opens the dataset's path where the job runs, which may not be this host's
            # path (a rewriting compute environment): read the file Galaxy keeps.
            yield from _file_text(hda.get_file_name())


# The most of a dataset the check reads; a bigger one counts as holding every character.
CONTENT_LIMIT = 64 * 1024 * 1024


# The characters a check can look for in a dataset's content: the probe characters, and a carriage
# return, which templates turn into a newline. Each is found with one search of a chunk.
_SCANNED = frozenset(char.encode("ascii") for char in PROBE | {"\r"})


def _file_text(path: str) -> Iterator[str]:
    """What the check needs of a file's text: its characters, ending in the backslashes the file ends in.

    Only a backslash at the file's own end can escape the template text after it. A file that is too
    big or cannot be read counts as holding every character.
    """
    seen: set[bytes] = set()
    ending = b""
    read = 0
    try:
        with open(path, "rb") as fh:
            while chunk := fh.read(1024 * 1024):
                read += len(chunk)
                if read > CONTENT_LIMIT:
                    break
                seen.update(char for char in _SCANNED - seen if char in chunk)
                stripped = chunk.rstrip(b"\\")
                ending = chunk[len(stripped) :] if stripped else ending + chunk
            else:
                seen.discard(b"\\")
                yield b"".join(sorted(seen)).decode("ascii") + ending.decode("ascii")
                return
    except OSError as e:
        log.debug("Cannot read %s: %s", path, e)
    yield "".join(sorted(PROBE))


def _identifiers(value: Any) -> Iterator[str]:
    """Element identifiers at every level, and the name of a collection input, which `$c.name` gives."""
    if isinstance(value, DatasetCollectionWrapper):
        if value.is_input_supplied and value.name is not None:
            yield str(value.name)
        for element in value:
            yield from _identifiers(element)
    elif isinstance(value, DatasetListWrapper):
        for dataset in value:
            yield from _identifiers(dataset)
    elif isinstance(value, DatasetFilenameWrapper) and value:
        yield str(value.element_identifier)


def _datasets(value: Any) -> Iterator[DatasetFilenameWrapper]:
    if isinstance(value, DatasetCollectionWrapper):
        for element in value:
            yield from _datasets(element)
    elif isinstance(value, DatasetListWrapper):
        for dataset in value:
            yield from _datasets(dataset)
    elif isinstance(value, DatasetFilenameWrapper) and value:
        yield value


_DESCRIPTIONS = {
    ELEMENT_IDENTIFIER: "an element identifier or the name of",
    GROUP_TAGS: "a group tag of a dataset of",
    DATASET_CONTENT: "the content of a dataset of",
}


_ACCOUNT_DESCRIPTIONS = {
    "__user_email__": "your email address",
    "userEmail": "your email address",
    "__user_name__": "your user name",
}


def _describe(ref: SourceRef) -> str:
    if ref.accessor == SPECIAL:
        return _ACCOUNT_DESCRIPTIONS.get(ref.key or "", f"the account value {ref.key}")
    if ref.accessor == USER_PREFERENCE:
        return f"your preference '{ref.key}'"
    if ref.accessor in (DATASET_ATTRIBUTE, RAW_DATASET_ATTRIBUTE):
        what = "the name" if ref.key == "name" else f"the {ref.key}"
        return f"{what} of a dataset of input '{ref.param}'"
    if ref.accessor in (METADATA, RAW_METADATA):
        return f"metadata '{ref.key}' of a dataset of input '{ref.param}'"
    return f"{_DESCRIPTIONS.get(ref.accessor, 'the value of')} input '{ref.param}'"


# What the user of a refused job reads: the job carries the values a template reads.
_JOB_WHY = {**WHY, Uncheckable.TEMPLATE_CODE: "its templates run code or read data the job does not carry ({})"}


def _no_plain_value(report: Report | None) -> list[tuple[RefusalCode, str]]:
    """Why no value counts as plain for a tool: the strict check refuses its jobs outright."""
    if report is None:
        return [(RefusalCode.UNCHECKABLE_REVIEW_FAILED, "nothing is known about what its templates do")]
    # Ungated, unlike classify(): a failed check or a stricter level asks with no code-level location unchecked.
    return [(RefusalCode(code.value), why) for code, why in uncheckable_reasons(report, _JOB_WHY).items()]


def strict_violations(
    report: Report, locations: list[str] | None, param_dict: dict[str, Any], level: str = CODE
) -> Iterator[tuple[SourceRef, frozenset[str]]]:
    """The sources the templates read in ``locations`` (all when None) whose job values are not plain at
    the enforcement ``level``, with what keeps them from being plain."""
    refs: dict[SourceRef, None] = {}
    for location in report.reads if locations is None else locations:
        for ref in report.reads.get(location, ()):
            refs.update(dict.fromkeys(_expanded(ref, param_dict)))
    for ref in refs:
        harm: frozenset[str] = frozenset()
        for value in source_values(ref, param_dict):
            added = _added_by_rewrites(report, ref, frozenset(value))
            harm |= strict_harm(value, level) | (added & (_NOT_PLAIN_AT[level] | {"-"}))
            if "-" in value and any(c.isspace() for c in added):
                # Added whitespace splits the value into words, one of which can start with its dash.
                harm |= {"-"}
        if harm:
            yield ref, harm


# The characters a plain value lacks at each enforcement level.
_NOT_PLAIN_AT = {CODE: NOT_PLAIN, DATA: NOT_PLAIN | {"/"}, ALL: NOT_PLAIN | {"/"} | WHITESPACE}


def strict_harm(value: str, level: str = CODE) -> frozenset[str]:
    """What keeps a value from being plain at the enforcement ``level``: beyond the code level, a slash or
    a word that starts with ``~``, and at the level of all, whitespace."""
    harm = not_plain(value) | (frozenset(value) & _NOT_PLAIN_AT[level])
    if level != CODE and TILDE_WORD in marks(value):
        harm |= {"~"}
    return harm


def _expanded(ref: SourceRef, param_dict: dict[str, Any]) -> Iterator[SourceRef]:
    """The source, or for any metadata element or any preference (``key=None``) each one the job has."""
    if ref.accessor == METADATA and ref.key is None:
        keys: dict[str, None] = {}
        for value in _resolve(param_dict, _param_path(ref)):
            for dataset in _datasets(value):
                spec = dataset.unsanitized.metadata.spec
                # A file metadata element holds a path Galaxy makes.
                keys.update(dict.fromkeys(key for key in spec if not isinstance(spec[key].param, FileParameter)))
        yield from (SourceRef(METADATA, ref.param, key) for key in keys)
    elif ref.accessor == USER_PREFERENCE and ref.key is None:
        yield from (SourceRef(USER_PREFERENCE, key=key) for key in _preferences(param_dict))
    else:
        yield ref


def _preferences(param_dict: dict[str, Any]) -> dict[str, Any]:
    """The preferences of the job's user, from the wrapped user object Galaxy puts in the namespace."""
    user = param_dict.get("__user__")
    return getattr(getattr(user, "obj", user), "extra_preferences", None) or {}


def unchecked_message(tool: "Tool", reason: str, why: list[str]) -> str:
    # Galaxy keeps the first 255 characters of a dataset's info: each message starts with what the user can do.
    return (
        f"This job was not run: this Galaxy server cannot check any value for tool '{tool.name}' ({tool.id} version"
        f" {tool.version}). Please contact the administrators of this server. The reason: {reason}, and"
        f" {'; '.join(why)}."
    )


# What a plain value can hold at each enforcement level, for the message of a refused job.
_PLAIN = {
    CODE: "letters, digits, spaces and . _ : / = + @ , ! ^ ~ ? in names and values, and do not start a word with -",
    DATA: "letters, digits, spaces and . _ : = + @ , ! ^ ~ ? in names and values, and do not start a word with - or ~",
    ALL: "letters, digits and . _ : = + @ , ! ^ ~ ? in names and values, and do not start a word with - or ~",
}


def strict_message(
    tool: "Tool", reason: str, harmful: list[tuple[SourceRef, frozenset[str]]], level: str = CODE
) -> str:
    parts = [f"{_describe(ref)} contains [{show(chars)}]" for ref, chars in harmful]
    return (
        f"This job was not run: {', and '.join(parts)}. Use {_PLAIN[level]}, or contact the administrators of"
        f" this server. This Galaxy server allows only plain names and values for tool '{tool.name}' ({tool.id}"
        f" version {tool.version}), because {reason}."
    )


def rejection_message(tool: "Tool", violations: list[Violation]) -> str:
    parts = [f"{_describe(v.ref)} contains the characters [{show(v.chars)}]" for v in violations]
    return (
        f"This job was not run: {', and '.join(parts)}. Tool '{tool.name}' ({tool.id} version {tool.version}) has"
        " a known problem handling these characters in this input, and this Galaxy server does not allow them"
        " there. Rename the dataset or collection element, or change the value, and run the job again."
    )
