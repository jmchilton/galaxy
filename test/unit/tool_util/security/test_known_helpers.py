"""#def helpers of tools-iuc that look a parameter up by the name their caller passes."""

from __future__ import annotations

import pytest

from galaxy.tool_util.security import Report
from galaxy.tool_util.security.report import (
    CODE_CAPABILITIES,
    rendered,
)
from .test_review import (
    INPUTS,
    review,
    rules,
)

# tools-iuc bowtie2, bwa, bwa_mem2 and picard: read_group_macros.xml.
RG_PARAM = """#def rg_param(name)
    #if $varExists("rg")
        #return $rg.get($name, None)
    #else
        #return $getVar($name, None)
    #end if
#end def
"""

# tools-iuc picrust2: macros.xml, now and before 2.5.0.
GET_VAR_COND = """    #def getVarCond($sec_cond, $var)
        #if $varExists($var)
            #return $getVar($var)
        #else if $varExists($sec_cond + "." + $var)
            #return $getVar($sec_cond + "." + $var)
        #else
            #return
        #end if
    #end def
"""
GET_VAR_COND_PATHWAYS = """#def getVarCond($var)
    ## $var $varExists($var) $varExists("predict_pathways." + $var)
    #if $varExists($var)
        #return $getVar($var)
    #else if $varExists("predict_pathways." + $var)
        #return $getVar("predict_pathways." + $var)
    #else
        #return
    #end if
#end def
"""

SECTIONS = """
<section name="sec" title="sec"><param name="inner" type="text"><sanitizer sanitize="false"/></param></section>
<section name="predict_pathways" title="p"><param name="inner" type="text"><sanitizer sanitize="false"/></param></section>
"""


COMPUTED_GET_VAR = "Looks up a variable by a computed name with `getVar`"


def code(report: Report) -> set[str]:
    """The rules of the findings that refuse every job: template code that reaches what the job does not carry."""
    return {f.rule for f in report.findings if f.rule in CODE_CAPABILITIES and rendered(f.location)}


@pytest.mark.parametrize(
    "command",
    [
        RG_PARAM + "tool '${rg_param(str($text))}'",
        RG_PARAM + "tool '${rg_param(name='free')}'",
        RG_PARAM + "tool '${rg_param('fr' + 'ee')}'",
        RG_PARAM + "#set $f = $rg_param\ntool '${f('free')}'",
        RG_PARAM + "tool '${getVar('rg_param')('free')}'",
        RG_PARAM + "tool '${self.rg_param('free')}'",
        RG_PARAM + "#def g($f=$rg_param)\n#return $f('free')\n#end def\ntool '$g()'",
        RG_PARAM + "#for $rg_param in [$getVar]\ntool '${rg_param('free')}'\n#end for",
        RG_PARAM + "#set global $rg_param = $getVar\ntool '${rg_param('free')}'",
        RG_PARAM + "#def rg_param(name)\n#return $getVar($name)\n#end def\ntool '${rg_param('free')}'",
        RG_PARAM.replace("None)\n    #end if", "'')\n    #end if") + "tool '${rg_param('free')}'",
        RG_PARAM + "#def varExists($n)\n#return False\n#end def\ntool '${rg_param('free')}'",
        RG_PARAM + "#include source=$text#\ntool '${rg_param('free')}'",
        RG_PARAM + "$_handleCheetahInclude(str($text), includeFrom='str')\ntool '${rg_param('free')}'",
        # Python reads the full-width letter as the plain one: this rebinds the helper.
        RG_PARAM + "#set ｒg_param = getVar\ntool '${rg_param('free')}'",
        RG_PARAM + "#silent $rg_param.__call__('free')\ntool",
        RG_PARAM + "#silent self._CHEETAH__globalSetVars.update({'f': 1})\ntool '${rg_param('free')}'",
        RG_PARAM + "#set $write = $getVar\ntool '${rg_param('free')}'",
        # The template object comes before the namespace.
        RG_PARAM + "tool '${rg_param('searchList')}'",
        RG_PARAM + "#set $searchList = 1\ntool '${rg_param('searchList')}'",
        RG_PARAM + "tool '${rg_param('_CHEETAH__searchList')}'",
        RG_PARAM + "#def evil()\n#return $free\n#end def\ntool '${rg_param('evil')}'",
        RG_PARAM + "#def text()\n#return $free\n#end def\ntool '${rg_param('text')}'",
        # A name the template binds anywhere, run or not.
        RG_PARAM + "#set global $g = $free\ntool '${rg_param('g')}'",
        RG_PARAM
        + "#def text()\n#return $free\n#end def\ntool '${rg_param('text')}'\n#if False\n#set global $text = 1\n#end if",
        RG_PARAM + "#set $text = $free\ntool '${rg_param('text')}'",
        RG_PARAM + "#set $self.text = $free\ntool '${rg_param('text')}'",
        # Found on the template object or on the #set global dict before the namespace.
        RG_PARAM + "tool '${rg_param('__unicode__')}'",
        RG_PARAM + "#set global $g = $free\n#for $v in $rg_param('values')\ntool '$v'\n#end for",
        RG_PARAM + "tool '${rg_param('text.__class__')}'",
        # The TreeDict Galaxy retries a namespace as has the raw values under `data`.
        RG_PARAM + "tool '${rg_param('data.free')}'",
        # The helper's own `$rg` is a #def or a #set global value.
        RG_PARAM + "#def rg()\n#return {'text': $free}\n#end def\ntool '${rg_param('text')}'",
        RG_PARAM + "#set global $rg = {'text': $free}\ntool '${rg_param('text')}'",
        # The #set global store, reached other than as Cheetah reaches it.
        RG_PARAM
        + "#silent $self._CHEETAH__globalSetVars.update(dict.fromkeys(['text'], $free))\ntool '${rg_param('text')}'",
    ],
)
def test_misused_known_helper_is_reflection(tmp_path, command):
    assert "template-reflection" in code(review(tmp_path, command))


def test_known_helper_reaching_the_model_is_model_access(tmp_path):
    report = review(tmp_path, RG_PARAM + "tool '${rg_param('input.unsanitized.history.name')}'")
    assert code(report) == {"template-model-access"}


@pytest.mark.parametrize("name,injection", [("free", True), ("$free", True), ("text", False), ("absent", False)])
def test_known_helper_called_with_literal_text_reads_that_parameter(tmp_path, name, injection):
    report = review(tmp_path, RG_PARAM + f"tool '${{rg_param('{name}')}}' '${{rg_param('text')}}'")
    assert code(report) == set()
    assert (("shell-injection", "high") in rules(report)) is injection


@pytest.mark.parametrize(
    "helper,call",
    [
        (GET_VAR_COND, "getVarCond('sec', 'inner')"),
        (GET_VAR_COND, "getVarCond('sec', 'free')"),
        (GET_VAR_COND_PATHWAYS, "getVarCond('inner')"),
    ],
)
def test_known_helper_with_a_section_reads_the_parameter_in_it(tmp_path, helper, call):
    report = review(tmp_path, helper + f"tool '${{{call}}}'", inputs=INPUTS + SECTIONS)
    assert code(report) == set()
    assert ("shell-injection", "high") in rules(report)


@pytest.mark.parametrize("name", ["str", "time", "absent"])
def test_known_helper_reads_a_name_no_input_has_as_a_job_parameter(tmp_path, name):
    report = review(tmp_path, RG_PARAM + f"tool ${{rg_param('{name}')}}", extra='<options sanitize="False"/>')
    keys = {ref.key for f in report.findings if f.rule == "shell-injection" for ref in f.refs}
    assert name in keys


def nested(body: str, depth: int = 9) -> str:
    """`body` in a #def called through ``depth`` #defs."""
    defs = f"#def f1()\n{body}\n#end def\n"
    defs += "".join(f"#def f{i}()\n$f{i - 1}()\n#end def\n" for i in range(2, depth + 1))
    return defs + f"tool $f{depth}()"


@pytest.mark.parametrize("body", ["${rg_param('free')}", "$free"])
def test_helpers_nested_past_the_limit_are_not_followed(tmp_path, body):
    report = review(tmp_path, RG_PARAM + nested(body))
    assert any("#def calls nest deeper than" in note for note in report.unanalyzed)


def test_known_helper_never_called_is_dropped(tmp_path):
    assert code(review(tmp_path, RG_PARAM + "tool")) == set()


# tools-iuc hmmer3: macros.xml.
OFORMAT = """#if $oformat:
    #for o in str($oformat).split(','):
        --$o '$getVar($o, 'MISSING_OUTPUT'+$o)'
    #end for
#end if
"""


def select(options: str = '<option value="tblout"/><option value="free"/>', attrs: str = "") -> str:
    return INPUTS + f'<param name="oformat" type="select" multiple="true" {attrs}>{options}</param>'


@pytest.mark.parametrize(
    "options,injection",
    [
        ('<option value="tblout"/><option value="free"/>', True),
        ('<option value="tblout"/><option value="word"/>', False),
    ],
)
def test_loop_over_select_values_reads_each_option(tmp_path, options, injection):
    report = review(tmp_path, OFORMAT + "tool", inputs=select(options))
    assert code(report) == set()
    assert (("shell-injection", "high") in rules(report)) is injection


@pytest.mark.parametrize(
    "command,inputs",
    [
        (OFORMAT.replace("$oformat", "$text"), select()),
        (OFORMAT.replace("','", "';'"), select()),
        (OFORMAT, select('<option value="tblout"/><option value="a-b"/>')),
        (OFORMAT, select('<option value="tblout"/><option value="values"/>')),
        (OFORMAT, select(attrs='separator=";"')),
        (OFORMAT, select('<option value="tblout"/><sanitizer sanitize="false"/>')),
        (OFORMAT, select('<options from_parameter="tool.app.datatypes_registry.upload_file_formats"/>')),
        (OFORMAT, INPUTS + '<param name="oformat" type="data_column" data_ref="input"/>'),
        (OFORMAT.replace("--$o", "#set $o = $free\n--$o"), select()),
        (OFORMAT.replace("--$o", "--$o.x"), select()),
        (OFORMAT.replace("--$o", "#set $n = o\n--$n"), select()),
        ("#set $oformat = $free\n" + OFORMAT, select()),
        ("#set $str = $text\n" + OFORMAT, select()),
        ("#set global $tblout = $free\n" + OFORMAT, select()),
        ("#silent $searchList()\n" + OFORMAT, select()),
        ("#silent $self.searchList()\n" + OFORMAT, select()),
        ("#silent $self._CHEETAH__globalSetVars.update(dict.fromkeys(['oformat'], 'free'))\n" + OFORMAT, select()),
        # Cheetah's own local SL comes before the namespace.
        (OFORMAT.replace("$oformat", "$SL"), select().replace("oformat", "SL")),
        ("#def f()\n" + OFORMAT + "#end def\n$f()", select()),
    ],
)
def test_loop_over_other_values_is_reflection(tmp_path, command, inputs):
    report = review(tmp_path, command + "tool", inputs=inputs)
    assert any(f.message.startswith(COMPUTED_GET_VAR) for f in report.findings)


# tools-iuc gatk4: macros.xml.
SECTIONS_SET = "#set global $sections = ['', 'sec.']\n"
SECTIONS_LOOP = """#for $sect in $sections
    #if $varExists($sect + "inner")
        tool '$getVar($sect + "inner")'
    #end if
#end for
"""


@pytest.mark.parametrize("sections,name,injection", [("['', 'sec.']", "inner", True), ("['']", "word", False)])
def test_loop_over_a_global_list_reads_each_element(tmp_path, sections, name, injection):
    command = f"#set global $sections = {sections}\n" + SECTIONS_LOOP.replace("inner", name)
    report = review(tmp_path, command, inputs=INPUTS + SECTIONS)
    assert code(report) == set()
    assert (("shell-injection", "high") in rules(report)) is injection


@pytest.mark.parametrize(
    "command",
    [
        SECTIONS_LOOP + SECTIONS_SET,
        "#if $text\n" + SECTIONS_SET + "#end if\n" + SECTIONS_LOOP,
        SECTIONS_SET.replace("'sec.'", "$free") + SECTIONS_LOOP,
        SECTIONS_SET.replace("['', 'sec.']", "'sec.'") + SECTIONS_LOOP,
        SECTIONS_SET + "#set global $sections = ['free']\n" + SECTIONS_LOOP,
        SECTIONS_SET + "#set $sections = ['free']\n" + SECTIONS_LOOP,
        SECTIONS_SET + "#silent $sections.append('x')\n" + SECTIONS_LOOP,
        SECTIONS_SET + "#silent $getVar('sections').append('x')\n" + SECTIONS_LOOP,
        SECTIONS_SET.replace("sections", "values") + SECTIONS_LOOP.replace("sections", "values"),
        SECTIONS_SET + "#silent $searchList()\n" + SECTIONS_LOOP,
        SECTIONS_SET + "#silent $self._CHEETAH__globalSetVars['sec' + 'tions'].append('free')\n" + SECTIONS_LOOP,
        SECTIONS_SET
        + "#for $l in $self._CHEETAH__globalSetVars.values()\n#silent $l.append('free')\n#end for\n"
        + SECTIONS_LOOP,
        SECTIONS_SET + "#def f()\n" + SECTIONS_LOOP + "#end def\n$f()",
    ],
)
def test_loop_over_a_list_set_otherwise_is_reflection(tmp_path, command):
    report = review(tmp_path, command + "tool", inputs=INPUTS + SECTIONS)
    assert any(f.message.startswith(COMPUTED_GET_VAR) for f in report.findings)


def sections_macros(set_sections: str = SECTIONS_SET) -> str:
    return f"""<macros>
<template name="set_sections"><![CDATA[{set_sections}]]></template>
<template name="loop"><![CDATA[{SECTIONS_LOOP}]]></template>
<template name="outer"><![CDATA[#include source=$loop#
]]></template>
</macros>"""


@pytest.mark.parametrize("loop", ["loop", "outer"])
def test_loop_in_a_template_macro_over_a_list_a_macro_sets_reads_each_element(tmp_path, loop):
    command = f"#include source=$set_sections#\n#include source=${loop}#\ntool"
    report = review(tmp_path, command, inputs=INPUTS + SECTIONS, extra=sections_macros())
    assert code(report) == set()
    assert ("shell-injection", "high") in rules(report)


@pytest.mark.parametrize(
    "command,set_sections",
    [
        ("#include source=$loop#\n#include source=$set_sections#\n", SECTIONS_SET),
        ("#include source=$outer#\n#include source=$set_sections#\n#include source=$loop#\n", SECTIONS_SET),
        ("#if $text\n#include source=$set_sections#\n#end if\n#include source=$loop#\n", SECTIONS_SET),
        ("#include source=$set_sections#\n#include source=$loop#\n", "#if $text\n#return\n#end if\n" + SECTIONS_SET),
        ("#include source=$set_sections#\n#include source=$loop#\n", "#stop\n" + SECTIONS_SET),
    ],
)
def test_loop_in_a_template_macro_over_a_list_set_otherwise_is_reflection(tmp_path, command, set_sections):
    report = review(tmp_path, command + "tool", inputs=INPUTS + SECTIONS, extra=sections_macros(set_sections))
    assert any(f.message.startswith(COMPUTED_GET_VAR) for f in report.findings)


# galaxytools llm_hub, tools-galaxyp idpqonvert: loops over a literal list.
LITERAL_LOOPS = [
    "#for $n in ['text', 'NAME']\ntool '$getVar($n)'\n#end for",
    "#for $k, $n in [('a', 'text'), ('b', 'NAME')]\ntool $k '$getVar($n, None)'\n#end for",
    "#for $e in ['te:xt', 'NA!ME']\n#set $n = $e.replace(':', '').replace('!', '')\ntool '$getVar($n)'\n#continue\n#end for",
]


@pytest.mark.parametrize("command", LITERAL_LOOPS)
@pytest.mark.parametrize("name,injection", [("free", True), ("word", False)])
def test_loop_over_a_literal_list_reads_each_element(tmp_path, command, name, injection):
    report = review(tmp_path, command.replace("NAME", name).replace("NA!ME", f"{name[:2]}!{name[2:]}"))
    assert not report.unanalyzed
    assert code(report) == set()
    assert (("shell-injection", "high") in rules(report)) is injection


def test_loop_over_a_literal_list_reads_a_section_named_with_a_dash(tmp_path):
    inputs = (
        INPUTS
        + '<section name="scoring" title="s"><param name="ms-gf_w" type="text"><sanitizer sanitize="false"/></param></section>'
    )
    command = "#for $e in ['ms-gf:w']\n#set $n = $e.replace(':', '_')\ntool '$getVar('scoring.' + $n)'\n#end for"
    report = review(tmp_path, command, inputs=inputs)
    assert not report.unanalyzed
    assert code(report) == set()
    assert ("shell-injection", "high") in rules(report)


# galaxytools llm_hub: a literal loop over two inputs, their element identifiers cleaned with re.sub.
LLM_HUB = """#import os
#import re
#for $input_type, $param in [('text', 'flat'), ('image', 'input')]
    #set context = $getVar($param, None)
    #if $context
        #for $i in ($context if isinstance($context, list) else [$context])
            #set file_name = re.sub('[^\\w\\-]', '_', os.path.splitext($i.element_identifier)[0])
            ln -s '$i' '${file_name}.txt' &&
        #end for
    #end if
#end for
tool"""


def test_loop_over_a_literal_list_of_inputs_cleaned_with_re_sub(tmp_path):
    report = review(tmp_path, LLM_HUB)
    assert code(report) == set()
    assert not report.unanalyzed
    assert ("shell-injection", "high") not in rules(report)


# galaxytools infernal cmbuild: a loop over the values of a multiple select.
VALUE_LOOP = "#for j in $oformat.value:\n--$j '$getVar($j)'\n#end for\n"


@pytest.mark.parametrize(
    "options,injection",
    [
        ('<option value="tblout"/><option value="free"/>', True),
        ('<option value="tblout"/><option value="word"/>', False),
    ],
)
def test_loop_over_a_select_value_reads_each_option(tmp_path, options, injection):
    report = review(tmp_path, VALUE_LOOP + "tool", inputs=select(options))
    assert not report.unanalyzed
    assert code(report) == set()
    assert (("shell-injection", "high") in rules(report)) is injection


def test_loop_over_a_select_value_reads_the_parameter_a_letter_of_an_option_names(tmp_path):
    inputs = select('<option value="tblout"/><option value="word"/>') + (
        '<param name="t" type="text"><sanitizer sanitize="false"/></param>'
    )
    report = review(tmp_path, VALUE_LOOP + "tool", inputs=inputs)
    assert code(report) == set()
    assert ("shell-injection", "high") in rules(report)


TWO_SELECTS = """<conditional name="c">
<param name="kind" type="select"><option value="a"/><option value="b"/></param>
<when value="a"><param name="oformat" type="select" multiple="true"><option value="tblout"/></param></when>
<when value="b"><param name="oformat" type="select" multiple="true"><option value="free"/></param></when>
</conditional>"""


@pytest.mark.parametrize(
    "command,inputs",
    [
        ("#for $n in ['text', $free]\ntool '$getVar($n)'\n#end for", INPUTS),
        ("#for $n in ['text', 1]\ntool '$getVar($n)'\n#end for", INPUTS),
        ("#for $k, $n in [('a', 'text', 'b')]\ntool '$getVar($n)'\n#end for", INPUTS),
        ("#for $k, $n in [('a', 'text'), 'bc']\ntool '$getVar($n)'\n#end for", INPUTS),
        ("#for $e in ['text']\n#set $n = $e + $free\ntool '$getVar($n)'\n#end for", INPUTS),
        ("#for $e in ['text']\n#set $n = $e\n#set $n = $free\ntool '$getVar($n)'\n#end for", INPUTS),
        ("#for $e in ['text']\n#if $text\n#set $n = $e\n#end if\ntool '$getVar($n)'\n#end for", INPUTS),
        (
            "#for $e in ['text']\n#set $n = $e\n#if $text\n#set $n = $free\n#end if\ntool '$getVar($n)'\n#end for",
            INPUTS,
        ),
        ("#for $e in ['te:xt']\n#set $n = $e.replace(':', $free)\ntool '$getVar($n)'\n#end for", INPUTS),
        ("#for $e in ['text']\n#set $n = $e.upper()\ntool '$getVar($n)'\n#end for", INPUTS),
        ("#for $e in ['text']\n#set $e = $free\ntool '$getVar($e)'\n#end for", INPUTS),
        (VALUE_LOOP, INPUTS),
        (VALUE_LOOP, select('<option value="tblout"/><sanitizer sanitize="false"/>')),
        (VALUE_LOOP, select('<options from_parameter="tool.app.datatypes_registry.upload_file_formats"/>')),
        (VALUE_LOOP.replace(".value", ".fields"), select()),
        (VALUE_LOOP.replace(".value", ".value.x"), select()),
        ("#set $oformat = $free\n" + VALUE_LOOP, select()),
        # A letter of a single select's option is the loop variable.
        (VALUE_LOOP, select('<option value="tblout"/><option value="join"/>')),
        # Read before the #set: the previous element, or a job parameter `n` at first.
        ("#for $e in ['text']\ntool '$getVar($n)'\n#set $n = $e\n#end for", INPUTS),
        ("#for $e in ['text']\n#set $n = $e\n#for $n in [$free]\nx\n#end for\ntool '$getVar($n)'\n#end for", INPUTS),
        ("#for $e in ['text']\n#set $n = $text.replace(':', '')\ntool '$getVar($n)'\n#end for", INPUTS),
        # In a lambda, generator or comprehension, the lookup does not see the method's locals.
        ("#for $n in ['word']\ntool '${''.join($getVar($n) for _x in [1])}'\n#end for", INPUTS),
        ("#for $n in ['word']\n#set $f = lambda: $getVar($n)\ntool '${f()}'\n#end for", INPUTS),
        ("#for $n in ['word']\ntool '${''.join([$getVar($n) for _x in [1]])}'\n#end for", INPUTS),
        ("#for $e in ['word']\n#set $n = $e\ntool '${''.join($getVar($n) for _x in [1])}'\n#end for", INPUTS),
        ("#set global $e = $free\n#for $e in ['word']\ntool '${''.join($getVar($e) for _x in [1])}'\n#end for", INPUTS),
        (VALUE_LOOP.replace("'$getVar($j)'", "'${''.join($getVar($j) for _x in [1])}'"), select()),
        (OFORMAT.replace("'$getVar($o, 'MISSING_OUTPUT'+$o)'", "'${''.join($getVar($o) for _x in [1])}'"), select()),
        # A read in a nested loop before the statement in it that binds the name again.
        (
            "#for $e in ['text']\n#set $n = $e\n#for $x in [1, 2]\ntool '$getVar($n)'\n#set $n = $free\n#end for\n#end for",
            INPUTS,
        ),
        # `replace` with a count, and another method given two texts, are not folded.
        ("#for $e in ['te:x:t']\n#set $n = $e.replace(':', '', 1)\ntool '$getVar($n)'\n#end for", INPUTS),
        ("#for $e in ['te:xt']\n#set $n = $e.format(':', '')\ntool '$getVar($n)'\n#end for", INPUTS),
        # A later part of the name is private or a dunder.
        ("#for $n in ['text.__class__']\ntool '$getVar($n)'\n#end for", INPUTS),
        ("#for $n in ['text._value']\ntool '$getVar($n)'\n#end for", INPUTS),
        # Two selects answer for the path, with different options.
        (VALUE_LOOP.replace("$oformat", "$c.oformat"), INPUTS + TWO_SELECTS),
        # Set and dict comprehensions have their own frame too.
        ("#for $n in ['word']\ntool '${''.join({$getVar($n) for _x in [1]})}'\n#end for", INPUTS),
        ("#for $n in ['word']\ntool '${''.join({$getVar($n): 1 for _x in [1]})}'\n#end for", INPUTS),
    ],
)
def test_loop_over_values_the_review_cannot_list_is_reflection(tmp_path, command, inputs):
    report = review(tmp_path, command + "tool", inputs=inputs)
    assert not any("does not compile" in note for note in report.unanalyzed)
    assert any(f.message.startswith(COMPUTED_GET_VAR) for f in report.findings)
