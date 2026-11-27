"""Structured sources and breakout characters of findings, which let Galaxy check the values of a job."""

from __future__ import annotations

import json
import time

import pytest

from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.security import (
    Finding,
    Report,
    review_tool_source,
    SourceRef,
)
from galaxy.tool_util.security.charsets import (
    HIGH,
    SHELL_EXEC,
)
from galaxy.tool_util.security.report import (
    DATASET_ATTRIBUTE,
    DATASET_CONTENT,
    ELEMENT_IDENTIFIER,
    GROUP_TAGS,
    METADATA,
    OPAQUE,
    RAW_DATASET_ATTRIBUTE,
    RAW_METADATA,
    RAW,
    SPECIAL,
    TEXT,
    USER_PREFERENCE,
)
from .test_review import (
    CONFIG,
    INPUTS,
    review,
    rules,
)

UNSANITIZED = '<options sanitize="False"/>'


def refs(report: Report) -> set[SourceRef]:
    return {ref for f in report.findings for ref in f.refs}


@pytest.mark.parametrize(
    "command,extra,expected",
    [
        ("echo '$text'", "", SourceRef(TEXT, "text")),
        ("echo '${text.value}'", "", SourceRef(RAW, "text")),
        ("echo '$text.strip()'", "", SourceRef(RAW, "text")),
        ("echo '$input.element_identifier'", "", SourceRef(ELEMENT_IDENTIFIER, "input")),
        ("echo '$input.name_and_ext'", "", SourceRef(ELEMENT_IDENTIFIER, "input")),
        ("#for $e in $flat\necho '$e.element_identifier'\n#end for", "", SourceRef(ELEMENT_IDENTIFIER, "flat")),
        ("#for $e in $nested\necho '$e.name'\n#end for", "", SourceRef(ELEMENT_IDENTIFIER, "nested")),
        ("echo '$flat.name'", "", SourceRef(ELEMENT_IDENTIFIER, "flat")),
        ("echo '$input.name'", UNSANITIZED, SourceRef(DATASET_ATTRIBUTE, "input", "name")),
        ("echo '$input.info'", UNSANITIZED, SourceRef(DATASET_ATTRIBUTE, "input", "info")),
        ("echo '$input.dataset.info'", UNSANITIZED, SourceRef(DATASET_ATTRIBUTE, "input", "info")),
        ("echo '$input.metadata.sample_names'", UNSANITIZED, SourceRef(METADATA, "input", "sample_names")),
        ("#for $g in $input.groups\necho '$g'\n#end for", "", SourceRef(GROUP_TAGS, "input")),
        ("echo $column", UNSANITIZED, SourceRef(TEXT, "column")),
        ("echo '${column.value}'", "", SourceRef(RAW, "column")),
        ("echo '$__user_email__'", UNSANITIZED, SourceRef(SPECIAL, None, "__user_email__")),
        ("echo '$input.unsanitized.name'", "", SourceRef(RAW_DATASET_ATTRIBUTE, "input", "name")),
        ("echo '$input.unsanitized.metadata.sample_names'", "", SourceRef(RAW_METADATA, "input", "sample_names")),
        # What the model reaches beyond the dataset stays opaque.
        ("echo '$input.unsanitized.history.name'", "", SourceRef(OPAQUE, "input")),
        ("echo '$input.unsanitized.metadata.get('x')'", "", SourceRef(OPAQUE, "input")),
        ("echo '$__user__.username'", "", SourceRef(SPECIAL, None, "__user_name__")),
        ("echo '$__user__.email'", "", SourceRef(SPECIAL, None, "__user_email__")),
        ("echo '$__user__.addresses'", "", SourceRef(OPAQUE)),
        ("echo '${opts.adv.deep.element_identifier}'", "", SourceRef(ELEMENT_IDENTIFIER, "opts.adv.deep")),
        ("#for $r in $rows\necho '${r.label.value}'\n#end for", "", SourceRef(RAW, "rows.label")),
    ],
)
def test_finding_names_its_source(tmp_path, command, extra, expected):
    assert expected in refs(review(tmp_path, command, extra=extra))


def test_param_path():
    assert SourceRef(RAW, "opts.adv.deep").param_path == ("opts", "adv", "deep")
    assert SourceRef(SPECIAL, None, "__user_email__").param_path == ()


def test_sources_keep_their_text(tmp_path):
    (finding,) = [f for f in review(tmp_path, "echo '$input.element_identifier'").findings if f.severity == HIGH]
    assert finding.source == "element identifier of dataset 'input' (not sanitized)"


def high(report: Report):
    (finding,) = [f for f in report.findings if f.severity == HIGH]
    return finding


@pytest.mark.parametrize(
    "command,breakout,requires",
    [
        # A quote leaves single quotes, and a command character after it starts a command.
        ("echo '${free}'", frozenset("'"), SHELL_EXEC),
        ("echo ${free}", SHELL_EXEC, frozenset()),
        # A substitution, or a closing quote that a command character follows.
        ('echo "${free}"', frozenset('`$"'), SHELL_EXEC),
        # In $'...' a backslash escapes the closing quote.
        ("echo $'${free}'", frozenset("'\\"), SHELL_EXEC),
        # Escaping writes the quote that closes the string; the value has to bring the command characters.
        ("#import shlex\necho '${shlex.quote(str($free))}'", SHELL_EXEC, frozenset()),
        ('echo "$json.dumps(str($free))"', frozenset("`$") | SHELL_EXEC, frozenset()),
        ('echo "${repr(str($free))}"', frozenset("`$") | SHELL_EXEC, frozenset()),
    ],
)
def test_breakout(tmp_path, command, breakout, requires):
    finding = high(review(tmp_path, command))
    assert (finding.breakout, finding.requires) == (breakout, requires)
    assert finding.checkable


def python_script_findings(tmp_path, script: str) -> list[Finding]:
    report = review(tmp_path, "python3 '$script'", CONFIG.format(f"<![CDATA[{script}\n]]>"))
    return [f for f in report.findings if f.location == "configfile:script"]


@pytest.mark.parametrize(
    "script",
    [
        # repr() and json.dumps() write a literal: as Python code outside a string it stays one string.
        "x = ${repr($free)}",
        "x = ${repr('a' + $free)}",
        "#import json\nx = ${json.dumps($free)}",
        # json.dumps() writes no single quote, and escapes the backslash that could escape one.
        "#import json\nx = '${json.dumps(str($text))}'",
    ],
)
def test_literal_in_python_configfile_stays_one_string(tmp_path, script):
    assert python_script_findings(tmp_path, script) == []


@pytest.mark.parametrize(
    "script,breakout,context",
    [
        # Inside a string their quotes end it; the value then has to bring the code.
        ("x = '${repr(str($text))}'", frozenset("()"), "inside a '...' string of a python script"),
        ("x = '${repr(' ' + str($text))}'", frozenset("()"), "inside a '...' string of a python script"),
        ('#import json\nx = "${json.dumps(str($text))}"', frozenset("()"), 'inside a "..." string of a python script'),
        # A slice cuts off repr()'s quotes.
        ("x = ${repr($free)[1:-1]}", frozenset("();`"), "outside any string of a python script"),
        # The code before the literal runs it, or makes it an f-string.
        ("x = eval(${repr(str($text))})", frozenset("()"), "as a string that the python script evaluates as code"),
        ("x = f${repr($free)}", frozenset("{"), "as an f-string of a python script"),
    ],
)
def test_literal_in_python_configfile_breakout(tmp_path, script, breakout, context):
    (finding,) = [f for f in python_script_findings(tmp_path, script) if f.severity == HIGH]
    assert (finding.breakout, finding.requires, finding.context) == (breakout, frozenset(), context)
    assert finding.checkable


def nested(report: Report):
    (finding,) = [f for f in report.findings if f.rule == "nested-interpreter" and f.severity == HIGH]
    return finding


@pytest.mark.parametrize(
    "command,breakout",
    [
        # In a part of s, y or an address only its delimiter, a backslash or a newline leaves it.
        ("sed 's/x/${free}/' '$input'", frozenset("/\\\n]")),
        ("sed \"s|x|${free}|g\" '$input'", frozenset("|\\\n]")),
        ("sed '/${free}/d' '$input'", frozenset("/\\\n]")),
        ("sed 's/[/]/${free}/' '$input'", frozenset("/\\\n]")),
        # Quotes are plain characters to sed.
        ("sed \"s/'${free}'/x/\" '$input'", frozenset("/\\\n]")),
        ("sed '1i ${free}' '$input'", frozenset("\n\\")),
        ("sed 'b ${free}' '$input'", frozenset(";\n} \t")),
        # Where sed expects a command, letters are enough: `e` runs a shell command.
        ("sed -n '${free}p' '$input'", frozenset()),
        ("sed -e 's/a/b/' -e '${free}' '$input'", frozenset()),
        ("sed 's/a/b/${free}' '$input'", frozenset()),
    ],
)
def test_sed_breakout(tmp_path, command, breakout):
    finding = nested(review(tmp_path, command))
    assert finding.breakout == breakout
    assert finding.checkable is bool(breakout)


def test_awk_has_no_single_quoted_strings(tmp_path):
    # `'...'` is not a string in awk: the value is awk code.
    assert '"' in nested(review(tmp_path, "awk \"{print '${free}'}\" '$input'")).breakout
    assert nested(review(tmp_path, "awk '{print \"${free}\"}' '$input'")).breakout == frozenset('"')


@pytest.mark.parametrize(
    "script,reported",
    [
        ("#!/bin/sh\ntool ${free}\n", True),
        # A comment ends with its line, and the next line is a new command.
        ("#!/bin/sh\n# ${free}\ntool '$input'\n", False),
        ("#!/bin/sh\n# note\ntool ${free}\n", True),
    ],
)
def test_shell_script_configfile_has_lines(tmp_path, script, reported):
    configfiles = f'<configfile name="script"><![CDATA[{script}]]></configfile>'
    report = review(tmp_path, "sh '$script'", configfiles)
    assert any(f.location == "configfile:script" and f.severity == HIGH for f in report.findings) is reported


def test_quote_in_a_here_document_does_not_quote_the_rest_of_the_script(tmp_path):
    script = "#!/bin/sh\ncat <<EOF\ndon't\nEOF\ntool ${free}\n"
    configfiles = f'<configfile name="script"><![CDATA[{script}]]></configfile>'
    finding = high(review(tmp_path, "sh '$script'", configfiles))
    assert ";" in finding.breakout


@pytest.mark.parametrize(
    "command",
    [
        # Template code can write the character that leaves the quotes, whatever the user wrote.
        "echo \"${text.replace('Q', '`')}\"",
        "echo ${str($text).replace('__gt__', '>')}",
        "#import re\necho ${re.sub('[^a-z]', ';', str($free))}",
        "#import re\necho ${re.sub('_*', ';', str($free))}",
        "echo ${str($free).lower().replace('_', ';')}",
        "#import urllib.parse\necho '${urllib.parse.unquote(str($free))}'",
        "#import base64\necho '${base64.b64decode(str($free))}'",
        "echo '${some_function($free)}'",
        "echo '${str($free).translate($table)}'",
    ],
)
def test_rewritten_values_are_not_checkable(tmp_path, command):
    report = review(tmp_path, command)
    findings = [f for f in report.findings if f.severity == HIGH and f.kind == "vulnerability"]
    assert findings
    assert all(not f.checkable and f.unchecked for f in findings)


@pytest.mark.parametrize(
    "command,trigger,added",
    [
        ("#import re\necho ${re.sub('_', ';', str($free))}", "_", ";"),
        ("#import re\necho ${re.sub('[|&]', ';', str($free))}", "|&", ";"),
        ("echo ${str($free).replace('|', ';')}", "|", ";"),
        ("echo \"${free.replace('\"', '\\\\\"')}\"", '"', '\\"'),
    ],
)
def test_literal_rewrite_of_a_value_is_checked_with_what_it_adds(tmp_path, command, trigger, added):
    report = review(tmp_path, command)
    finding = high(report)
    assert finding.checkable and not finding.unchecked
    assert not report.rewrites
    assert report.rewritten[finding.refs[0]] == [(frozenset(trigger), frozenset(added))]


def test_literal_rewrite_of_a_changed_value_is_a_rewrite(tmp_path):
    report = review(tmp_path, "echo ${str($free).lower().replace('|', ';')}")
    assert report.rewrites == {"command": [".replace"]}
    assert not report.rewritten


def test_rewriting_that_cannot_add_a_breakout_character_stays_checkable(tmp_path):
    finding = high(review(tmp_path, "echo '${str($free).replace('_', '-').lower()}'"))
    assert finding.checkable and not finding.unchecked


@pytest.mark.parametrize(
    "command",
    [
        "echo '${''.join([\"'\", str($free)])}'",
        "#set $l = [\"'\", str($free)]\necho '${''.join($l)}'",
        "#set $l = [\"'\", str($free)]\necho '${''.join(reversed($l))}'",
    ],
)
def test_literal_elements_joined_with_a_value_are_not_the_users(tmp_path, command):
    finding = high(review(tmp_path, command))
    assert finding.unchecked and not finding.checkable


def test_writes_record_what_does_harm_outside_quotes(tmp_path):
    # `echo '$x' && echo '$y'`: a quote in x leaves the `;` of y unquoted. `no_quote` has no finding
    # (it cannot leave its quotes), but its `;` does harm once another value's quote frees it.
    report = review(tmp_path, "echo '${free}' && echo '${no_quote}' && echo '$word'")
    writes = report.writes["command"]
    assert writes[SourceRef(TEXT, "free")] == SHELL_EXEC
    assert writes[SourceRef(TEXT, "no_quote")] == SHELL_EXEC
    assert writes[SourceRef(TEXT, "word")] == frozenset()
    json.dumps(report.to_dict())


def test_a_quote_left_raw_by_escaping_closes(tmp_path):
    # repr() writes `"x'"`: its `"` closes the template's double quotes, and the value's own `'`
    # then opens single quotes that flip the rest of the line.
    report = review(tmp_path, """echo "${repr(str($quotes))}" && echo '$word'""")
    (finding,) = [f for f in report.findings if f.kind == "vulnerability" and f.refs == (SourceRef(TEXT, "quotes"),)]
    assert finding.closes == frozenset("'\"") and finding.checkable


def test_writes_are_left_out_when_a_value_is_rewritten(tmp_path):
    report = review(tmp_path, """echo '${str($no_quote).replace("Q", ";")}' && echo '${free}'""")
    assert "command" not in report.writes
    assert not any(f.checkable for f in report.findings if f.kind == "vulnerability")


def test_a_rewritten_value_makes_the_whole_template_uncheckable(tmp_path):
    # The rewrite can bring the quote that lets the other value out.
    report = review(tmp_path, """echo '${str($free).replace("Q", "'")}${text.value}'""")
    findings = [f for f in report.findings if f.kind == "vulnerability" and f.severity == HIGH]
    assert findings and not any(f.checkable for f in findings)


@pytest.mark.parametrize(
    "command",
    [
        "echo '${free}'\necho ${str($free).replace('Q', ';')}",
        "echo ${str($free).replace('Q', ';')}\necho '${free}'",
    ],
)
def test_a_rewritten_source_is_not_checkable_anywhere(tmp_path, command):
    # Whether the rewrite comes before or after a place that writes the value as it is.
    findings = [f for f in review(tmp_path, command).findings if f.kind == "vulnerability" and f.severity == HIGH]
    assert len(findings) == 2
    assert all(f.unchecked for f in findings)


def test_nested_shell(tmp_path):
    report = review(tmp_path, "sh -c 'echo ${free}'")
    breakout = {f.rule: (f.breakout, f.requires) for f in report.findings}
    # Closing the quotes of `sh -c '...'`, or a command character inside the nested shell.
    assert breakout == {
        "shell-injection": (frozenset("'"), SHELL_EXEC),
        "nested-interpreter": (SHELL_EXEC, frozenset()),
    }


def test_no_character_decides_the_program(tmp_path):
    report = review(tmp_path, "$free --version")
    (finding,) = [f for f in report.findings if f.rule == "command-position"]
    assert finding.breakout == frozenset()


@pytest.mark.parametrize(
    "command,reason",
    [
        # Whatever the template object holds is not followed: it may bring the quote that frees another value.
        ("echo '$searchList' '$input.element_identifier'", "parts of it were not analysed"),
        # Letters alone are a command once the shell reads them.
        ("echo '${free}' | sh", "it sends text to a shell to run"),
    ],
)
def test_template_no_character_test_can_judge(tmp_path, command, reason):
    report = review(tmp_path, command)
    assert report.unchecked_locations == {"command": reason}
    assert report.findings and not any(f.checkable for f in report.findings if f.kind == "vulnerability")
    assert "command" not in report.writes


@pytest.mark.parametrize(
    "configfiles",
    [
        '<inputs name="params"/>',
        '<inputs name="params" filename="params.json" data_style="paths"/>',
        '<file_sources name="params"/>',
    ],
)
def test_path_of_a_file_galaxy_writes_is_checkable(tmp_path, configfiles):
    report = review(tmp_path, "tool --params '$params' '$input.element_identifier'", configfiles)
    assert report.unchecked_locations == {}
    assert high(report).checkable


@pytest.mark.parametrize(
    "command",
    [
        "#import pipes\necho ${pipes.quote(str($free))}",
        "#if $free\n    #import pipes\n    echo ${pipes.quote(str($free))}\n#end if",
        "#import pipes as p\necho ${p.quote(str($free))}",
        "#from pipes import quote\necho ${quote(str($free))}",
    ],
)
def test_imported_module_is_not_an_unanalysed_part(tmp_path, command):
    report = review(tmp_path, f"{command} '$input.element_identifier'")
    assert report.unanalyzed == []
    assert report.unchecked_locations == {}


@pytest.mark.parametrize("call", ["$hex($count)", "$oct($count)", "${divmod($count, 2)[0]}", "${frozenset($free)}"])
def test_builtin_the_analysis_models_is_not_an_unanalysed_part(tmp_path, call):
    report = review(tmp_path, f"echo {call} '$input.element_identifier'")
    assert report.unanalyzed == []
    assert report.unchecked_locations == {}


@pytest.mark.parametrize("include", ["#include source=$pre#", "#include source=$pre", "  #include source=$pre#  "])
def test_included_template_macro_is_analysed_in_place(tmp_path, include):
    macros = """<macros><template name="pre"><![CDATA[echo '${free}' &&]]></template></macros>"""
    report = review(tmp_path, f"{include}\necho '$input.element_identifier'", extra=macros)
    assert report.unanalyzed == []
    assert not any(f.rule == "template-include" for f in report.findings)
    assert [(f.rule, f.severity, f.expr, f.line) for f in report.findings if f.rule == "template-macro"] == [
        ("template-macro", "info", "pre", 1)
    ]
    assert SourceRef(TEXT, "free") in refs(report)
    assert all(f.checkable for f in report.findings if f.kind == "vulnerability")


@pytest.mark.parametrize(
    "command,inputs",
    [
        ("#set $pre = str($free)\n", ""),
        ("#set global $pre = str($free)\n", ""),
        ("#def pre\nx\n#end def\n", ""),
        ("#attr $pre = 'x'\n", ""),
        ("#for $pre in [$free]\nx\n#end for\n", ""),
        ("#silent $searchList()[0].update({'pre': $free})\n", ""),
        ("#silent $SL[0].update({'pre': $free})\n", ""),
        ("#silent $self._CHEETAH__globalSetVars.update({'pre': $free})\n", ""),
        ("#silent self._CHEETAH__globalSetVars.update({'pre': $free})\n", ""),
        ("#include source=$other#\n", ""),
        ("", '<param name="pre" type="text"/>'),
    ],
)
def test_template_macro_a_lookup_can_find_elsewhere_is_a_runtime_include(tmp_path, command, inputs):
    macros = """<macros>
<template name="pre"><![CDATA[echo hi &&]]></template>
<template name="other"><![CDATA[#set global $pre = str($free)]]></template>
</macros>"""
    command = f"{command}#include source=$pre#\necho '$input.element_identifier'"
    report = review(tmp_path, command, extra=macros, inputs=INPUTS + inputs if inputs else "")
    assert ("template-include", "critical") in {(f.rule, f.severity) for f in report.findings}
    assert "pre" not in {f.expr for f in report.findings if f.rule == "template-macro"}


@pytest.mark.parametrize("name", ["keys", "searchList", "SL"])
def test_template_macro_named_like_a_name_cheetah_finds_first_is_a_runtime_include(tmp_path, name):
    macros = f"""<macros><template name="{name}"><![CDATA[echo hi &&]]></template></macros>"""
    report = review(tmp_path, f"#include source=${name}#\ntool", extra=macros)
    assert ("template-include", "critical") in {(f.rule, f.severity) for f in report.findings}
    assert not any(f.rule == "template-macro" for f in report.findings)


def test_include_of_a_long_form_placeholder_does_not_compile(tmp_path):
    macros = """<macros><template name="pre"><![CDATA[echo hi &&]]></template></macros>"""
    report = review(tmp_path, "#include source=${pre}\ntool", extra=macros)
    assert report.unanalyzed == ["command: template does not compile (ParseError)"]


@pytest.mark.parametrize(
    "command,reads",
    [
        ("## #include source=$pre#\n", True),
        ("#*\n#include source=$pre#\n*#\n", True),
        # The text is written: a shell comment to the end of the joined command line.
        ("#raw\n#include source=$pre#\n#end raw\n", False),
    ],
)
def test_include_text_cheetah_does_not_read_as_the_directive_is_left_as_it_is(tmp_path, command, reads):
    macros = """<macros><template name="pre"><![CDATA[x
#set $free = 'clean'
]]></template></macros>"""
    report = review(tmp_path, f"{command}echo '$free' > '$out'", extra=macros)
    assert (SourceRef(TEXT, "free") in refs(report)) == reads
    assert not any(f.rule in ("template-macro", "template-include") for f in report.findings)


@pytest.mark.parametrize(
    "macro,command",
    [
        # Cheetah renders an included text as a template of its own: its locals are not the includer's.
        ("#set $free = 'clean'", "#include source=$pre#\necho '$free' > '$out'"),
        ("echo '$free' &&", "#set $free = 'clean'\n#include source=$pre#\necho x > '$out'"),
        ("#set $x = 'clean'", "#set $x = $free\n#include source=$pre#\necho '$x' > '$out'"),
        ("#set $k = 'clean'", "#set $k = $free\n#include source=$pre#\necho '$k' > '$out'"),
        ("#set $v = 'clean'", "#for $v in [$free]\n#include source=$pre#\necho '$v' > '$out'\n#end for"),
        ("#if $count\n#set $free = 'clean'\n#end if", "#include source=$pre#\necho '$free' > '$out'"),
        ("#for $free in ['clean']\nx\n#end for", "#include source=$pre#\necho '$free' > '$out'"),
        # Text around the include on its line.
        ("x", "  echo '$free' #include source=$pre#\necho x > '$out'"),
        ("x", "#include source=$pre# echo '$free' > '$out'"),
        # Without its closing `#`, the include takes its newline: the next line is no shell comment.
        ("echo hi", "#include source=$pre\n# '$free'\necho done > '$out'"),
        # A last line of a comment alone renders nothing (Galaxy strips the macro's trailing whitespace).
        ("echo '$free' &&\n  ## end", "#include source=$pre#\necho x > '$out'"),
    ],
)
def test_template_macro_is_read_in_as_cheetah_renders_it(tmp_path, macro, command):
    macros = f"""<macros><template name="pre"><![CDATA[{macro}]]></template></macros>"""
    report = review(tmp_path, command, extra=macros)
    assert any(f.rule == "shell-injection" and SourceRef(TEXT, "free") in f.refs for f in report.findings)
    assert [f.expr for f in report.findings if f.rule == "template-macro"] == ["pre"]


def test_newline_after_an_include_renders_after_the_macro(tmp_path):
    macros = """<macros><template name="pre"><![CDATA[echo --opt=#slurp]]></template></macros>"""
    report = review(tmp_path, "#include source=$pre#\n'$text' > '$out'", extra=macros)
    assert ("option-injection", "low") in rules(report)


@pytest.mark.parametrize(
    "macro,command",
    [
        # Its members are its own.
        ("#def helper\nx\n#end def", "#include source=$pre#\necho '$helper' > '$out'"),
        ("#attr $helper = 'x'", "#include source=$pre#\necho '$helper' > '$out'"),
        ("#import os", "#include source=$pre#\necho '$os' > '$out'"),
        # It includes itself.
        ("#include source=$pre#", "#include source=$pre#\necho x > '$out'"),
    ],
)
def test_template_macro_that_cannot_be_read_in_is_a_runtime_include(tmp_path, macro, command):
    macros = f"""<macros><template name="pre"><![CDATA[{macro}]]></template></macros>"""
    report = review(tmp_path, command, extra=macros)
    assert ("template-include", "critical") in {(f.rule, f.severity) for f in report.findings}
    assert not any(f.rule == "template-macro" for f in report.findings)


@pytest.mark.parametrize("macro", ["#raw\nx", "x ## comment"])
def test_template_macro_ending_in_text_cheetah_does_not_read_is_not_analysed(tmp_path, macro):
    macros = f"""<macros><template name="pre"><![CDATA[{macro}]]></template></macros>"""
    report = review(tmp_path, "#include source=$pre#\necho '$free' > '$out'", extra=macros)
    assert ("template-include", "critical") in {(f.rule, f.severity) for f in report.findings}


def test_template_macros_binding_a_name_before_reading_it_are_read_in_place(tmp_path):
    loop = "#for $s in $sections\necho '$s' &&\n#end for"
    macros = f"""<macros>
<template name="set_sections"><![CDATA[#set global $sections = ['a', 'b']]]></template>
<template name="first"><![CDATA[{loop}]]></template>
<template name="second"><![CDATA[#set $s = 'c'\necho '$s' &&\n{loop}]]></template>
</macros>"""
    includes = ("set_sections", "first", "second", "first")
    command = "".join(f"#include source=${name}#\n" for name in includes) + "tool"
    report = review(tmp_path, command, extra=macros)
    assert not any(f.rule == "template-include" for f in report.findings)
    assert sorted({f.expr for f in report.findings if f.rule == "template-macro"}) == [
        "first",
        "second",
        "set_sections",
    ]


def test_output_named_like_a_template_macro_is_a_runtime_include(tmp_path):
    path = tmp_path / "tool.xml"
    path.write_text("""<tool id="t" name="t" version="1" profile="24.2">
  <macros><template name="pre"><![CDATA[echo hi &&]]></template></macros>
  <command><![CDATA[#include source=$pre#
echo x > '$pre']]></command>
  <outputs><data name="pre" format="txt"/></outputs>
</tool>""")
    report = review_tool_source(get_tool_source(str(path)))
    assert ("template-include", "critical") in {(f.rule, f.severity) for f in report.findings}


def test_template_macros_included_by_macros_are_read_in(tmp_path):
    macros = """<macros>
<template name="a"><![CDATA[echo a
#include source=$b#]]></template>
<template name="b"><![CDATA[echo '$free' &&]]></template>
</macros>"""
    report = review(tmp_path, "echo x\n#include source=$a#\n#include source=$b#\necho y", extra=macros)
    assert sorted((f.expr, f.line, f.more_lines) for f in report.findings if f.rule == "template-macro") == [
        ("a", 2, ()),
        ("b", 3, ()),
    ]
    assert not any(f.rule == "template-include" for f in report.findings)
    assert any(f.rule == "shell-injection" and SourceRef(TEXT, "free") in f.refs for f in report.findings)


def test_converted_dataset_is_a_dataset(tmp_path):
    inputs = '<param name="vcf" type="data" format="vcf"><conversion name="vcf_index" type="tabix"/></param>'
    report = review(tmp_path, "ln -s '$vcf_index' i.tbi && echo '$vcf_index.element_identifier'", inputs=inputs)
    assert report.unanalyzed == []
    assert refs(report) == {SourceRef(ELEMENT_IDENTIFIER, "vcf_index")}
    assert high(report).checkable


def test_parameter_named_without_its_nesting_is_looked_up_in_each_when_block(tmp_path):
    inputs = """<conditional name="c">
  <param name="sel" type="select"><option value="a">a</option><option value="b">b</option></param>
  <when value="a"><param name="x" type="text"/></when>
  <when value="b"><section name="s"><param name="x" type="text"/></section></when>
</conditional>"""
    report = review(tmp_path, "#if $c.sel in ['a', 'b']\necho '$c.x'\n#end if", inputs=inputs)
    assert refs(report) == {SourceRef(TEXT, "c.x"), SourceRef(TEXT, "c.s.x")}


def test_many_narrowings_of_a_conditional_are_reviewed_in_time(tmp_path):
    # Each #if/#elif on the selector narrows the conditional; a template with many of them
    # inside a repeat once took minutes.
    cases = range(6)
    options = "".join(f'<option value="v{i}">v{i}</option>' for i in cases)
    whens = "".join(f'<when value="v{i}"><param name="p{i}" type="text"/></when>' for i in cases)
    inputs = f'<repeat name="r" title="r"><conditional name="c"><param name="sel" type="select">{options}</param>{whens}</conditional></repeat>'
    blocks = "".join(
        f"#if $t.c.sel == 'v{b % 6}'\necho '$t.c.p{b % 6}'\n#elif $t.c.sel == 'v{(b + 1) % 6}'\necho '$t.c.p{(b + 1) % 6}'\n#end if\n"
        for b in range(12)
    )
    started = time.thread_time()
    report = review(tmp_path, f"#for $t in $r\n{blocks}#end for", inputs=inputs)
    assert time.thread_time() - started < 5
    assert refs(report) == {SourceRef(TEXT, f"r.c.p{i}") for i in cases}


def test_template_without_such_parts_is_checkable(tmp_path):
    report = review(tmp_path, "echo '$input.element_identifier'")
    assert report.unchecked_locations == {}
    assert all(f.checkable for f in report.findings)


@pytest.mark.parametrize(
    "command",
    [
        "#from os.path import splitext\n#set $n = splitext($input.element_identifier)[0]\necho '$n'",
        "#import os\n#set $p = os.path.join('dir', $input.element_identifier)\necho '$p'",
        "#from os.path import join as j\n#set $p = j($input.element_identifier, 'f.txt')\necho '$p'",
        "#import os\n#set $p = os.path.dirname($input.element_identifier)\necho '$p'",
    ],
)
def test_path_functions_keep_the_value_checkable(tmp_path, command):
    finding = high(review(tmp_path, command))
    assert finding.checkable
    assert finding.breakout == frozenset("'")


QUOTED_OR = (
    "#set $l = []\n#for r in $rows\n#if len(r.label.value) > 1\n#silent $l.append(\"'%s'\" % r.label.value)\n"
    "#else\n#silent $l.append({other})\n#end if\n#end for\necho #echo ' '.join($l)#"
)


@pytest.mark.parametrize(
    "command,checkable",
    [
        # Each element quotes its own value: the shell reads the quotes in place.
        ("""#set $l = ' '.join(["'%s'" % r.label.value for r in $rows])\necho $l""", True),
        ("""#set $l = "' '".join(["'%s'" % r.label.value for r in $rows])\necho $l""", True),
        # Elements and a separator that each end in the quote state they start in, with both kinds.
        ("""#set $l = '" "'.join(["'%s'" % r.label.value for r in $rows])\necho $l""", True),
        ("""#set $l = ' AND '.join(["c = '\\"'\\"'%s'\\"'\\"'" % r.label.value for r in $rows])\necho '$l'""", True),
        # Here a third element can land in a third quote state.
        ("""#set $l = ' '.join(["'%s\\"" % r.label.value for r in $rows])\necho $l""", False),
        # A literal element alone loses its place next to the value.
        ("""#set $l = ''.join(["'", str($free)])\necho $l""", False),
        # Elements that are one of several strings.
        (QUOTED_OR.format(other="r.label.value"), True),
        (
            """#if $free\n#set $l = $free\n#else\n#set $l = ["'%s'" % r.label.value for r in $rows]\n#end if\necho #echo ' '.join($l)#""",
            True,
        ),
        (QUOTED_OR.format(other="'\"%s\"' % r.label.value"), True),
        (QUOTED_OR.format(other='"\'%s\\"" % r.label.value'), False),
    ],
)
def test_join_of_quoted_elements(tmp_path, command, checkable):
    findings = [f for f in review(tmp_path, command).findings if f.severity == HIGH]
    assert findings and all(f.checkable is checkable for f in findings)


def test_value_that_is_a_parameter_or_a_list_has_the_elements_of_both(tmp_path):
    command = "#if $free\n#set $l = $text\n#else\n#set $l = [$input.element_identifier]\n#end if\n#for $e in $l\necho '$e'\n#end for"
    assert SourceRef(ELEMENT_IDENTIFIER, "input") in refs(review(tmp_path, command))


@pytest.mark.parametrize(
    "command",
    [
        "echo '$unknown' '$input.element_identifier'",
        "#for $k in $unknown.keys()\necho '$unknown[$k].name' '$input.element_identifier'\n#end for",
    ],
)
def test_name_that_is_not_a_tool_input_is_a_job_parameter(tmp_path, command):
    report = review(tmp_path, command)
    assert report.unanalyzed == []
    assert high(report).checkable
    assert not any(SourceRef(SPECIAL, None, "unknown") in f.refs for f in report.findings if f.severity == HIGH)


def test_job_parameter_of_a_tool_without_sanitizing_is_checked(tmp_path):
    finding = high(review(tmp_path, "echo '$unknown'", extra=UNSANITIZED))
    assert finding.refs == (SourceRef(SPECIAL, None, "unknown"),)
    assert finding.checkable


@pytest.mark.parametrize("name", ["input1", "input12"])
def test_dataset_of_a_data_input_by_its_position_is_a_dataset(tmp_path, name):
    report = review(tmp_path, f"echo '${name}.element_identifier'")
    assert refs(report) == {SourceRef(ELEMENT_IDENTIFIER, "input")}


def test_datasets_of_a_group_are_datasets_of_the_collection(tmp_path):
    command = "#for $f in $flat.get_datasets_for_group($free)\necho '$f.element_identifier'\n#end for"
    finding = high(review(tmp_path, command))
    assert finding.refs == (SourceRef(ELEMENT_IDENTIFIER, "flat"),)
    assert finding.checkable


def test_value_put_into_a_dict_with_setitem_is_followed(tmp_path):
    command = "#import json\n#set $d = {}\n$d.__setitem__('k', $input.element_identifier)\necho '#echo json.dumps($d)#'"
    assert SourceRef(ELEMENT_IDENTIFIER, "input") in refs(review(tmp_path, command))


def test_newline_starts_a_command_in_a_shell_script(tmp_path):
    script = review(tmp_path, "bash '$script'", configfiles='<configfile name="script">echo $free</configfile>')
    assert "\n" in high(script).breakout
    assert "\n" not in high(review(tmp_path, "echo $free")).breakout


def test_newline_a_replace_makes_of_a_carriage_return_is_checked(tmp_path):
    configfile = """<configfile name="script">#set $v = str($free).replace('\\r', '\\n')\necho $v</configfile>"""
    finding = high(review(tmp_path, "bash '$script'", configfiles=configfile))
    assert "\n" in finding.breakout
    assert finding.checkable


@pytest.mark.parametrize("value", ["$input.__str__", "$input.__str__()"])
def test_str_method_gives_the_string_of_the_value(tmp_path, value):
    command = f"#import os\n#set $n = os.path.basename({value}).replace('.', '_')\necho $n '$input.element_identifier'"
    report = review(tmp_path, command)
    assert refs(report) == {SourceRef(ELEMENT_IDENTIFIER, "input")}
    assert high(report).checkable


@pytest.mark.parametrize("value", ["$input.unsanitized.metadata.delimiter", "$input.unsanitized.ext"])
def test_what_galaxy_sets_on_the_dataset_model_is_clean(tmp_path, value):
    report = review(tmp_path, f"echo '{value}' '$input.element_identifier'")
    assert refs(report) == {SourceRef(ELEMENT_IDENTIFIER, "input")}
    assert high(report).checkable


@pytest.mark.parametrize(
    "opened", ["open(str($input))", "open($input.__str__)", "open($input.file_name)", "open($input.get_file_name())"]
)
def test_content_of_a_dataset_the_template_opens_is_checkable(tmp_path, opened):
    report = review(tmp_path, f"#set $n = {opened}.read().strip()\ntool --n $n")
    (finding,) = [f for f in report.findings if f.rule == "shell-injection"]
    assert finding.refs == (SourceRef(DATASET_CONTENT, "input"),)
    assert finding.checkable


def test_content_of_another_file_the_template_opens_is_opaque(tmp_path):
    report = review(tmp_path, "#set $n = open(str($text)).read().strip()\ntool --n $n")
    (finding,) = [f for f in report.findings if f.rule == "shell-injection"]
    assert finding.refs == (SourceRef(OPAQUE),)


def test_user_value_a_replace_puts_in_keeps_its_own_source(tmp_path):
    command = "#set $v = str($free).replace('N', str($word.value))\necho '$v' '$input.element_identifier'"
    report = review(tmp_path, command)
    assert report.unchecked_locations == {}
    assert all(f.checkable for f in report.findings if f.severity == HIGH)


def test_literal_text_of_a_built_replacement_is_the_templates(tmp_path):
    command = "#set $v = str($free).replace('a', \"'\" + str($letters))\necho '$v'"
    findings = [f for f in review(tmp_path, command).findings if f.severity == HIGH]
    assert findings and not any(f.checkable for f in findings)


def test_getattr_of_a_name_is_the_attribute(tmp_path):
    report = review(tmp_path, "echo '${input.__getattr__('name')}'", extra=UNSANITIZED)
    assert refs(report) == {SourceRef(DATASET_ATTRIBUTE, "input", "name")}


@pytest.mark.parametrize("codec", ["", "'utf-8'", "'ascii'"])
def test_utf8_bytes_of_a_value_keep_it_checkable(tmp_path, codec):
    command = f"#import json\n#set $j = json.dumps(str($input.element_identifier)).encode({codec}).decode()\necho '$j' '$free'"
    report = review(tmp_path, command)
    assert report.unchecked_locations == {}
    assert all(f.checkable for f in report.findings if f.severity == HIGH)


@pytest.mark.parametrize(
    "command,expected",
    [
        ("sed -e '$free' '$input'", True),
        ("sed --sandbox -e '$free' '$input'", False),
        # GNU sed reads every option before it runs, but the review only knows the options before the program.
        ("sed -e '$free' --sandbox '$input'", True),
    ],
)
def test_sandboxed_sed_program_runs_nothing(tmp_path, command, expected):
    rules = {f.rule for f in review(tmp_path, command.replace("$free", "$letters")).findings}
    assert ("nested-interpreter" in rules) is expected


@pytest.mark.parametrize("command", ["sed -e 's/x/$sq/' '$input'", "sh -c 'echo $sq'"])
def test_escaped_quote_stays_in_the_word_of_a_nested_program(tmp_path, command):
    # The shell reads '"'"' inside the single-quoted word; the program in it gets the quote.
    findings = [f for f in review(tmp_path, command).findings if f.severity == HIGH]
    assert {f.rule for f in findings} == {"nested-interpreter"}


def test_user_preference_is_checkable(tmp_path):
    finding = high(review(tmp_path, """echo "${__user__.extra_preferences.get('account|name', '')}" """))
    assert finding.refs == (SourceRef(USER_PREFERENCE, None, "account|name"),)
    assert finding.checkable


def test_reads_name_what_each_template_writes(tmp_path):
    report = review(tmp_path, "echo '$input.element_identifier' '$text' > '$out'")
    assert set(report.reads["command"]) == {SourceRef(ELEMENT_IDENTIFIER, "input"), SourceRef(TEXT, "text")}


def test_reads_of_a_template_not_followed_name_the_inputs_it_mentions(tmp_path):
    command = "echo '$searchList' '$input.info' '$input.metadata.comments' '${__user__.extra_preferences.get(\"a\")}'"
    reads = set(review(tmp_path, command).reads["command"])
    assert {
        SourceRef(DATASET_ATTRIBUTE, "input", "info"),
        SourceRef(METADATA, "input"),
        SourceRef(USER_PREFERENCE),
        SourceRef(ELEMENT_IDENTIFIER, "flat"),
    } <= reads
    assert SourceRef(DATASET_ATTRIBUTE, "flat", "info") in reads
    assert not any(ref.accessor == OPAQUE for ref in reads)


YAML_TOOL = """class: GalaxyTool
id: yaml_t
name: yaml_t
version: "1"
command: "cat '$input' > '$out'"
inputs:
- name: input
  type: data
  format: txt
outputs:
  out:
    format: txt
"""


def test_outputs_of_a_yaml_tool_are_outputs(tmp_path):
    path = tmp_path / "tool.yml"
    path.write_text(YAML_TOOL)
    report = review_tool_source(get_tool_source(str(path)))
    assert not any(ref.key == "out" for f in report.findings for ref in f.refs)
    assert report.reads["command"] == []


def test_findings_that_tie_sort_by_their_message():
    first = Finding(rule="r", kind="vulnerability", severity="low", message="b", location="command", line=1)
    second = Finding(rule="r", kind="vulnerability", severity="low", message="a", location="command", line=1)
    assert Report(findings=[first, second]).sorted() == Report(findings=[second, first]).sorted() == [second, first]
