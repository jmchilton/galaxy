"""Template code the review reads as code of the same meaning that it follows."""

from __future__ import annotations

import pytest

from .test_known_helpers import code
from .test_review import (
    GROUP,
    INPUTS,
    review,
    rules,
)

REPEAT = '<repeat name="r" title="r"><param name="t" type="text"><sanitizer sanitize="false"/></param></repeat>'


@pytest.mark.parametrize(
    "command,injection",
    [
        # tools-iuc countess.
        ("#for $m in $r\n#set $v = getattr($m.t, 'value', $m.t) or ''\ntool '$v'\n#end for", True),
        ("#set $v = getattr($text, 'value', $text) or ''\ntool '$v'", True),
        ("#set $v = getattr($word, 'value', $word)\ntool '$v'", False),
        ("#if getattr($text, 'value')\ntool\n#end if", False),
    ],
)
def test_getattr_of_value_is_the_attribute(tmp_path, command, injection):
    report = review(tmp_path, command, inputs=INPUTS + GROUP + REPEAT)
    assert code(report) == set()
    assert (("shell-injection", "high") in rules(report)) is injection


@pytest.mark.parametrize(
    "command",
    [
        "#set $v = getattr($text, '__class__')\ntool '$v'",
        "#set $v = getattr($text, 'f_globals')\ntool '$v'",
        "#set $v = getattr($input, 'unsanitized').name\ntool '$v'",
        "#set $v = getattr($text, 'value' + '')\ntool '$v'",
        "#set $v = getattr($text, 'value', default=1)\ntool '$v'",
        "#set $v = getattr($text.pop(), 'value')\ntool '$v'",
        "#set $v = getattr($text, 'value', $free.pop())\ntool '$v'",
        # A method, left uncalled and called later.
        "#set $f = getattr($c, 'get')\ntool '${f('t')}'",
        "#for $v in getattr($c, 'values')()\ntool '$v'\n#end for",
        "#set $e = getattr($r, 'pop')()\ntool '${e.t}'",
        "#set $g = getattr(self, 'getVar')\ntool '${g(str($text), '')}'",
        # The template object or the #set global store, not the namespace.
        "#set $v = getattr($self, 'value')\ntool '$v'",
        "#def value()\n#return $free\n#end def\n#set $v = getattr($text, 'value')\ntool '$v'",
        "#set $v = getattr($values, 'value')\ntool '$v'",
        # Read through the namespace, where an input of that name comes first.
        "tool '${getattr($text, 'value')}'",
        "#set $getattr = $vars\n#set $v = getattr($text, 'value')\ntool '$v'",
        "#set $v = getattr($SL, 'value', $free)\ntool '$v'",
        "#def hasattr(a, b)\n#return True\n#end def\n#set $v = getattr($text, 'value', $free)\ntool '$v'",
    ],
)
def test_getattr_otherwise_is_reflection(tmp_path, command):
    report = review(tmp_path, command, inputs=INPUTS + GROUP + REPEAT)
    assert any(f.rule == "template-reflection" and f.expr == "getattr" for f in report.findings)
