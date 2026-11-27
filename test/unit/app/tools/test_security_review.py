import contextlib
import gc
import logging
import os
import threading
import time
from decimal import Decimal
from types import SimpleNamespace
from typing import (
    Any,
    cast,
)

import pytest

from galaxy import model
from galaxy.app_unittest_utils.galaxy_mock import MockApp
from galaxy.app_unittest_utils.security_review_spec import SpecJobRunner
from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.security import (
    review_tool_source,
)
from galaxy.tool_util.security.model import (
    REPLACEABLE_SPECIALS,
    SAFE_SPECIALS,
)
from galaxy.tool_util.security.report import (
    ELEMENT_IDENTIFIER,
    RAW,
)
from galaxy.tool_util.security.spec import JobCase
from galaxy.tools import (
    create_tool_from_source,
    security_review,
    Tool,
)
from galaxy.tools.evaluation import ToolEvaluator
from galaxy.tools.parameters.basic import (
    SelectToolParameter,
    ToolParameter,
)
from galaxy.tools.security_review import (
    _identifiers,
    ANALYSED,
    ENFORCE_CODE,
    LOG,
    NOT_ANALYSED,
    OFF,
    reviewed_tool_source,
    STRICT,
    ToolInputRejected,
    ToolSecurityReviewer,
)
from galaxy.tools.wrappers import (
    DatasetCollectionWrapper,
    DatasetFilenameWrapper,
    DatasetListWrapper,
    InputValueWrapper,
    RawObjectWrapper,
    SelectToolParameterWrapper,
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


def broken(*args, **kwds):
    raise RuntimeError("analyser bug")


def reviewer(tmp_path, mode: str = LOG, when_unsure: str = STRICT) -> ToolSecurityReviewer:
    return ToolSecurityReviewer(mode, when_unsure=when_unsure)


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


MAYBE_UNSET = """<tool id="maybe_unset" name="Maybe unset" version="1.0" profile="24.0">
  <command><![CDATA[
#if $word == 'x'
#set $NAME = 'safe'
#end if
echo '$NAME' > '$out'
  ]]></command>
  <inputs ATTRS><param name="word" type="text"/></inputs>
  <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


@pytest.mark.parametrize(
    "name,attrs,read",
    [
        # A job parameter that is not an input does not reach the templates of a regular tool.
        ("undeclared", "", False),
        # A data source tool keeps all its job parameters.
        ("undeclared", ' check_values="false"', True),
        ("__target_datatype__", "", True),
    ],
)
def test_unset_local_reads_the_job_parameters_the_tool_passes_to_its_templates(app, tmp_path, name, attrs, read):
    tool = make_tool(app, tmp_path, MAYBE_UNSET.replace("NAME", name).replace("ATTRS", attrs))
    review = reviewer(tmp_path).review(tool)
    assert review is not None and review.report is not None
    assert any(ref.key == name for f in review.report.findings for ref in f.refs) is read


def test_job_parameters_replace_exactly_the_galaxy_names_the_review_reads_as_job_parameters(tmp_path):
    # REPLACEABLE_SPECIALS follows the order in which build_param_dict sets Galaxy's names and the job's
    # parameters: a job parameter replaces a name in a tool that keeps all its job parameters only if
    # Galaxy sets the name before the job's parameters, or never. chromInfo is the tool action's.
    names = sorted(SAFE_SPECIALS - {"chromInfo", "__get_data_table_entry__"})
    lines = "\n".join(f"echo {n}=${{getVar('{n}', 'ABSENT')}};" for n in names)
    for check_values, expected in (("", set()), (' check_values="false"', REPLACEABLE_SPECIALS)):
        path = os.path.join(tmp_path, f"tool{len(check_values)}.xml")
        with open(path, "w") as fh:
            fh.write(f"""<tool id="t{len(check_values)}" name="t" version="1.0" profile="24.0">
<command><![CDATA[{lines}
true]]></command>
<inputs{check_values}><param name="word" type="text" value="a"/></inputs>
<outputs><data name="out" format="txt"/></outputs>
</tool>""")
        runner = SpecJobRunner(path, str(tmp_path))
        job = JobCase(inputs={"word": "w", **{n: f"MARK{i}" for i, n in enumerate(names)}}, expect={"rejected": False})
        command = runner.run(job, mode=OFF).command_line
        assert command is not None
        assert {n for i, n in enumerate(names) if f"{n}=MARK{i};" in command} == expected


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


def test_analyser_error_is_recorded_as_not_analysed(app, tmp_path, monkeypatch):
    monkeypatch.setattr(security_review, "review_tool_source", broken)
    tool = make_tool(app, tmp_path)
    r = reviewer(tmp_path, ENFORCE_CODE, when_unsure=LOG)
    review = r.review(tool)
    assert review is not None and review.status == NOT_ANALYSED and review.reason == "error: RuntimeError"
    # Kept, so the next job does not review again.
    assert r.review(tool) is review
    r.check_job(tool, evaluator(app, tool, ["a'b"]))


def test_tool_source_error_is_recorded_once(app, tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(security_review, "reviewed_tool_source", broken)
    tool = make_tool(app, tmp_path)
    r = reviewer(tmp_path)
    review = r.review(tool)
    assert review is not None and review.status == NOT_ANALYSED
    assert r.review(tool) is review
    assert caplog.text.count("Cannot review tool echo_ids for security") == 1


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
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)
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


@pytest.mark.parametrize("mode", [LOG, ENFORCE_CODE])
def test_harmless_values_pass(app, tmp_path, caplog, mode):
    tool = make_tool(app, tmp_path)
    # A command character stays inside the quotes.
    reviewer(tmp_path, mode).check_job(tool, evaluator(app, tool, ["sample 1", "a;b|c"], word="a b;c"))
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize("mode", [LOG, ENFORCE_CODE])
def test_lone_quote_passes_when_it_is_the_only_user_value(app, tmp_path, caplog, mode):
    tool = make_tool(app, tmp_path, ECHO_ONE, "one.xml")
    reviewer(tmp_path, mode).check_job(tool, evaluator(app, tool, ["sample 1", "Bob's reads"], name="Bob's list"))
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_lone_quote_counts_when_another_value_brings_a_command(app, tmp_path):
    # `echo 'Bob's' ...; echo 'a;b'`: the stray quote leaves the `;` of the next value unquoted.
    tool = make_tool(app, tmp_path)
    with pytest.raises(ToolInputRejected) as e:
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, evaluator(app, tool, ["Bob's reads"], word="a;b"))
    assert "the value of input 'word' contains the characters [;]" in str(e.value)
    assert "an element identifier or the name of input 'input' contains the characters [']" in str(e.value)


@pytest.mark.parametrize("mode", [LOG, ENFORCE_CODE])
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
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)
    job.param_dict["q"] = InputValueWrapper(cast(ToolParameter, tool.inputs["q"]), "plain")
    reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)


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
            reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)
    else:
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)


def test_collection_name_is_checked(app, tmp_path):
    # `$c.name` gives the collection's name, and the review does not tell it from element identifiers.
    tool = make_tool(app, tmp_path)
    with pytest.raises(ToolInputRejected):
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, evaluator(app, tool, ["a"], name="Bob's;list"))


def test_characters_of_all_values_count_together(app, tmp_path):
    # A template may join the identifiers into one string, where one brings the quote and another the `;`.
    tool = make_tool(app, tmp_path, ECHO_ONE, "one.xml")
    with pytest.raises(ToolInputRejected):
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, evaluator(app, tool, ["Bob's", "a;b"]))


def test_raw_value_is_checked(app, tmp_path):
    tool = make_tool(app, tmp_path)
    with pytest.raises(ToolInputRejected) as e:
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, evaluator(app, tool, ["a"], word="it';id"))
    assert "the value of input 'word' contains the characters [' ;]" in str(e.value)


def test_rewritten_value_is_reported_as_not_checkable(app, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger=security_review.__name__)
    rewriting = ECHO_IDS.replace("echo '${word.value}'", "echo ${str($word).replace('__gt__', '>')}")
    tool = make_tool(app, tmp_path, rewriting, "rewriting.xml")
    review = reviewer(tmp_path, ENFORCE_CODE).review(tool)
    # The rewritten value can bring the quote that lets the identifiers out: nothing is checkable.
    assert review is not None and len(review.unchecked_findings) == 2 and not review.checked_findings
    assert "(2 cannot be checked against job values)" in caplog.text
    reviewer(tmp_path, ENFORCE_CODE, when_unsure=LOG).check_job(tool, evaluator(app, tool, ["a"], word="a__gt__/tmp/x"))


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


def test_check_errors_do_not_fail_the_job_unless_strict(app, tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(security_review, "find_violations", broken)
    tool = make_tool(app, tmp_path)
    reviewer(tmp_path, ENFORCE_CODE, when_unsure=LOG).check_job(tool, evaluator(app, tool, ["it's"]))
    assert "checking values against the security review of tool echo_ids failed" in caplog.text


def test_finding_refs_name_the_inputs(app, tmp_path):
    review = reviewer(tmp_path).review(make_tool(app, tmp_path))
    assert review is not None
    refs = {(ref.accessor, ref.param) for f in review.checked_findings for ref in f.refs}
    assert refs == {(ELEMENT_IDENTIFIER, "input"), (RAW, "word")}


def refused(app, tmp_path, tool: Tool, identifiers: list[str], word: str = "plain") -> bool:
    try:
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, evaluator(app, tool, identifiers, word=word))
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
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)
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
    review = reviewer(tmp_path, ENFORCE_CODE).review(tool)
    assert review is not None and review.unchecked_locations == {"command": "it sends text to a shell to run"}
    assert not review.checked_findings
    assert "values written in command are not checked, it sends text to a shell to run" in caplog.text


SCRIPT_LINE = """<tool id="script_line" name="Script line" version="1.0" profile="24.0">
  <command><![CDATA[bash '$script' > '$out']]></command>
  <configfiles><configfile name="script"><![CDATA[{script}]]></configfile></configfiles>
  <inputs><param name="q" type="text"><sanitizer sanitize="false"/></param></inputs>
  <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


@pytest.mark.parametrize(
    "script,q,expected",
    [
        ("echo $q", "x\nid", True),
        ("echo $q", "x id", False),
        # The template makes a newline of the carriage return.
        ("#set $v = str($q).replace('\\r', '\\n')\necho $v", "x\rid", True),
    ],
)
def test_newline_in_a_shell_script_starts_a_command(app, tmp_path, script, q, expected):
    tool = make_tool(app, tmp_path, SCRIPT_LINE.format(script=script), "script_line.xml")
    job: Any = SimpleNamespace(job=SimpleNamespace(id=7), consumes_names=False, consumes_identifiers=False)
    job.param_dict = {"q": InputValueWrapper(cast(ToolParameter, tool.inputs["q"]), q)}
    with pytest.raises(ToolInputRejected) if expected else contextlib.nullcontext():
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)


OPEN_FILE = """<tool id="open_file" name="Open file" version="1.0" profile="24.0">
  <command><![CDATA[#set $n = open(str($n_file)).read().strip()
tool --n $n > '$out']]></command>
  <inputs><param name="n_file" type="data" format="txt"/></inputs>
  <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


@pytest.mark.parametrize("content,expected", [("15\n", False), ("15; id\n", True)])
def test_content_of_a_dataset_the_template_opens_is_checked(app, tmp_path, content, expected):
    path = tmp_path / "n.txt"
    path.write_text(content)
    tool = make_tool(app, tmp_path, OPEN_FILE, "open_file.xml")
    hda = model.HistoryDatasetAssociation(extension="txt", dataset=model.Dataset(external_filename=str(path)))
    job: Any = SimpleNamespace(job=SimpleNamespace(id=7), consumes_names=False, consumes_identifiers=False)
    job.param_dict = {"n_file": DatasetFilenameWrapper(hda, datatypes_registry=app.datatypes_registry)}
    with pytest.raises(ToolInputRejected) if expected else contextlib.nullcontext():
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)


def test_content_of_a_dataset_over_the_limit_counts_as_every_character_unread(app, tmp_path, monkeypatch):
    def not_read(*args, **kwds):
        raise AssertionError("read a dataset over the limit")

    path = tmp_path / "n.txt"
    path.write_text("15\n")
    monkeypatch.setattr(security_review, "CONTENT_LIMIT", 2)
    monkeypatch.setattr(security_review, "open", not_read, raising=False)
    tool = make_tool(app, tmp_path, OPEN_FILE, "open_file.xml")
    dataset = model.Dataset(external_filename=str(path))
    dataset.file_size = Decimal(3)
    hda = model.HistoryDatasetAssociation(extension="txt", dataset=dataset)
    job: Any = SimpleNamespace(job=SimpleNamespace(id=7), consumes_names=False, consumes_identifiers=False)
    job.param_dict = {"n_file": DatasetFilenameWrapper(hda, datatypes_registry=app.datatypes_registry)}
    with pytest.raises(ToolInputRejected):
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)


@pytest.mark.parametrize("content,expected", [("15\n", False), ("15; id\n", True)])
def test_content_is_read_from_the_galaxy_side_file_when_the_job_runs_elsewhere(app, tmp_path, content, expected):
    # Where the job runs, the template opens the dataset under its path on that host.
    path = tmp_path / "n.txt"
    path.write_text(content)
    tool = make_tool(app, tmp_path, OPEN_FILE, "open_file.xml")
    hda = model.HistoryDatasetAssociation(extension="txt", dataset=model.Dataset(external_filename=str(path)))
    remote = SimpleNamespace(input_path_rewrite=lambda dataset: "/remote/staging/inputs/n.txt")
    job: Any = SimpleNamespace(job=SimpleNamespace(id=7), consumes_names=False, consumes_identifiers=False)
    job.param_dict = {
        "n_file": DatasetFilenameWrapper(
            hda, datatypes_registry=app.datatypes_registry, compute_environment=cast(Any, remote)
        )
    }
    with pytest.raises(ToolInputRejected) if expected else contextlib.nullcontext():
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)


# A backslash at the end of the content escapes the closing quote and frees the `;` in it.
OPEN_FILE_QUOTED = OPEN_FILE.replace("tool --n $n > '$out'", "echo \"$n\" '$out' > '$out'")


@pytest.mark.parametrize("content,expected", [("a\\;b\n", False), ("a;b\\", True)])
def test_backslash_counts_only_at_the_end_of_a_large_dataset(app, tmp_path, content, expected):
    path = tmp_path / "n.txt"
    # Longer than the check reads at once, with the backslash at the end of the first read.
    path.write_text("a" * (1024 * 1024 - 2) + content)
    tool = make_tool(app, tmp_path, OPEN_FILE_QUOTED, "open_file_quoted.xml")
    hda = model.HistoryDatasetAssociation(extension="txt", dataset=model.Dataset(external_filename=str(path)))
    job: Any = SimpleNamespace(job=SimpleNamespace(id=7), consumes_names=False, consumes_identifiers=False)
    job.param_dict = {"n_file": DatasetFilenameWrapper(hda, datatypes_registry=app.datatypes_registry)}
    with pytest.raises(ToolInputRejected) if expected else contextlib.nullcontext():
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)


def test_content_that_cannot_be_read_counts_as_every_character(app, tmp_path):
    tool = make_tool(app, tmp_path, OPEN_FILE, "open_file.xml")
    missing = model.HistoryDatasetAssociation(
        extension="txt", dataset=model.Dataset(external_filename=str(tmp_path / "missing.txt"))
    )
    job: Any = SimpleNamespace(job=SimpleNamespace(id=7), consumes_names=False, consumes_identifiers=False)
    job.param_dict = {"n_file": DatasetFilenameWrapper(missing, datatypes_registry=app.datatypes_registry)}
    with pytest.raises(ToolInputRejected):
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)


USER_PREFERENCE = """<tool id="user_preference" name="User preference" version="1.0" profile="24.0">
  <command><![CDATA[echo "${__user__.extra_preferences.get('account|name', '')}" > '$out']]></command>
  <inputs/>
  <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


@pytest.mark.parametrize("name,expected", [("me@example.org", False), ("$(id)", True)])
def test_user_preference_is_checked(app, tmp_path, name, expected):
    tool = make_tool(app, tmp_path, USER_PREFERENCE, "user_preference.xml")
    job: Any = SimpleNamespace(job=SimpleNamespace(id=7), consumes_names=False, consumes_identifiers=False)
    job.param_dict = {"__user__": RawObjectWrapper(SimpleNamespace(extra_preferences={"account|name": name}))}
    with pytest.raises(ToolInputRejected) if expected else contextlib.nullcontext():
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)


# -- strict when unsure ------------------------------------------------------------------------

REWRITING = ECHO_IDS.replace("echo '${word.value}'", "echo ${str($word).replace('__gt__', '>')}")
# Galaxy joins the lines of a command: the `;` keeps a command added after it from being the script of sh.
PIPING = ECHO_IDS.replace("echo '${word.value}' >> '$out'", "echo '${word.value}' | sh >> '$out';")
PERL = ECHO_IDS.replace("echo '${word.value}' >> '$out'", "perl -e 'print ${word.value};' >> '$out'")
SAFE_REPLACE = ECHO_IDS.replace("echo '${word.value}'", "echo '${str($word.value).replace(' ', '_')}'")


def unsure(contents: str = ECHO_IDS) -> str:
    """The tool with a part the analysis does not follow: the review is unsure of what it writes."""
    return contents.replace("]]></command>", "\necho '$searchList' >> '$out'\n]]></command>", 1)


def strict_refusal(r: ToolSecurityReviewer, tool: Tool, job: Any) -> str:
    with pytest.raises(ToolInputRejected) as e:
        r.check_job(tool, job)
    return str(e.value)


def test_strict_when_unsure_runs_plain_values_only(app, tmp_path):
    tool = make_tool(app, tmp_path, unsure(), "unsure.xml")
    r = reviewer(tmp_path, ENFORCE_CODE)
    r.check_job(tool, evaluator(app, tool, ["sample_1.fastq", "FastQC on data 1: RawData"], word="My title"))
    message = strict_refusal(r, tool, evaluator(app, tool, ["sample (1)"]))
    assert message.startswith(
        "[not-plain-unchecked-place] This job was not run: an element identifier or the name of input 'input'"
        " contains [( )]"
    )
    assert "because this tool writes values in places that no check of their characters can judge (command)" in message
    assert "Echo identifiers" in message and "echo_ids" in message
    # With strict_when_unsure off the same job runs.
    reviewer(tmp_path, ENFORCE_CODE, when_unsure=LOG).check_job(tool, evaluator(app, tool, ["sample (1)"]))


@pytest.mark.parametrize(
    "identifier,harm",
    [
        ("a;b", ";"),
        ("x__gt__y", ">"),
        ("a -rf", "-"),
        ("-x", "-"),
        ("a\tb", "tab"),
        ("50%", "%"),
    ],
)
def test_strict_check_refuses_what_can_leave_any_place(app, tmp_path, identifier, harm):
    tool = make_tool(app, tmp_path, unsure(), "unsure.xml")
    assert f"contains [{harm}]" in strict_refusal(
        reviewer(tmp_path, ENFORCE_CODE), tool, evaluator(app, tool, [identifier])
    )


def test_strict_check_reads_dataset_names(app, tmp_path):
    tool = make_tool(app, tmp_path, unsure(), "unsure.xml")
    job = evaluator(app, tool, ["a"])
    next(iter(job.param_dict["input"])).unsanitized.name = "Trimmomatic on data 1 (R1 paired)"
    assert "the name of a dataset of input 'input' contains" in strict_refusal(
        reviewer(tmp_path, ENFORCE_CODE), tool, job
    )


READS_MORE = ECHO_IDS.replace(
    "echo '${word.value}'",
    "echo '${word.value}' '${__user__.extra_preferences.get('account|name')}' '${e.info}' '${e.metadata.comment_lines}'",
)


def test_strict_check_reads_what_the_template_names(app, tmp_path):
    def job_with(info: str, preference: str) -> Any:
        job = evaluator(app, tool, ["a"])
        next(iter(job.param_dict["input"])).unsanitized.info = info
        job.param_dict["__user__"] = RawObjectWrapper(SimpleNamespace(extra_preferences={"account|name": preference}))
        return job

    r = reviewer(tmp_path, ENFORCE_CODE)
    # A template that names neither: a tool's output summary and a password do not count.
    tool = make_tool(app, tmp_path, unsure(), "unsure.xml")
    r.check_job(tool, job_with('aligned "95.3%"', "a&b"))
    tool = make_tool(app, tmp_path, unsure(READS_MORE), "reads_more.xml")
    message = strict_refusal(r, tool, job_with('aligned "95.3%"', "a&b"))
    # The template writes the info as Galaxy sanitizes it, and the check reads it the same way.
    assert "the info of a dataset of input 'input' contains [\"]" in message
    assert "your preference 'account|name' contains [&]" in message


USER_EMAIL = ECHO_IDS.replace("echo '${word.value}'", "echo $__user_email__")


def test_strict_check_reads_the_email_a_template_names(app, tmp_path):
    def job_with(email: str) -> Any:
        job = evaluator(app, tool, ["a"])
        job.param_dict["__user_email__"] = email
        return job

    r = reviewer(tmp_path, ENFORCE_CODE)
    tool = make_tool(app, tmp_path, unsure(), "unsure.xml")
    r.check_job(tool, job_with("a`b`@example.org"))
    tool = make_tool(app, tmp_path, unsure(USER_EMAIL), "user_email.xml")
    r.check_job(tool, job_with("me@example.org"))
    assert "your email address contains [`]" in strict_refusal(r, tool, job_with("a`b`@example.org"))


PIPING_SELECT = unsure(
    ECHO_IDS.replace("echo '${word.value}'", "echo '${word.value}' $mode").replace(
        '<param name="word" type="text"/>',
        """<param name="word" type="text"/>
    <param name="mode" type="select">
      <option value="--fast">fast</option>
      <option value="--very-sensitive">sensitive</option>
    </param>""",
    )
)


def test_strict_check_leaves_select_options_the_tool_defines_alone(app, tmp_path):
    tool = make_tool(app, tmp_path, PIPING_SELECT, "unsure_select.xml")
    job = evaluator(app, tool, ["a"], word="b")
    job.param_dict["mode"] = SelectToolParameterWrapper(cast(SelectToolParameter, tool.inputs["mode"]), "--fast")
    reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)


@pytest.mark.parametrize("patched", ["review_tool_source", "reviewed_tool_source"])
def test_strict_when_unsure_refuses_every_job_of_a_tool_it_could_not_review(app, tmp_path, monkeypatch, patched):
    monkeypatch.setattr(security_review, patched, broken)
    tool = make_tool(app, tmp_path)
    message = strict_refusal(reviewer(tmp_path, ENFORCE_CODE), tool, evaluator(app, tool, ["a"], word="b"))
    assert "the security review of this tool failed, and nothing is known about what its templates do" in message


@pytest.mark.parametrize(
    "contents,why,code",
    [
        (REWRITING, "its templates change values with .replace", "uncheckable-rewrites"),
        (OPEN_FILE, "its templates run code or read data the job does not carry (open)", "uncheckable-template-code"),
        (PIPING, "letters alone can be code where it writes values (command)", "uncheckable-letters-are-code"),
        (PERL, "letters alone can be code where it writes values (command)", "uncheckable-letters-are-code"),
    ],
)
def test_strict_when_unsure_refuses_every_job_when_no_value_can_be_plain(app, tmp_path, contents, why, code):
    tool = make_tool(app, tmp_path, unsure(contents), "unchecked.xml")
    if contents is OPEN_FILE:
        job: Any = SimpleNamespace(job=SimpleNamespace(id=7), consumes_names=False, consumes_identifiers=False)
        job.param_dict = {}
    else:
        job = evaluator(app, tool, ["a"], word="b")
    message = strict_refusal(reviewer(tmp_path, ENFORCE_CODE), tool, job)
    assert why in message
    assert message.startswith(f"[{code}] This job was not run: this Galaxy server cannot check any value for tool")


def test_rewrites_in_several_templates_are_named_once(app, tmp_path):
    rewrite = "#set $v = chr(36) + str($word.value)\necho $v"
    contents = ECHO_IDS.replace("echo '${word.value}'", rewrite).replace(
        "  <inputs>",
        f"""  <configfiles><configfile name="script"><![CDATA[{rewrite}]]></configfile></configfiles>
  <inputs>""",
    )
    tool = make_tool(app, tmp_path, unsure(contents), "two_rewrites.xml")
    message = strict_refusal(reviewer(tmp_path, ENFORCE_CODE), tool, evaluator(app, tool, ["a"], word="b"))
    assert message.count("its templates change values with chr") == 1


@pytest.mark.parametrize("new", ["'$'", "'$a'", '"x$"'])
def test_replace_that_brings_a_dollar_is_a_rewrite(app, tmp_path, new):
    contents = ECHO_IDS.replace("echo '${word.value}'", f"#set $v = str($word.value).replace('x', {new})\necho $v")
    review = reviewer(tmp_path).review(make_tool(app, tmp_path, contents, "dollar.xml"))
    assert review is not None and review.report is not None
    assert review.report.rewrites == {"command": [".replace"]}


@pytest.mark.parametrize(
    "rewrite,name",
    [
        ("#import re\n#set $v = $re.sub('x', ';', str($word.value))", "re.sub"),
        ("#set $v = str.replace(str($word.value), 'x', ';')", ".replace"),
        ("#set $v = chr(36) + str($word.value)", "chr"),
        ("#set $v = str($word.value).encode('rot13').decode('rot13')", "decode"),
    ],
)
def test_other_rewrites(app, tmp_path, rewrite, name):
    contents = ECHO_IDS.replace("echo '${word.value}'", f"{rewrite}\necho $v")
    review = reviewer(tmp_path).review(make_tool(app, tmp_path, contents, "rewrite.xml"))
    assert review is not None and review.report is not None
    assert name in review.report.rewrites["command"]


@pytest.mark.parametrize(
    "contents",
    [SAFE_REPLACE, ECHO_IDS.replace("echo '${word.value}'", "base64 --decode '${word.value}'; date +%c")],
)
def test_plain_replacements_and_shell_text_are_no_rewrites(app, tmp_path, contents):
    review = reviewer(tmp_path).review(make_tool(app, tmp_path, contents, "plain.xml"))
    assert review is not None and review.report is not None and review.report.rewrites == {}


def test_strict_when_unsure_checks_strictly_when_the_check_fails(app, tmp_path, monkeypatch):
    monkeypatch.setattr(security_review, "find_violations", broken)
    tool = make_tool(app, tmp_path)
    r = reviewer(tmp_path, ENFORCE_CODE)
    r.check_job(tool, evaluator(app, tool, ["a"]))
    message = strict_refusal(r, tool, evaluator(app, tool, ["it's"]))
    assert "checking the job's values against the security review failed" in message


def test_strict_when_unsure_lets_checked_values_run(app, tmp_path):
    tool = make_tool(app, tmp_path)
    reviewer(tmp_path, ENFORCE_CODE).check_job(tool, evaluator(app, tool, ["5' UTR"], word="x"))


REWRITING_SCRIPT = ECHO_IDS.replace("echo '${word.value}' >> '$out'", "bash '$script' >> '$out'").replace(
    "  <inputs>",
    """  <configfiles><configfile name="script"><![CDATA[echo ${str($word).replace('__gt__', '>')}]]></configfile></configfiles>
  <inputs>""",
)


def test_strict_when_unsure_names_the_harmful_value_first(app, tmp_path):
    tool = make_tool(app, tmp_path, REWRITING_SCRIPT, "unchecked.xml")
    review = reviewer(tmp_path).review(tool)
    assert review is not None and review.checked_findings and review.unchecked_findings
    message = strict_refusal(reviewer(tmp_path, ENFORCE_CODE), tool, evaluator(app, tool, ["it';id;'s"]))
    assert "contains the characters" in message


def test_strict_when_unsure_in_log_mode_warns_and_lets_the_job_run(app, tmp_path, caplog):
    tool = make_tool(app, tmp_path, unsure(), "unsure.xml")
    reviewer(tmp_path, LOG).check_job(tool, evaluator(app, tool, ["a"], word="a|b"))
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    prefix = (
        "Tool security review (not-plain-unchecked-place): job 7 of tool echo_ids version 1.0 cannot be checked,"
        " this tool writes values in places that no check of their characters can judge (command), and"
    )
    # Log mode warns of what enforce_all refuses, whose plain values have no spaces.
    assert warnings == [
        f"{prefix} an element identifier or the name of input 'input' contains [space]",
        f"{prefix} the value of input 'word' contains [|]",
        f"{prefix} the name of a dataset of input 'input' contains [space]",
    ]


def test_strict_check_errors_fail_the_job_only_in_enforce_mode(app, tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(security_review, "strict_violations", broken)
    tool = make_tool(app, tmp_path, unsure(), "unsure.xml")
    reviewer(tmp_path, LOG).check_job(tool, evaluator(app, tool, ["a"]))
    assert "the strict check of the values of job 7 of tool echo_ids failed" in caplog.text
    message = strict_refusal(reviewer(tmp_path, ENFORCE_CODE), tool, evaluator(app, tool, ["a"]))
    assert "checking its values strictly failed" in message


def test_strict_when_unsure_leaves_tools_without_a_template_alone(app, tmp_path):
    tool = make_tool(app, tmp_path, NO_COMMAND)
    job: Any = SimpleNamespace(job=SimpleNamespace(id=7))
    reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)


# -- literal rewrites ------------------------------------------------------------------------


def ids_tool(command: str) -> str:
    """A tool with the collection `input` and the text param `word` of :func:`evaluator`."""
    return f"""<tool id="rewrites" name="Rewrites" version="1.0" profile="24.0">
  <command><![CDATA[{command}]]></command>
  <inputs>
    <param name="input" type="data_collection" collection_type="list" format="txt"/>
    <param name="word" type="text"/>
  </inputs>
  <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


OPTION_WORDS = "a --checkpoint=1 --checkpoint-action=exec=id"

DEEP_REWRITE = "\n".join(
    ["#def f0($v)\n${v.replace('_', ';')}\n#end def"]
    + [f"#def f{i}($v)\n$f{i - 1}($v)\n#end def" for i in range(1, 10)]
    + ["echo $f9(str($word.value)) >> '$out'"]
)


@pytest.mark.parametrize(
    "command,identifiers,word",
    [
        # The text these rewrite is not the value as the job carries it: it always has what they replace.
        (
            '#for $e in $input\necho "${e.name_and_ext.replace(\'.\', \'"\')}" "$e.element_identifier"\n#end for',
            ["x; touch harm #"],
            "plain",
        ),
        (
            '#for $e in $input\necho "${e.get_staging_path().replace(\'.\', \'"\')}" "$e.element_identifier"\n#end for',
            ["x; touch harm #"],
            "plain",
        ),
        (
            '#for $p in $input.get_all_staging_paths()\necho "${p.replace(\'.\', \'"\')}"\n#end for\necho "${word.value}"',
            ["x"],
            "; touch harm #",
        ),
        (
            "echo \"${str($input.element_identifiers_extensions_paths_and_metadata_files).replace('/', '\"')}\""
            ' "${word.value}"',
            ["x"],
            "; touch harm #",
        ),
        # Under re.X a space matches nothing, so the replacement goes in everywhere.
        ("#import re\necho '${re.sub(\" \", \"';id;'\", str($word.value), flags=re.X)}'", ["x"], "x"),
        ("#import re\necho '${re.sub(\" \", \"';id;'\", str($word.value), 0, re.X)}'", ["x"], "x"),
        ("#import re\n#set $p = re.compile(\" \", re.X)\necho '${p.sub(\"';id;'\", str($word.value))}'", ["x"], "x"),
        # repr() quotes the value and format() pads it: the text these rewrite is not the job's value either.
        ("tar -cf '$out' \"${repr($word.value).replace(\"'\", '\"')}\"", ["x"], OPTION_WORDS),
        (
            "#for $e in $input\ntar -cf '$out' \"${repr($e.element_identifier).replace(\"'\", '\"')}\"\n#end for",
            [OPTION_WORDS],
            "plain",
        ),
        ("tar -cf '$out' \"${format($word.value, '.^60').replace('.', '\"')}\"", ["x"], OPTION_WORDS),
    ],
)
def test_rewrite_the_job_check_cannot_judge_refuses_the_job(app, tmp_path, command, identifiers, word):
    tool = make_tool(app, tmp_path, ids_tool(command), "rewrites.xml")
    assert refused(app, tmp_path, tool, identifiers, word=word)


def test_rewrite_the_analysis_does_not_reach_is_a_rewrite(app, tmp_path):
    review = reviewer(tmp_path).review(make_tool(app, tmp_path, ids_tool(DEEP_REWRITE), "deep.xml"))
    assert review is not None and review.report is not None
    assert review.report.rewrites == {"command": [".replace"]}


DATASET_REWRITE = """<tool id="open_rewrite" name="Open and rewrite" version="1.0" profile="24.0">
  <command><![CDATA[echo "${open(str($n_file)).read().replace('\\\\', '"')}" > '$out']]></command>
  <inputs><param name="n_file" type="data" format="txt"/></inputs>
  <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


def test_rewrite_of_dataset_content_refuses_the_job(app, tmp_path):
    path = tmp_path / "n.txt"
    path.write_text("x\\;id;#\n")
    tool = make_tool(app, tmp_path, DATASET_REWRITE, "open_rewrite.xml")
    hda = model.HistoryDatasetAssociation(extension="txt", dataset=model.Dataset(external_filename=str(path)))
    job: Any = SimpleNamespace(job=SimpleNamespace(id=7), consumes_names=False, consumes_identifiers=False)
    job.param_dict = {"n_file": DatasetFilenameWrapper(hda, datatypes_registry=app.datatypes_registry)}
    with pytest.raises(ToolInputRejected):
        reviewer(tmp_path, ENFORCE_CODE).check_job(tool, job)


@pytest.mark.parametrize("word,expected", [("a_id", True), ("a.id", False)])
def test_characters_a_literal_rewrite_adds_count_when_the_value_holds_what_it_replaces(app, tmp_path, word, expected):
    tool = make_tool(app, tmp_path, ids_tool("echo ${str($word.value).replace('_', ';')} > '$out'"), "adds.xml")
    assert refused(app, tmp_path, tool, ["x"], word=word) == expected


@pytest.mark.parametrize("word,expected", [("a'b", True), ("ab", False)])
def test_sanitizer_tokens_hold_what_a_literal_rewrite_replaces(app, tmp_path, word, expected):
    tool = make_tool(app, tmp_path, ids_tool("echo ${str($word).replace('_', ';')} > '$out'"), "tokens.xml")
    assert refused(app, tmp_path, tool, ["x"], word=word) == expected


def test_strict_check_counts_what_a_literal_rewrite_adds(app, tmp_path):
    tool = make_tool(app, tmp_path, unsure(ids_tool("echo '${str($word.value).replace('_', ';')}' > '$out'")), "s.xml")
    r = reviewer(tmp_path, ENFORCE_CODE)
    r.check_job(tool, evaluator(app, tool, ["x"], word="ab"))
    assert "contains [;]" in strict_refusal(r, tool, evaluator(app, tool, ["x"], word="a_b"))


def test_strict_check_counts_spaces_a_rewrite_adds_as_option_words(app, tmp_path):
    command = "tar -cf o.tar ${str($word.value).replace('_', ' ')} > '$out'"
    tool = make_tool(app, tmp_path, unsure(ids_tool(command)), "words.xml")
    job = evaluator(app, tool, ["x"], word="a_--checkpoint=1_--checkpoint-action=exec=id")
    assert "contains [-]" in strict_refusal(reviewer(tmp_path, ENFORCE_CODE), tool, job)
