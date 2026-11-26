"""What a review cannot decide from a tool's templates alone.

:func:`classify` reads only a :class:`~.report.Report`. Its unchecked locations are templates whose values
no character test of a finding can judge, so only a check that every value is plain could. Its codes say
why not even that could: the review does not vet the tool.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import (
    dataclass,
    field,
)
from enum import StrEnum

from .charsets import CODE
from .patterns import access_patterns
from .report import (
    OPAQUE,
    rendered,
    Report,
    RUNS_TEXT_RULES,
    serious_findings,
    VULNERABILITY,
)
from .rules import Rule


class Uncheckable(StrEnum):
    # Set by callers for a path the review did not run on; classify() never returns it.
    REVIEW_FAILED = "uncheckable-review-failed"
    REWRITES = "uncheckable-rewrites"
    TEMPLATE_CODE = "uncheckable-template-code"
    LETTERS_ARE_CODE = "uncheckable-letters-are-code"
    UNTRACED_VALUE = "uncheckable-untraced-value"


DESCRIPTIONS = {
    Uncheckable.REVIEW_FAILED: "The review did not run: the tool could not be loaded or reviewed, it is not an XML"
    " tool, or a directory held no tools. Nothing is known about what the templates do.",
    Uncheckable.REWRITES: "The templates change values in ways that can bring back characters the sanitizer took"
    " out (`chr()`, a decoder, a `.replace` or `re.sub` of the sanitizer's tokens, of text that is not literal, or"
    " of a value template code changed before).",
    Uncheckable.TEMPLATE_CODE: "The templates run Python that can read text no tool input carries (imports,"
    " `open()`, `#include` of anything but a template macro, a lambda that reads more than its arguments or changes"
    " a value, `$__app__`, `getattr`, what the dataset model behind `.unsanitized` reaches).",
    Uncheckable.LETTERS_ARE_CODE: "Letters alone can be code where the tool writes a value: the program to run,"
    " text piped to a shell that runs it, or unquoted Perl or Ruby code.",
    Uncheckable.UNTRACED_VALUE: "The templates write a value the review cannot trace to one input or preference"
    " (the user object read in a loop, a conditional built at run time).",
}

# Why a location is unchecked, beyond the reasons of Report.unchecked_locations.
NOT_CHECKABLE = "a finding there is not decided by the characters of a value"
READS_BY_NAME = "it reads objects by name"


@dataclass(frozen=True)
class Classification:
    """The uncheckable codes of a review, each with why, and the locations no character test can judge."""

    reasons: dict[Uncheckable, str] = field(default_factory=dict)
    unchecked_locations: dict[str, str] = field(default_factory=dict)

    @property
    def codes(self) -> list[Uncheckable]:
        return sorted(self.reasons)


# Why each code applies, filled with what the review found (uncheckable_evidence), joined by commas.
WHY = {
    Uncheckable.REWRITES: "its templates change values with {}",
    Uncheckable.TEMPLATE_CODE: "its templates run code or read data no input carries ({})",
    Uncheckable.LETTERS_ARE_CODE: "letters alone can be code where it writes values ({})",
    Uncheckable.UNTRACED_VALUE: "it writes values it cannot trace to an input ({})",
}


def classify(report: Report) -> Classification:
    """What the review cannot decide from the templates of the tool it reviewed."""
    unchecked = unchecked_locations(report)
    if not unchecked:
        # Every finding is decided by the characters of a value.
        return Classification()
    return Classification(uncheckable_reasons(report), unchecked)


def uncheckable_reasons(report: Report, why: Mapping[Uncheckable, str] = WHY) -> dict[Uncheckable, str]:
    """The codes of :func:`uncheckable_evidence`, each with ``why`` filled with its evidence."""
    return {code: why[code].format(", ".join(found)) for code, found in uncheckable_evidence(report).items()}


def uncheckable_evidence(report: Report) -> dict[Uncheckable, list[str]]:
    """Each reason no value of the tool counts as plain, with what shows it, whether or not a location is unchecked."""
    evidence: dict[Uncheckable, list[str]] = {}
    if rewrites := sorted({name for found in report.rewrites.values() for name in found}):
        evidence[Uncheckable.REWRITES] = rewrites
    capabilities = sorted(
        {
            f.expr
            for found in access_patterns(report).values()
            for f in found
            # Reflection in an output filter or an option list cannot write into what the job runs.
            if f.expr and not (f.rule == Rule.TEMPLATE_REFLECTION and not rendered(f.location))
        }
    )
    if capabilities:
        evidence[Uncheckable.TEMPLATE_CODE] = capabilities
    serious = serious_findings(report)
    runs = {f.location for f in report.findings if f.rule in RUNS_TEXT_RULES}
    runs |= {f.location for f in serious if not (f.breakout or f.closes)}
    if runs:
        evidence[Uncheckable.LETTERS_ARE_CODE] = sorted(runs)
    if untraced := sorted(
        {f.location for f in serious if any(ref.accessor == OPAQUE and ref.param is None for ref in f.refs)}
    ):
        evidence[Uncheckable.UNTRACED_VALUE] = untraced
    return evidence


def unchecked_locations(report: Report) -> dict[str, str]:
    """The locations no character test of a code-level finding can judge, with why."""
    unchecked = dict(report.unchecked_locations)
    for f in report.findings:
        if f.kind == VULNERABILITY and f.level == CODE and not f.checkable:
            unchecked.setdefault(f.location, NOT_CHECKABLE)
        elif f.rule == Rule.TEMPLATE_REFLECTION and rendered(f.location):
            # A template that reads objects by name can write any value without a finding about it.
            unchecked.setdefault(f.location, READS_BY_NAME)
    return dict(sorted(unchecked.items()))
