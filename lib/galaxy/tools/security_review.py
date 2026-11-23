"""Review the templates of tools and check the values of jobs against the reviews.

The review (:mod:`galaxy.tool_util.security`) finds places where a value a user controls can leave
the quotes or the argument it is written into. A process that prepares jobs reviews a tool when it
prepares the tool's first job and keeps the review as long as it keeps the tool: a reloaded tool is
a new object and is reviewed again. A review takes a few milliseconds and at most about two seconds
of CPU for the largest templates known; it has no time limit, since it runs once per tool and process,
and the analyser's step budget bounds the work on any one template. It is never stored.

Before a job's command line is built, :meth:`ToolSecurityReviewer.check_job` compares the values of
the job's inputs with the tool's high and critical findings: a value that contains a character that
can leave its place is logged (``log``) or fails the job (``enforce``).

A job that the review cannot check (no review, a finding no character test can decide, an error in
the check) gets a stricter check instead, unless ``strict_when_unsure`` is off: every value the job carries must be
plain, without a character that can leave its place anywhere. A template that changes values
(``open()``, ``decode``, ``chr()``, a ``.replace`` that brings such a character) makes even plain
values unsafe, so such a job is refused outright.
"""

import ast
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import (
    Any,
    Iterator,
    Optional,
    TYPE_CHECKING,
)
from weakref import WeakKeyDictionary

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
    CRITICAL,
    HIGH,
    PROBE,
    show,
)
from galaxy.tool_util.security.report import (
    DATASET_ATTRIBUTE,
    DATASET_CONTENT,
    ELEMENT_IDENTIFIER,
    GROUP_TAGS,
    METADATA,
    OPAQUE,
    RAW,
    SPECIAL,
    TEXT,
    USER_PREFERENCE,
    VULNERABILITY,
)
from galaxy.tools.wrappers import (
    DatasetCollectionWrapper,
    DatasetFilenameWrapper,
    DatasetListWrapper,
    ToolParameterValueWrapper,
)
from galaxy.util import mapped_chars

if TYPE_CHECKING:
    from galaxy.tools import Tool
    from galaxy.tools.evaluation import ToolEvaluator

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


class ToolInputRejected(Exception):
    """The tool security review refuses a job: an input value can leave its place, or the job cannot be checked."""


@dataclass(frozen=True)
class ToolReview:
    """The outcome of reviewing one tool."""

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
        return [f for f in self._serious if f.checkable]

    @property
    def unchecked_findings(self) -> list[Finding]:
        """High and critical findings no character test on job values can decide."""
        return [f for f in self._serious if not f.checkable]

    @property
    def unchecked_locations(self) -> dict[str, str]:
        """Templates whose values no character test can judge, with the reason."""
        return self.report.unchecked_locations if self.report is not None else {}

    @property
    def _serious(self) -> list[Finding]:
        if self.report is None:
            return []
        return [f for f in self.report.findings if f.kind == VULNERABILITY and f.severity in CHECKED_SEVERITIES]


def reviewed_tool_source(tool: "Tool") -> Optional[ToolSource]:
    """The source the review reads: the tool as parsed, macros expanded; None for a tool without a template."""
    if tool.tool_type_local or tool.tool_type in _UNREVIEWED_TOOL_TYPES or not tool.command:
        return None
    source = tool.tool_source
    if not isinstance(source, (XmlToolSource, YamlToolSource)):
        return None
    return source


class ToolSecurityReviewer:
    """Reviews tools when their jobs are prepared, and checks job values against the reviews."""

    def __init__(self, mode: str, strict_when_unsure: bool = True) -> None:
        if mode not in MODES:
            raise ValueError(f"tool_security_review must be one of {', '.join(MODES)}, not '{mode}'")
        self.mode = mode
        # Check a job the review cannot check with the strict character set.
        self.strict_when_unsure = strict_when_unsure
        # Keyed by the Tool object: a review lives as long as the tool it is about.
        self._reviews: WeakKeyDictionary[Tool, ToolReview] = WeakKeyDictionary()
        self._tool_locks: WeakKeyDictionary[Tool, threading.Lock] = WeakKeyDictionary()
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, config: Any) -> "ToolSecurityReviewer":
        return cls(
            mode=config.tool_security_review,
            strict_when_unsure=bool(config.tool_security_review_strict_when_unsure),
        )

    @property
    def enabled(self) -> bool:
        return self.mode != OFF

    # -- reviews -------------------------------------------------------------------------------

    def review(self, tool: "Tool") -> Optional[ToolReview]:
        """The review of a tool, computed on first use.

        None when reviews are off or the tool has no template to review.
        """
        if not self.enabled:
            return None
        try:
            tool_source = reviewed_tool_source(tool)
        except Exception as e:
            log.warning("Cannot review tool %s for security: %s", tool.id, e)
            return ToolReview(NOT_ANALYSED, tool.id, tool.version, reason=f"error: {type(e).__name__}")
        if tool_source is None:
            return None
        if (review := self._reviews.get(tool)) is not None:
            return review
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
        in ``enforce`` mode.
        """
        if not self.enabled:
            return
        review = self.review(tool)
        job_id = evaluator.job.id
        if review is None:
            return
        if review.status != ANALYSED or review.report is None:
            self._cannot_check(tool, evaluator, "the security review of this tool failed")
            return
        violations: list[Violation] = []
        if review.checked_findings or review.report.writes:
            # Reading element identifiers and names through the wrappers marks the job as consuming
            # them, which changes how the job cache matches it; the check must not.
            consumes = (evaluator.consumes_names, evaluator.consumes_identifiers)
            try:
                violations = list(find_violations(review.report, evaluator.param_dict))
            except Exception:
                # Without strict_when_unsure, the check must never be the reason a job fails.
                log.exception("Job %s: checking values against the security review of tool %s failed", job_id, tool.id)
                self._cannot_check(tool, evaluator, "checking the job's values against the security review failed")
                return
            finally:
                evaluator.consumes_names, evaluator.consumes_identifiers = consumes
        for violation in violations:
            log.warning(
                "Tool security review: job %s of tool %s version %s: %s of input '%s' contains [%s],"
                " which can leave its place in the %s (%s, %s)",
                job_id,
                tool.id,
                tool.version,
                violation.ref.accessor + (f" '{violation.ref.key}'" if violation.ref.key else ""),
                violation.ref.param or violation.ref.key,
                show(violation.chars),
                violation.location,
                violation.rule,
                violation.severity,
            )
        if violations and self.mode == ENFORCE:
            raise ToolInputRejected(rejection_message(tool, violations))
        unchecked = sorted({f.location for f in review.unchecked_findings} | set(review.unchecked_locations))
        if unchecked and not violations:
            self._cannot_check(
                tool,
                evaluator,
                f"this tool writes values in places that no check of their characters can judge ({', '.join(unchecked)})",
            )

    def _cannot_check(self, tool: "Tool", evaluator: "ToolEvaluator", reason: str) -> None:
        """A job the review cannot judge: its values must all be plain, unless strict_when_unsure is off."""
        job_id = evaluator.job.id
        if not self.strict_when_unsure:
            log.debug("Job %s of tool %s: values are not checked, %s", job_id, tool.id, reason)
            return
        if transforms := template_transforms(tool):
            log.warning(
                "Tool security review: job %s of tool %s version %s cannot be checked, %s, and the template changes"
                " values (%s)",
                job_id,
                tool.id,
                tool.version,
                reason,
                ", ".join(transforms),
            )
            if self.mode == ENFORCE:
                raise ToolInputRejected(unchecked_message(tool, reason, transforms))
            return
        consumes = (evaluator.consumes_names, evaluator.consumes_identifiers)
        try:
            harmful = list(strict_violations(tool, evaluator.param_dict))
        finally:
            evaluator.consumes_names, evaluator.consumes_identifiers = consumes
        if not harmful:
            log.debug("Job %s of tool %s: %s, and every value is plain", job_id, tool.id, reason)
            return
        for description, chars in harmful:
            log.warning(
                "Tool security review: job %s of tool %s version %s cannot be checked, %s, and %s contains [%s]",
                job_id,
                tool.id,
                tool.version,
                reason,
                description,
                show(chars),
            )
        if self.mode == ENFORCE:
            raise ToolInputRejected(strict_message(tool, reason, harmful))


@dataclass(frozen=True)
class Violation:
    ref: SourceRef
    chars: frozenset[str]
    rule: str
    severity: str
    location: str


# The rule of a value that a stray quote of another value leaves outside its quotes.
STRAY_QUOTE = "stray-quote"


def find_violations(report: Report, param_dict: dict[str, Any]) -> Iterator[Violation]:
    """The sources whose job values do what a high or critical finding says, or free other values.

    A finding applies when its own values bring a breakout character (and a required one). And
    when any value of a template can close the quotes it is written in (a finding with a quote
    in ``breakout``, at any severity), the quoting of the rest of the line flips, so every value
    the template writes counts with the characters that do harm in it outside quotes. The
    characters of all values of a source, and of all sources of a finding, count together: a
    template can join them into one string. A backslash escapes the character after it, which is
    template text only after the last one: it counts only when a value ends in an odd number of
    them.
    """
    chars_by_ref: dict[SourceRef, frozenset[str]] = {}

    def chars_of(ref: SourceRef) -> frozenset[str]:
        if ref not in chars_by_ref:
            chars: set[str] = set()
            escapes_template = False
            for value in source_values(ref, param_dict):
                chars.update(value)
                escapes_template = escapes_template or (len(value) - len(value.rstrip("\\"))) % 2 == 1
            if "\r" in chars:
                # Templates turn carriage returns into newlines (replace("\\r", "\\n")).
                chars.add("\n")
            if not escapes_template:
                chars.discard("\\")
            chars_by_ref[ref] = frozenset(chars)
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
        if finding.severity not in CHECKED_SEVERITIES or not finding.checkable:
            continue
        if finding.needs_closer and not closers.get(finding.location):
            # No value of the job escapes the quote this finding is about.
            continue
        values = own(finding)
        present = frozenset().union(*values.values())
        if not present & finding.breakout or (finding.requires and not present & finding.requires):
            continue
        wanted = finding.breakout | finding.requires
        for ref, chars in values.items():
            violation = Violation(ref, chars & wanted, finding.rule, finding.severity, finding.location)
            if violation.chars and first(violation):
                yield violation

    for location, quoted in closers.items():
        freed = []
        for ref, harm in report.writes.get(location, {}).items():
            if ref.accessor != OPAQUE and chars_of(ref) & harm:
                freed.append(Violation(ref, chars_of(ref) & harm, STRAY_QUOTE, HIGH, location))
        if freed:
            for ref, closing in quoted.items():
                freed.append(Violation(ref, frozenset(closing), STRAY_QUOTE, HIGH, location))
            for violation in freed:
                if first(violation):
                    yield violation


def source_values(ref: SourceRef, param_dict: dict[str, Any]) -> Iterator[str]:
    """The strings a template reads from a source in this job."""
    if ref.accessor == SPECIAL:
        if ref.key and (value := param_dict.get(ref.key)) is not None:
            yield str(value)
        return
    if ref.accessor == USER_PREFERENCE:
        user = param_dict.get("__user__")
        preferences = getattr(getattr(user, "obj", user), "extra_preferences", None) or {}
        if ref.key and (value := preferences.get(ref.key)) is not None:
            yield str(value)
        return
    for value in _resolve(param_dict, ref.param_path):
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
    elif accessor == DATASET_ATTRIBUTE and ref.key:
        for dataset in _datasets(value):
            attribute = getattr(dataset, ref.key, None)
            if attribute is not None and not callable(attribute):
                yield str(attribute)
    elif accessor == METADATA and ref.key:
        for dataset in _datasets(value):
            metadata = getattr(dataset.metadata, ref.key, None)
            for item in metadata if isinstance(metadata, (list, tuple)) else [metadata]:
                if item is not None:
                    yield str(item)
    elif accessor == GROUP_TAGS:
        for dataset in _datasets(value):
            yield from (str(group) for group in dataset.groups)
    elif accessor == DATASET_CONTENT:
        for dataset in _datasets(value):
            # The path the template opens.
            yield from _file_text(str(dataset))


# The most of a dataset the check reads; a bigger one counts as holding every character.
CONTENT_LIMIT = 64 * 1024 * 1024


def _file_text(path: str) -> Iterator[str]:
    read = 0
    with open(path, "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            read += len(chunk)
            if read > CONTENT_LIMIT:
                yield "".join(sorted(PROBE))
                return
            yield chunk.decode("utf-8", errors="replace")


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
    TEXT: "the value of",
    RAW: "the value of",
    ELEMENT_IDENTIFIER: "an element identifier or the name of",
    GROUP_TAGS: "a group tag of a dataset of",
    DATASET_CONTENT: "the content of a dataset of",
}


def _describe(ref: SourceRef) -> str:
    if ref.accessor == SPECIAL:
        return f"the account value {ref.key}"
    if ref.accessor == USER_PREFERENCE:
        return f"your preference '{ref.key}'"
    if ref.accessor == DATASET_ATTRIBUTE:
        what = "the name" if ref.key == "name" else f"the {ref.key}"
        return f"{what} of a dataset of input '{ref.param}'"
    if ref.accessor == METADATA:
        return f"metadata '{ref.key}' of a dataset of input '{ref.param}'"
    return f"{_DESCRIPTIONS.get(ref.accessor, 'the value of')} input '{ref.param}'"


# Characters that can leave a value's place somewhere: in the shell, in a string of a program, or
# unquoted in Python or R code, where a call needs no quotes (eval(chr(105) + chr(100))). Not "?":
# it is Galaxy's unknown dbkey, and in the shell it only globs.
STRICT_DENIED = frozenset("'\"`$;&|<>\\\n\r\t(){}[]%#*")
# Galaxy's sanitizer writes these for the characters it maps; templates often turn them back.
_SANITIZER_TOKENS = re.compile("|".join(re.escape(token) for token in sorted(set(mapped_chars.values()))))
# A word that starts with a dash can be read as an option.
_OPTION_WORD = re.compile(r"(?:^|\s)-")
# Template code that can make a plain value unsafe, or read text the job does not carry.
_TRANSFORMS = re.compile(
    r"\bopen\s*\(|decode|b64|\b(?:uni)?chr\s*\(|unquote|\beval\s*\(|\bexec\s*\(|__import__|fromhex"
    r"|\btranslate\s*\(|%c|__app__|creating_job|\bgetVar\s*\(|\bcompile\s*\(|subprocess|os\.popen|os\.system"
)


def _template_texts(tool: "Tool") -> list[str]:
    texts = [tool.command or ""]
    texts.extend(content for cf in tool.config_files if isinstance(content := getattr(cf, "content", None), str))
    texts.extend(text for text in tool.template_macro_params.values() if text)
    return texts


def template_transforms(tool: "Tool") -> list[str]:
    """What in the tool's templates can turn a plain value into an unsafe one."""
    found: set[str] = set()
    for text in _template_texts(tool):
        found.update(re.sub(r"[\s(]+", "", match.group(0)) for match in _TRANSFORMS.finditer(text))
        if _unsafe_replace(text):
            found.add(".replace")
    return sorted(found)


def _unsafe_replace(text: str) -> bool:
    """A ``.replace`` whose new text is not a plain literal: it can bring what the strict check refuses."""
    for match in re.finditer(r"\.replace\s*\(", text):
        args = _call_arguments(text, match.end())
        if args is None:
            return True
        try:
            call = ast.parse(f"f({args.replace('$', '')})", mode="eval").body
        except SyntaxError:
            return True
        if not isinstance(call, ast.Call) or len(call.args) < 2:
            return True
        new = call.args[1]
        if not (isinstance(new, ast.Constant) and isinstance(new.value, str)):
            return True
        if _strict_harm(new.value) or "-" in new.value or any(c.isspace() for c in new.value):
            return True
    return False


def _call_arguments(text: str, start: int) -> Optional[str]:
    depth, quote, i = 1, "", start
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = ""
        elif c in "'\"":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return None


def _strict_harm(value: str) -> frozenset[str]:
    harm = set(value) & STRICT_DENIED
    if _OPTION_WORD.search(value):
        harm.add("-")
    harm.update(_SANITIZER_TOKENS.findall(value))
    return frozenset(harm)


def strict_violations(tool: "Tool", param_dict: dict[str, Any]) -> Iterator[tuple[str, frozenset[str]]]:
    """The values of a job that are not plain, with what makes them unsafe."""
    words = frozenset(word for text in _template_texts(tool) for word in re.findall(r"\w+", text))
    for description, value in _job_values(tool, param_dict, words):
        if harm := _strict_harm(value):
            yield description, harm


def _job_values(tool: "Tool", param_dict: dict[str, Any], words: frozenset[str]) -> Iterator[tuple[str, str]]:
    """The values a user controls that the job carries, described for the user.

    Element identifiers, dataset names and parameter values always count. A dataset attribute, tag,
    metadata element or user preference counts when the templates name it (``words``): these often
    hold text such as a tool's output summary, and a template reads them only by name.
    """
    for name in tool.inputs:
        if name in param_dict:
            yield from _values_of(name, param_dict[name], words)
    if "extra_preferences" not in words:
        return
    user = param_dict.get("__user__")
    preferences = getattr(getattr(user, "obj", user), "extra_preferences", None) or {}
    for key, value in preferences.items():
        if value is not None:
            yield f"your preference '{key}'", str(value)


def _values_of(path: str, value: Any, words: frozenset[str]) -> Iterator[tuple[str, str]]:
    if isinstance(value, (DatasetCollectionWrapper, DatasetListWrapper, DatasetFilenameWrapper)):
        for identifier in _identifiers(value):
            yield f"an element identifier or the name of input '{path}'", identifier
        for dataset in _datasets(value):
            yield from _dataset_values(path, dataset, words)
    elif isinstance(value, ToolParameterValueWrapper):
        raw = getattr(value, "value", None)
        for item in raw if isinstance(raw, (list, tuple)) else [raw]:
            if isinstance(item, str):
                yield f"the value of input '{path}'", item
    elif isinstance(value, dict):
        for key, item in value.items():
            if not key.startswith("__"):
                yield from _values_of(f"{path}.{key}", item, words)
    elif isinstance(value, list):
        for item in value:
            yield from _values_of(path, item, words)
    elif isinstance(value, str):
        yield f"the value of input '{path}'", value


def _dataset_values(path: str, dataset: DatasetFilenameWrapper, words: frozenset[str]) -> Iterator[tuple[str, str]]:
    hda = dataset.unsanitized
    for attribute in ("name", "info", "created_from_basename", "dbkey"):
        if (attribute == "name" or attribute in words) and isinstance(text := getattr(hda, attribute, None), str):
            yield f"the {attribute} of a dataset of input '{path}'", text
    if words & {"tags", "tag", "groups", "group"}:
        for tag in getattr(hda, "tags", None) or []:
            yield f"a tag of a dataset of input '{path}'", f"{tag.user_tname}:{tag.user_value or ''}"
    if "metadata" not in words:
        return
    try:
        metadata = hda.metadata
        # A template that looks metadata up by a computed name can read any of it.
        every = "getattr" in words or "items" in words
        for key in metadata.spec:
            if not (every or key in words):
                continue
            item = metadata.get(key)
            for text in item if isinstance(item, (list, tuple)) else [item]:
                if isinstance(text, str):
                    yield f"metadata '{key}' of a dataset of input '{path}'", text
    except Exception as e:
        log.debug("Cannot read the metadata of a dataset of input %s: %s", path, e)


def unchecked_message(tool: "Tool", reason: str, transforms: list[str]) -> str:
    return (
        f"This job was not run: {reason}, and its templates can change values ({', '.join(transforms)}), so this"
        f" Galaxy server cannot check any value for tool '{tool.name}' ({tool.id} version {tool.version})."
        " Please contact the administrators of this server."
    )


def strict_message(tool: "Tool", reason: str, harmful: list[tuple[str, frozenset[str]]]) -> str:
    parts = [f"{description} contains [{show(chars)}]" for description, chars in harmful]
    return (
        f"This job was not run: {reason}, so this Galaxy server allows only plain names and values for tool"
        f" '{tool.name}' ({tool.id} version {tool.version}), and {', and '.join(parts)}. Use letters, digits,"
        " spaces and . _ : / = + @ , ! ^ ~ ? in names and values, and do not start a word with -, or contact the"
        " administrators of this server."
    )


def rejection_message(tool: "Tool", violations: list[Violation]) -> str:
    parts = [f"{_describe(v.ref)} contains the characters [{show(v.chars)}]" for v in violations]
    return (
        f"This job was not run: {', and '.join(parts)}. Tool '{tool.name}' ({tool.id} version {tool.version}) has"
        " a known problem handling these characters in this input, and this Galaxy server does not allow them"
        " there. Rename the dataset or collection element, or change the value, and run the job again."
    )
