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
