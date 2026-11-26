"""The codes of the refusals of the tool security review, one for each reason a job is refused.

A refusal for a finding has the finding's rule (:class:`~.rules.Rule`), and one for a tool the review
cannot check has its :class:`~.classify.Uncheckable` code; the others exist only where jobs are checked.
"""

from enum import StrEnum

from .classify import (
    DESCRIPTIONS as UNCHECKABLE_DESCRIPTIONS,
    Uncheckable,
)
from .rules import (
    DESCRIPTIONS as RULE_DESCRIPTIONS,
    Rule,
)


class RefusalCode(StrEnum):
    # A value can leave its place where the template writes it: the rule of the finding.
    SHELL_INJECTION = Rule.SHELL_INJECTION.value
    NESTED_INTERPRETER = Rule.NESTED_INTERPRETER.value
    CONFIGFILE_INJECTION = Rule.CONFIGFILE_INJECTION.value
    STRAY_QUOTE = "stray-quote"
    # From tool_security_review: enforce_data on, a value can stop being the data it is meant to be.
    PATH_TRAVERSAL = Rule.PATH_TRAVERSAL.value
    OPTION_INJECTION = Rule.OPTION_INJECTION.value
    ARGUMENT_INJECTION = Rule.ARGUMENT_INJECTION.value
    PATH_LIKE_NAME = "path-like-name"
    # The review cannot judge the job's values, and one of them is not plain.
    NOT_PLAIN_UNCHECKED_PLACE = "not-plain-unchecked-place"
    NOT_PLAIN_CHECK_ERROR = "not-plain-check-error"
    # No value of the job can be checked: it is refused whatever its values.
    UNCHECKABLE_REVIEW_FAILED = Uncheckable.REVIEW_FAILED.value
    UNCHECKABLE_REWRITES = Uncheckable.REWRITES.value
    UNCHECKABLE_TEMPLATE_CODE = Uncheckable.TEMPLATE_CODE.value
    UNCHECKABLE_LETTERS_ARE_CODE = Uncheckable.LETTERS_ARE_CODE.value
    UNCHECKABLE_UNTRACED_VALUE = Uncheckable.UNTRACED_VALUE.value
    UNCHECKABLE_STRICT_CHECK_ERROR = "uncheckable-strict-check-error"
    UNCHECKABLE_WHEN_UNSURE = "uncheckable-when-unsure"


_FROM_ENFORCE_DATA = " Refused from `enforce_data` on."

DESCRIPTIONS = {
    RefusalCode.SHELL_INJECTION: RULE_DESCRIPTIONS[Rule.SHELL_INJECTION],
    RefusalCode.NESTED_INTERPRETER: RULE_DESCRIPTIONS[Rule.NESTED_INTERPRETER],
    RefusalCode.CONFIGFILE_INJECTION: RULE_DESCRIPTIONS[Rule.CONFIGFILE_INJECTION],
    RefusalCode.STRAY_QUOTE: "A quote in one value is harmless by itself but flips the quoting of the rest of the"
    " line, which leaves the command characters of another value unquoted.",
    RefusalCode.PATH_TRAVERSAL: RULE_DESCRIPTIONS[Rule.PATH_TRAVERSAL] + _FROM_ENFORCE_DATA,
    RefusalCode.OPTION_INJECTION: RULE_DESCRIPTIONS[Rule.OPTION_INJECTION] + _FROM_ENFORCE_DATA,
    RefusalCode.ARGUMENT_INJECTION: "A value is written unquoted, or can close its quotes, and can split into"
    " more words. From `enforce_data` on, a job is refused when a word can then be an option, a home directory,"
    " a path or a glob; with `enforce_all`, also when the words are plain or the value only closes its quotes.",
    RefusalCode.PATH_LIKE_NAME: "An element identifier or a dataset name that a template writes contains `/` or"
    " starts with `-` or `~`. Tools use names as file names and arguments in ways the review does not follow"
    " (a program's own options, paths in R or Python), where such a name is a path or an option." + _FROM_ENFORCE_DATA,
    RefusalCode.NOT_PLAIN_UNCHECKED_PLACE: "The tool writes values in places the review cannot judge (parts of the"
    " template it did not follow, or values it cannot trace), and a value is not plain.",
    RefusalCode.NOT_PLAIN_CHECK_ERROR: "Comparing the job's values with the review's findings failed (a bug), so"
    " the job got the strict check instead, and a value is not plain.",
    RefusalCode.UNCHECKABLE_REVIEW_FAILED: "The review of the tool failed, so nothing is known about what its"
    " templates do.",
    RefusalCode.UNCHECKABLE_REWRITES: UNCHECKABLE_DESCRIPTIONS[Uncheckable.REWRITES]
    + " A literal rewrite of a value as the job carries it is checked with each job.",
    RefusalCode.UNCHECKABLE_TEMPLATE_CODE: UNCHECKABLE_DESCRIPTIONS[Uncheckable.TEMPLATE_CODE],
    RefusalCode.UNCHECKABLE_LETTERS_ARE_CODE: UNCHECKABLE_DESCRIPTIONS[Uncheckable.LETTERS_ARE_CODE],
    RefusalCode.UNCHECKABLE_UNTRACED_VALUE: UNCHECKABLE_DESCRIPTIONS[Uncheckable.UNTRACED_VALUE],
    RefusalCode.UNCHECKABLE_STRICT_CHECK_ERROR: "The strict check itself failed (a bug), so none of the job's"
    " values could be checked.",
    RefusalCode.UNCHECKABLE_WHEN_UNSURE: "The review cannot check the job, and the server refuses every such job"
    " (`tool_security_review_when_unsure: refuse`) instead of checking its values strictly.",
}
