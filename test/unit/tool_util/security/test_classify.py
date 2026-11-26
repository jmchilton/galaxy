"""What the review cannot decide from a tool's templates alone."""

import pytest

from galaxy.tool_util.security.classify import (
    classify,
    DESCRIPTIONS,
    NOT_CHECKABLE,
    READS_BY_NAME,
    Uncheckable,
)
from galaxy.tool_util.security.report import RUNS_TEXT
from ._util import review


def test_plain_quoted_text_is_decidable(tmp_path):
    result = classify(review(tmp_path, "tool '$text'"))
    assert result.codes == []
    assert result.unchecked_locations == {}


def test_codes_need_an_unchecked_location(tmp_path):
    assert classify(review(tmp_path, "#import subprocess\ntool '$text'")).codes == []
    result = classify(review(tmp_path, "#import subprocess\necho '$text' | bash"))
    assert result.codes == [Uncheckable.LETTERS_ARE_CODE, Uncheckable.TEMPLATE_CODE]
    assert "subprocess" in result.reasons[Uncheckable.TEMPLATE_CODE]


def test_rewrites_name_the_rewriting_code(tmp_path):
    result = classify(review(tmp_path, "echo '${str($text).replace('__sq__', chr(39))}' | bash"))
    assert Uncheckable.REWRITES in result.codes
    assert "chr" in result.reasons[Uncheckable.REWRITES]


def test_user_object_read_with_the_sanitizer_on_is_not_template_code(tmp_path):
    command = "echo '$__user__.email' | bash"
    assert classify(review(tmp_path, command)).codes == [Uncheckable.LETTERS_ARE_CODE]
    unsanitized = classify(review(tmp_path, command, extra='<options sanitize="false"/>'))
    assert unsanitized.codes == [Uncheckable.LETTERS_ARE_CODE, Uncheckable.TEMPLATE_CODE]


def test_pipe_to_shell_is_letters_are_code(tmp_path):
    result = classify(review(tmp_path, "echo '$text' | bash"))
    assert Uncheckable.LETTERS_ARE_CODE in result.codes
    assert result.unchecked_locations == {"command": RUNS_TEXT}


def test_reflection_in_the_command_is_an_unchecked_location(tmp_path):
    result = classify(review(tmp_path, "tool '${getattr($input, 'name')}'"))
    assert result.unchecked_locations == {"command": READS_BY_NAME}
    assert result.codes == [Uncheckable.TEMPLATE_CODE]


def test_undecidable_finding_is_an_unchecked_location(tmp_path):
    result = classify(review(tmp_path, "$text.value"))
    assert result.unchecked_locations == {"command": NOT_CHECKABLE}
    assert result.codes == [Uncheckable.LETTERS_ARE_CODE]


@pytest.mark.parametrize("code", list(Uncheckable))
def test_every_code_has_a_description(code):
    assert DESCRIPTIONS[code]
