import gc
import logging
import os
import threading
import time
from types import SimpleNamespace
from typing import (
    Any,
    cast,
)

import pytest

from galaxy import model
from galaxy.app_unittest_utils.galaxy_mock import MockApp
from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.security import (
    review_tool_source,
    ReviewTimeout,
)
from galaxy.tool_util.security.report import (
    ELEMENT_IDENTIFIER,
    RAW,
)
from galaxy.tools import (
    create_tool_from_source,
    security_review,
    Tool,
)
from galaxy.tools.evaluation import ToolEvaluator
from galaxy.tools.parameters.basic import ToolParameter
from galaxy.tools.security_review import (
    _identifiers,
    ANALYSED,
    ENFORCE,
    LOG,
    NOT_ANALYSED,
    OFF,
    reviewed_tool_source,
    ToolInputRejected,
    ToolSecurityReviewer,
)
from galaxy.tools.wrappers import (
    DatasetCollectionWrapper,
    DatasetListWrapper,
    InputValueWrapper,
)

ECHO_IDS = """<tool id="echo_ids" name="Echo identifiers" version="1.0" profile="24.0">
  <command><![CDATA[
#for $e in $input
echo '$e.element_identifier' >> '$out';
#end for
echo '${word.value}' >> '$out'
  ]]></command>
  <inputs>
    <param name="input" type="data_collection" collection_type="list" format="txt"/>
    <param name="word" type="text"/>
  </inputs>
  <outputs><data name="out" format="txt"/></outputs>
</tool>
"""

# One user value in the command: a quote in it can only matter with a command character after it.
ECHO_ONE = ECHO_IDS.replace("echo '${word.value}' >> '$out'", "true")

NO_COMMAND = """<tool id="no_command" name="No command" version="1.0">
  <inputs><param name="word" type="text"/></inputs>
  <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


@pytest.fixture
def app():
    return MockApp()


def make_tool(app, tmp_path, contents: str = ECHO_IDS, name: str = "tool.xml") -> Tool:
    path = os.path.join(tmp_path, name)
    with open(path, "w") as fh:
        fh.write(contents)
    return create_tool_from_source(app, get_tool_source(path), config_file=path)


def reviewer(tmp_path, mode: str = LOG, timeout: float = 5.0) -> ToolSecurityReviewer:
    return ToolSecurityReviewer(mode, timeout)


def hdca(name: str, identifiers: list[str]) -> model.HistoryDatasetCollectionAssociation:
    collection = model.DatasetCollection(collection_type="list")
    for i, identifier in enumerate(identifiers):
        hda = model.HistoryDatasetAssociation(name=f"dataset {i}", extension="txt")
        model.DatasetCollectionElement(
            collection=collection, element=hda, element_identifier=identifier, element_index=i
        )
    return model.HistoryDatasetCollectionAssociation(name=name, collection=collection)


def evaluator(app, tool: Tool, identifiers: list[str], word: str = "plain", name: str = "my list") -> Any:
    stub = SimpleNamespace(job=SimpleNamespace(id=7), consumes_names=False, consumes_identifiers=False)
    # As in ToolEvaluator, the wrappers report reading identifiers and names to the evaluator.
    collection = DatasetCollectionWrapper(
        None,
        hdca(name, identifiers),
        datatypes_registry=app.datatypes_registry,
        tool_evaluator=cast(ToolEvaluator, stub),
    )
    stub.param_dict = {
        "input": collection,
        "word": InputValueWrapper(cast(ToolParameter, tool.inputs["word"]), word),
    }
    return stub


# -- reviews ---------------------------------------------------------------------------------


def test_first_use_computes_the_review(app, tmp_path):
    review = reviewer(tmp_path).review(make_tool(app, tmp_path))
    assert review is not None and review.status == ANALYSED
    assert {f.rule for f in review.checked_findings} == {"shell-injection"}


def test_review_is_kept_for_the_tool(app, tmp_path, monkeypatch):
    r = reviewer(tmp_path)
    tool = make_tool(app, tmp_path)
    first = r.review(tool)

    def fail(*args, **kwds):
        raise AssertionError("reviewed again")

    monkeypatch.setattr(security_review, "review_tool_source", fail)
    assert r.review(tool) is first


def test_reloaded_tool_is_reviewed_again(app, tmp_path):
    r = reviewer(tmp_path)
    r.review(make_tool(app, tmp_path))
    # A reload creates a new Tool object, here with a changed template.
    changed = make_tool(app, tmp_path, ECHO_IDS.replace("echo '${word.value}'", "echo '${word}'"))
    review = r.review(changed)
    assert review is not None
    assert {ref.accessor for f in review.checked_findings for ref in f.refs} == {ELEMENT_IDENTIFIER}


def test_review_goes_with_its_tool(app, tmp_path):
    r = reviewer(tmp_path)
    tool = make_tool(app, tmp_path)
    r.review(tool)
    assert len(r._reviews) == 1
    del tool
    gc.collect()
    assert len(r._reviews) == 0


def test_concurrent_first_jobs_review_once(app, tmp_path, monkeypatch):
    calls = []

    def counted(*args, **kwds):
        calls.append(1)
        time.sleep(0.05)
        return review_tool_source(*args, **kwds)

    monkeypatch.setattr(security_review, "review_tool_source", counted)
    r = reviewer(tmp_path)
    tool = make_tool(app, tmp_path)
    threads = [threading.Thread(target=r.review, args=(tool,)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(calls) == 1


def test_timeout_is_recorded_as_not_analysed(app, tmp_path, caplog):
    r = reviewer(tmp_path, timeout=-1)
    tool = make_tool(app, tmp_path)
    review = r.review(tool)
    assert review is not None and review.status == NOT_ANALYSED and review.reason == "timeout"
    assert "took longer than" in caplog.text
    # Kept, so the next job does not try again.
    assert r.review(tool) is review
    r.check_job(tool, evaluator(app, tool, ["a'b"]))


def test_analyser_error_is_recorded_as_not_analysed(app, tmp_path, monkeypatch):
    def broken(*args, **kwds):
        raise RuntimeError("analyser bug")

    monkeypatch.setattr(security_review, "review_tool_source", broken)
    tool = make_tool(app, tmp_path)
    r = reviewer(tmp_path, ENFORCE)
    review = r.review(tool)
    assert review is not None and review.status == NOT_ANALYSED and review.reason == "error: RuntimeError"
    r.check_job(tool, evaluator(app, tool, ["a'b"]))


def test_timeout_raised_while_reviewing(app, tmp_path, monkeypatch):
    def slow(*args, **kwds):
        raise ReviewTimeout()

    monkeypatch.setattr(security_review, "review_tool_source", slow)
    review = reviewer(tmp_path).review(make_tool(app, tmp_path))
    assert review is not None and review.reason == "timeout"


def test_summary_is_logged_once_when_computed(app, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger=security_review.__name__)
    tool = make_tool(app, tmp_path)
    r = reviewer(tmp_path)
    r.review(tool)
    assert caplog.text.count("Security review of tool echo_ids version 1.0: 2 high finding(s)") == 1
    caplog.clear()
    r.review(tool)
    assert "Security review of tool" not in caplog.text


def test_tool_without_command_is_not_reviewed(app, tmp_path):
    tool = make_tool(app, tmp_path, NO_COMMAND)
    assert reviewed_tool_source(tool) is None
    assert reviewer(tmp_path).review(tool) is None


def test_tool_method(app, tmp_path):
    tool = make_tool(app, tmp_path)
    assert tool.security_review() is None  # MockApp has reviews off
    app.tool_security_reviewer = reviewer(tmp_path)
    review = tool.security_review()
    assert review is not None and review.status == ANALYSED


# -- off ---------------------------------------------------------------------------------------


def test_off_does_nothing(app, tmp_path, monkeypatch):
    def fail(*args, **kwds):
        raise AssertionError("reviewed while off")

    monkeypatch.setattr(security_review, "review_tool_source", fail)
    r = reviewer(tmp_path, OFF)
    tool = make_tool(app, tmp_path)
    assert r.review(tool) is None
    r.check_job(tool, evaluator(app, tool, ["a'b; touch /tmp/x"]))


# -- job values --------------------------------------------------------------------------------


def test_enforce_refuses_an_identifier_that_closes_the_quotes(app, tmp_path):
    tool = make_tool(app, tmp_path)
    job = evaluator(app, tool, ["sample_1", "it';id;'s"])
    with pytest.raises(ToolInputRejected) as e:
        reviewer(tmp_path, ENFORCE).check_job(tool, job)
    message = str(e.value)
    assert "an element identifier or the name of input 'input' contains the characters [' ;]" in message
    assert "Echo identifiers" in message and "echo_ids" in message
    assert "id;" not in message
    # Reading identifiers through the wrappers must not change how the job cache sees the job.
    assert job.consumes_identifiers is False and job.consumes_names is False


def test_log_warns_and_lets_the_job_run(app, tmp_path, caplog):
    tool = make_tool(app, tmp_path)
    reviewer(tmp_path, LOG).check_job(tool, evaluator(app, tool, ["it'|'s"], word="x';y"))
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert all("job 7 of tool echo_ids version 1.0" in w for w in warnings)
    assert any("element_identifier of input 'input' contains [' |]" in w for w in warnings)
    assert any("raw of input 'word' contains [' ;]" in w for w in warnings)
    assert all("it'|'s" not in w and "x';y" not in w for w in warnings)


@pytest.mark.parametrize("mode", [LOG, ENFORCE])
def test_harmless_values_pass(app, tmp_path, caplog, mode):
    tool = make_tool(app, tmp_path)
    # A command character stays inside the quotes.
    reviewer(tmp_path, mode).check_job(tool, evaluator(app, tool, ["sample 1", "a;b|c"], word="a b;c"))
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize("mode", [LOG, ENFORCE])
def test_lone_quote_passes_when_it_is_the_only_user_value(app, tmp_path, caplog, mode):
    tool = make_tool(app, tmp_path, ECHO_ONE, "one.xml")
    reviewer(tmp_path, mode).check_job(tool, evaluator(app, tool, ["sample 1", "Bob's reads"], name="Bob's list"))
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_lone_quote_counts_when_another_value_brings_a_command(app, tmp_path):
    # `echo 'Bob's' ...; echo 'a;b'`: the stray quote leaves the `;` of the next value unquoted.
    tool = make_tool(app, tmp_path)
    with pytest.raises(ToolInputRejected) as e:
        reviewer(tmp_path, ENFORCE).check_job(tool, evaluator(app, tool, ["Bob's reads"], word="a;b"))
    assert "the value of input 'word' contains the characters [;]" in str(e.value)
    assert "an element identifier or the name of input 'input' contains the characters [']" in str(e.value)


@pytest.mark.parametrize("mode", [LOG, ENFORCE])
def test_lone_quote_passes_next_to_harmless_values(app, tmp_path, caplog, mode):
    tool = make_tool(app, tmp_path)
    reviewer(tmp_path, mode).check_job(tool, evaluator(app, tool, ["Bob's reads"], word="it's fine"))
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize(
    "written",
    [
        # `q` can only close its quotes (a medium finding, never checked by itself)...
        "echo '$q'",
        # ...or repr's `"` closes the double quotes and q's own `'` opens new ones.
        'echo "${repr(str($q))}"',
    ],
)
def test_quote_from_a_medium_finding_frees_another_value(app, tmp_path, written):
    # Either is enough to leave the command characters of `word` unquoted.
    closer = ECHO_IDS.replace(
        '<param name="word" type="text"/>',
        """<param name="word" type="text"/>
    <param name="q" type="text"><sanitizer><valid initial="string.ascii_letters"><add value="&apos;"/></valid>
    </sanitizer></param>""",
    ).replace("echo '${word.value}' >> '$out'", f"{written} >> '$out' && echo '${{word.value}}' >> '$out'")
    tool = make_tool(app, tmp_path, closer, "closer.xml")
    job = evaluator(app, tool, ["a"], word=";id;#")
    job.param_dict["q"] = InputValueWrapper(cast(ToolParameter, tool.inputs["q"]), "'")
    with pytest.raises(ToolInputRejected):
        reviewer(tmp_path, ENFORCE).check_job(tool, job)
    job.param_dict["q"] = InputValueWrapper(cast(ToolParameter, tool.inputs["q"]), "plain")
    reviewer(tmp_path, ENFORCE).check_job(tool, job)


SCRIPT = """<tool id="script" name="Script" version="1.0" profile="24.0">
  <command>python '$script'</command>
  <configfiles><configfile name="script">print('$q', '$x')</configfile></configfiles>
  <inputs>
    <param name="q" type="text"><sanitizer><valid initial="string.ascii_letters"><add value="\\"/></valid></sanitizer></param>
    <param name="x" type="text"><sanitizer><valid initial="string.printable"><remove value="&apos;"/></valid></sanitizer></param>
  </inputs>
  <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


@pytest.mark.parametrize(
    "q,x,refused",
    [
        # q can end in a backslash but does not: x stays inside its string.
        ("a", 'say "hi" (now)', False),
        # print('\\', '), print(1), (') runs print(1).
        ("\\", "), print(1), (", True),
    ],
)
def test_value_after_an_escaped_quote_counts_only_when_one_is_escaped(app, tmp_path, q, x, refused):
    tool = make_tool(app, tmp_path, SCRIPT, "script.xml")
    job: Any = SimpleNamespace(job=SimpleNamespace(id=7), consumes_names=False, consumes_identifiers=False)
    job.param_dict = {
        name: InputValueWrapper(cast(ToolParameter, tool.inputs[name]), value) for name, value in (("q", q), ("x", x))
    }
    if refused:
        with pytest.raises(ToolInputRejected):
            reviewer(tmp_path, ENFORCE).check_job(tool, job)
    else:
        reviewer(tmp_path, ENFORCE).check_job(tool, job)


def test_collection_name_is_checked(app, tmp_path):
    # `$c.name` gives the collection's name, and the review does not tell it from element identifiers.
    tool = make_tool(app, tmp_path)
    with pytest.raises(ToolInputRejected):
        reviewer(tmp_path, ENFORCE).check_job(tool, evaluator(app, tool, ["a"], name="Bob's;list"))


def test_characters_of_all_values_count_together(app, tmp_path):
    # A template may join the identifiers into one string, where one brings the quote and another the `;`.
    tool = make_tool(app, tmp_path, ECHO_ONE, "one.xml")
    with pytest.raises(ToolInputRejected):
        reviewer(tmp_path, ENFORCE).check_job(tool, evaluator(app, tool, ["Bob's", "a;b"]))


def test_raw_value_is_checked(app, tmp_path):
    tool = make_tool(app, tmp_path)
    with pytest.raises(ToolInputRejected) as e:
        reviewer(tmp_path, ENFORCE).check_job(tool, evaluator(app, tool, ["a"], word="it';id"))
    assert "the value of input 'word' contains the characters [' ;]" in str(e.value)


def test_rewritten_value_is_reported_as_not_checkable(app, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger=security_review.__name__)
    rewriting = ECHO_IDS.replace("echo '${word.value}'", "echo ${str($word).replace('__gt__', '>')}")
    tool = make_tool(app, tmp_path, rewriting, "rewriting.xml")
    review = reviewer(tmp_path, ENFORCE).review(tool)
    # The rewritten value can bring the quote that lets the identifiers out: nothing is checkable.
    assert review is not None and len(review.unchecked_findings) == 2 and not review.checked_findings
    assert "(2 cannot be checked against job values)" in caplog.text
    reviewer(tmp_path, ENFORCE).check_job(tool, evaluator(app, tool, ["a"], word="a__gt__/tmp/x"))


def test_identifiers_of_nested_collections_and_multiple_inputs(app):
    inner = model.DatasetCollection(collection_type="paired")
    for i, identifier in enumerate(["forward", "rev'erse"]):
        hda = model.HistoryDatasetAssociation(name=f"d{i}", extension="txt")
        model.DatasetCollectionElement(collection=inner, element=hda, element_identifier=identifier, element_index=i)
    outer = model.DatasetCollection(collection_type="list:paired")
    model.DatasetCollectionElement(collection=outer, element=inner, element_identifier="sam'ple", element_index=0)
    wrapper = DatasetCollectionWrapper(
        None, model.HistoryDatasetCollectionAssociation(name="pairs", collection=outer), app.datatypes_registry
    )
    assert list(_identifiers(wrapper)) == ["pairs", "sam'ple", "forward", "rev'erse"]

    datasets = [model.HistoryDatasetAssociation(name=name, extension="txt") for name in ("one", "two")]
    assert list(_identifiers(DatasetListWrapper(None, datasets, datatypes_registry=app.datatypes_registry))) == [
        "one",
        "two",
    ]


def test_check_errors_do_not_fail_the_job(app, tmp_path, monkeypatch, caplog):
    def broken(findings, param_dict):
        raise RuntimeError("unexpected param_dict")

    monkeypatch.setattr(security_review, "find_violations", broken)
    tool = make_tool(app, tmp_path)
    reviewer(tmp_path, ENFORCE).check_job(tool, evaluator(app, tool, ["it's"]))
    assert "checking values against the security review of tool echo_ids failed" in caplog.text


def test_finding_refs_name_the_inputs(app, tmp_path):
    review = reviewer(tmp_path).review(make_tool(app, tmp_path))
    assert review is not None
    refs = {(ref.accessor, ref.param) for f in review.checked_findings for ref in f.refs}
    assert refs == {(ELEMENT_IDENTIFIER, "input"), (RAW, "word")}


def refused(app, tmp_path, tool: Tool, identifiers: list[str], word: str = "plain") -> bool:
    try:
        reviewer(tmp_path, ENFORCE).check_job(tool, evaluator(app, tool, identifiers, word=word))
    except ToolInputRejected:
        return True
    return False


ECHO_DOUBLE = ECHO_IDS.replace("'$e.element_identifier'", '"$e.element_identifier"').replace(
    "'${word.value}'", '"${word.value}"'
)


@pytest.mark.parametrize(
    "identifiers,word,expected",
    [
        # "sample "A"" is one word: closing the quotes starts nothing without a command character.
        (['sample "A"'], "plain", False),
        # A quote counts as stray even when the value closes and reopens it.
        (['sample "A"'], "a;b", True),
        (['a"; id; "'], "plain", True),
        (["$(id)"], "plain", True),
        (["`id`"], "plain", True),
        # The first identifier ends in a backslash, which escapes its closing quote.
        (["a\\", "b"], ";id;#", True),
    ],
)
def test_double_quote_needs_a_command_character(app, tmp_path, identifiers, word, expected):
    tool = make_tool(app, tmp_path, ECHO_DOUBLE, "double.xml")
    assert refused(app, tmp_path, tool, identifiers, word) is expected


DATA_FILE = """<tool id="data_file" name="Data file" version="1.0" profile="24.0">
  <command>tool --conf '$conf' --title '${word.value}' > '$out'</command>
  <configfiles><configfile name="conf">title = "${word.value}"
#for $e in $input
sample = $e.element_identifier
#end for
</configfile></configfiles>
  <inputs>
    <param name="input" type="data_collection" collection_type="list" format="txt"/>
    <param name="word" type="text"/>
  </inputs>
  <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


def test_stray_quote_in_a_data_file_frees_nothing(app, tmp_path):
    tool = make_tool(app, tmp_path, DATA_FILE, "data_file.xml")
    assert not refused(app, tmp_path, tool, ["R&D;x|y"], word='say "hi"')


SHELL_SCRIPT = """<tool id="shell_script" name="Shell script" version="1.0" profile="24.0">
  <command>sh '$script'</command>
  <configfiles><configfile name="script">#!/bin/sh
#for $e in $input
echo '$e.element_identifier' >> '$out'
#end for
</configfile></configfiles>
  <inputs>
    <param name="input" type="data_collection" collection_type="list" format="txt"/>
    <param name="word" type="text"/>
  </inputs>
  <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


@pytest.mark.parametrize(
    "identifiers,expected",
    [
        (["R&D;x|y"], False),
        (["a';id;'"], True),
    ],
)
def test_shell_script_configfile_is_quoted_like_the_command(app, tmp_path, identifiers, expected):
    tool = make_tool(app, tmp_path, SHELL_SCRIPT, "shell_script.xml")
    assert refused(app, tmp_path, tool, identifiers) is expected


TWO_VALUES = """<tool id="two_values" name="Two values" version="1.0" profile="24.0">
  <command><![CDATA[{command}]]></command>
  <inputs>
    <param name="q" type="text">{q}</param>
    <param name="x" type="text"><sanitizer><valid initial="string.ascii_letters"><add value=";"/></valid></sanitizer></param>
  </inputs>
  <outputs><data name="out" format="txt"/></outputs>
</tool>
"""
UNSANITIZED = '<sanitizer sanitize="false"/>'
LETTERS_AND_QUOTE = '<sanitizer><valid initial="string.ascii_letters"><add value="&apos;"/></valid></sanitizer>'


def two_values_refused(app, tmp_path, command: str, q_sanitizer: str, q: str, x: str) -> bool:
    tool = make_tool(app, tmp_path, TWO_VALUES.format(command=command, q=q_sanitizer), "two_values.xml")
    job: Any = SimpleNamespace(job=SimpleNamespace(id=7), consumes_names=False, consumes_identifiers=False)
    job.param_dict = {
        name: InputValueWrapper(cast(ToolParameter, tool.inputs[name]), value) for name, value in (("q", q), ("x", x))
    }
    try:
        reviewer(tmp_path, ENFORCE).check_job(tool, job)
    except ToolInputRejected:
        return True
    return False


@pytest.mark.parametrize(
    "q,expected",
    [
        # `echo "a\" && echo ";id;#"`: the backslash escapes the closing quote and frees x.
        ("a\\", True),
        # Only a backslash at the end escapes the closing quote.
        ("C:\\data\\reads.fq", False),
        ("a\\\\", False),
    ],
)
def test_backslash_frees_the_next_value_only_at_the_end(app, tmp_path, q, expected):
    command = """echo "$q" && echo "$x" > '$out'"""
    assert two_values_refused(app, tmp_path, command, UNSANITIZED, q, ";id;#") is expected


@pytest.mark.parametrize(
    "q,expected",
    [
        # `echo " && echo ";id;"`: outside quotes, the quote of q opens a string that x closes.
        ('"', True),
        ("a", False),
    ],
)
def test_quote_outside_quotes_frees_the_next_value(app, tmp_path, q, expected):
    command = """echo $q && echo "$x" > '$out'"""
    assert two_values_refused(app, tmp_path, command, UNSANITIZED, q, ";id;") is expected


def test_tool_with_only_medium_findings_is_checked(app, tmp_path):
    # Two stray quotes in `echo ''' && echo ";id;" && echo '''` leave the `;` of x unquoted.
    command = """echo '$q' && echo "$x" && echo '$q' > '$out'"""
    assert two_values_refused(app, tmp_path, command, LETTERS_AND_QUOTE, "'", ";id;")
    assert not two_values_refused(app, tmp_path, command, LETTERS_AND_QUOTE, "Bob", ";id;")


SED_RENAME = ECHO_IDS.replace(
    "echo '$e.element_identifier' >> '$out';",
    "sed \"s/'$e.element_identifier'/$e.element_identifier/\" '$e' >> '$out';",
)


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("ID=gene1;Name=abc", False),
        ("5' UTR", False),
        ("C:\\data\\reads.fq", False),
        # The delimiter ends the replacement: `s/x/a/e;...` runs a command in GNU sed.
        ("a/e;#", True),
    ],
)
def test_value_in_a_sed_replacement(app, tmp_path, identifier, expected):
    tool = make_tool(app, tmp_path, SED_RENAME, "sed.xml")
    assert refused(app, tmp_path, tool, [identifier]) is expected


def test_template_that_pipes_into_a_shell_is_reported_as_not_checked(app, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger=security_review.__name__)
    piping = ECHO_IDS.replace("echo '${word.value}' >> '$out'", "echo '${word.value}' | sh >> '$out'")
    tool = make_tool(app, tmp_path, piping, "piping.xml")
    review = reviewer(tmp_path, ENFORCE).review(tool)
    assert review is not None and review.unchecked_locations == {"command": "it sends text to a shell to run"}
    assert not review.checked_findings
    assert "values written in command are not checked, it sends text to a shell to run" in caplog.text
