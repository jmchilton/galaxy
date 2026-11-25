"""The codes of the refusals of the tool security review, one for each reason a job is refused."""

from enum import Enum


class RefusalCode(str, Enum):
    # A value can leave its place where the template writes it: the rule of the finding.
    SHELL_INJECTION = "shell-injection"
    NESTED_INTERPRETER = "nested-interpreter"
    CONFIGFILE_INJECTION = "configfile-injection"
    STRAY_QUOTE = "stray-quote"
    # From tool_security_review: enforce_data on, a value can stop being the data it is meant to be.
    PATH_TRAVERSAL = "path-traversal"
    OPTION_INJECTION = "option-injection"
    ARGUMENT_INJECTION = "argument-injection"
    # The review cannot judge the job's values, and one of them is not plain.
    NOT_PLAIN_UNCHECKED_PLACE = "not-plain-unchecked-place"
    NOT_PLAIN_CHECK_ERROR = "not-plain-check-error"
    # No value of the job can be checked: it is refused whatever its values.
    UNCHECKABLE_REVIEW_FAILED = "uncheckable-review-failed"
    UNCHECKABLE_REWRITES = "uncheckable-rewrites"
    UNCHECKABLE_TEMPLATE_CODE = "uncheckable-template-code"
    UNCHECKABLE_LETTERS_ARE_CODE = "uncheckable-letters-are-code"
    UNCHECKABLE_UNTRACED_VALUE = "uncheckable-untraced-value"
    UNCHECKABLE_STRICT_CHECK_ERROR = "uncheckable-strict-check-error"
    UNCHECKABLE_WHEN_UNSURE = "uncheckable-when-unsure"


DESCRIPTIONS = {
    RefusalCode.SHELL_INJECTION: "A value can close the quotes around it, or is written unquoted, and start another"
    " shell command.",
    RefusalCode.NESTED_INTERPRETER: "A value is written into the program of another interpreter (`bash -c`, `sed`,"
    " `perl -e`, ...) and can change what that program does.",
    RefusalCode.CONFIGFILE_INJECTION: "A value is written into a configfile that a script runs and can end its"
    " string and add code.",
    RefusalCode.STRAY_QUOTE: "A quote in one value is harmless by itself but flips the quoting of the rest of the"
    " line, which leaves the command characters of another value unquoted.",
    RefusalCode.PATH_TRAVERSAL: "A value is written as a path a command writes or reads (a redirection, an"
    " argument of `cp`, `ln`, `mv`, ...) and can name a file outside the job's directory. Refused from"
    " `enforce_data` on.",
    RefusalCode.OPTION_INJECTION: "A value starts an argument and can begin with a dash, so the command reads it"
    " as an option. Refused from `enforce_data` on.",
    RefusalCode.ARGUMENT_INJECTION: "A value is written unquoted, or can close its quotes, and can split into"
    " more words. From `enforce_data` on, a job is refused when a word can then be an option, a home directory,"
    " a path or a glob; with `enforce_all`, also when the words are plain or the value only closes its quotes.",
    RefusalCode.NOT_PLAIN_UNCHECKED_PLACE: "The tool writes values in places the review cannot judge (parts of the"
    " template it did not follow, or values it cannot trace), and a value is not plain.",
    RefusalCode.NOT_PLAIN_CHECK_ERROR: "Comparing the job's values with the review's findings failed (a bug), so"
    " the job got the strict check instead, and a value is not plain.",
    RefusalCode.UNCHECKABLE_REVIEW_FAILED: "The review of the tool failed, so nothing is known about what its"
    " templates do.",
    RefusalCode.UNCHECKABLE_REWRITES: "The templates change values in ways that can bring back characters the"
    " sanitizer took out (`chr()`, a decoder, a `.replace` or `re.sub` of the sanitizer's tokens, of text that is"
    " not literal, or of a value template code changed before). A literal rewrite of a value as the job carries"
    " it is checked with each job.",
    RefusalCode.UNCHECKABLE_TEMPLATE_CODE: "The templates run Python that can read text the job does not carry"
    " (imports, `open()`, `$__app__`, the models behind `.unsanitized`).",
    RefusalCode.UNCHECKABLE_LETTERS_ARE_CODE: "Letters alone can be code where the tool writes a value: the program"
    " to run, text piped to a shell that runs it (not one that runs a script file), or unquoted Perl or Ruby code.",
    RefusalCode.UNCHECKABLE_UNTRACED_VALUE: "The templates write a value the review cannot trace to one input or"
    " preference (the user object read in a loop, a conditional built at run time), so no check sees it.",
    RefusalCode.UNCHECKABLE_STRICT_CHECK_ERROR: "The strict check itself failed (a bug), so none of the job's"
    " values could be checked.",
    RefusalCode.UNCHECKABLE_WHEN_UNSURE: "The review cannot check the job, and the server refuses every such job"
    " (`tool_security_review_when_unsure: refuse`) instead of checking its values strictly.",
}
