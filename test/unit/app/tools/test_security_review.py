import json
import logging
import os

import pytest

from galaxy.app_unittest_utils.galaxy_mock import MockApp
from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.security import ReviewTimeout
from galaxy.tool_util.security.report import (
    ELEMENT_IDENTIFIER,
)
from galaxy.tools import (
    create_tool_from_source,
    security_review,
    Tool,
)
from galaxy.tools.security_review import (
    ANALYSED,
    ENFORCE,
    LOG,
    NOT_ANALYSED,
    OFF,
    ReviewCache,
    reviewed_tool_source,
    ToolReview,
    ToolSecurityReviewer,
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
    return ToolSecurityReviewer(mode, os.path.join(tmp_path, "reviews"), timeout)


def stored_files(reviewer: ToolSecurityReviewer) -> list[str]:
    found: list[str] = []
    for dirpath, _, files in os.walk(reviewer.cache.directory):
        found.extend(os.path.join(dirpath, f) for f in files if f != "warm-up.lock")
    return found


# -- the cache ---------------------------------------------------------------------------------


def test_miss_computes_and_stores(app, tmp_path):
    r = reviewer(tmp_path)
    review = r.review(make_tool(app, tmp_path))
    assert review is not None and review.status == ANALYSED
    assert {f.rule for f in review.checked_findings} == {"shell-injection"}
    (path,) = stored_files(r)
    assert json.load(open(path))["tool_id"] == "echo_ids"


def test_hit_reads_the_stored_review(app, tmp_path, monkeypatch):
    tool = make_tool(app, tmp_path)
    first = reviewer(tmp_path).review(tool)

    def fail(*args, **kwds):
        raise AssertionError("reviewed again")

    monkeypatch.setattr(security_review, "review_tool_source", fail)
    # A new process: nothing in memory, the review comes from the directory.
    assert reviewer(tmp_path).review(tool) == first


def test_tool_text_change_is_a_miss(app, tmp_path):
    r = reviewer(tmp_path)
    r.review(make_tool(app, tmp_path))
    changed = make_tool(app, tmp_path, ECHO_IDS.replace("echo '${word.value}'", "echo '${word}'"), "changed.xml")
    review = r.review(changed)
    assert review is not None and review.status == ANALYSED
    assert len(stored_files(r)) == 2
    assert {ref.accessor for f in review.checked_findings for ref in f.refs} == {ELEMENT_IDENTIFIER}


def test_analyser_version_change_is_a_miss(app, tmp_path, monkeypatch):
    tool = make_tool(app, tmp_path)
    reviewer(tmp_path).review(tool)
    monkeypatch.setattr(security_review, "ANALYSER_VERSION", "next")
    r = reviewer(tmp_path)
    assert r.review(tool, compute=False) is None
    r.review(tool)
    assert len(stored_files(r)) == 2


def test_stored_review_of_another_analyser_version_is_ignored(tmp_path):
    cache = ReviewCache(str(tmp_path))
    os.makedirs(os.path.dirname(cache.path("ab12")))
    with open(cache.path("ab12"), "w") as fh:
        json.dump({**ToolReview(ANALYSED).to_dict(), "analyser_version": "0"}, fh)
    assert cache.get("ab12") is None


@pytest.mark.parametrize("content", ["", "{not json", '{"analyser_version": "1"}', "[]"])
def test_corrupt_file_is_a_miss(app, tmp_path, content):
    tool = make_tool(app, tmp_path)
    r = reviewer(tmp_path)
    r.review(tool)
    (path,) = stored_files(r)
    with open(path, "w") as fh:
        fh.write(content)
    fresh = reviewer(tmp_path)
    assert fresh.review(tool, compute=False) is None
    review = fresh.review(tool)
    assert review is not None and review.status == ANALYSED
    assert ReviewCache(fresh.cache.directory).get(os.path.basename(path)[: -len(".json")]) == review


def test_write_is_atomic(tmp_path, monkeypatch):
    cache = ReviewCache(str(tmp_path))
    old = ToolReview(ANALYSED, tool_id="old")
    cache.put("ab12", old)

    def interrupted(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(OSError):
        cache.put("ab12", ToolReview(ANALYSED, tool_id="new"))
    # Readers still see the whole old review, and no partial file is left behind.
    assert cache.get("ab12") == old
    assert os.listdir(os.path.dirname(cache.path("ab12"))) == ["ab12.json"]


def test_timeout_is_recorded_as_not_analysed(app, tmp_path, caplog):
    r = reviewer(tmp_path, timeout=-1)
    tool = make_tool(app, tmp_path)
    review = r.review(tool)
    assert review is not None and review.status == NOT_ANALYSED and review.reason == "timeout"
    assert "took longer than" in caplog.text
    # Stored, so the next process does not try again.
    assert reviewer(tmp_path).review(tool, compute=False) == review


def test_analyser_error_is_recorded_as_not_analysed(app, tmp_path, monkeypatch):
    def broken(*args, **kwds):
        raise RuntimeError("analyser bug")

    monkeypatch.setattr(security_review, "review_tool_source", broken)
    tool = make_tool(app, tmp_path)
    r = reviewer(tmp_path, ENFORCE)
    review = r.review(tool)
    assert review is not None and review.status == NOT_ANALYSED and review.reason == "error: RuntimeError"


def test_timeout_raised_while_reviewing(app, tmp_path, monkeypatch):
    def slow(*args, **kwds):
        raise ReviewTimeout()

    monkeypatch.setattr(security_review, "review_tool_source", slow)
    review = reviewer(tmp_path).review(make_tool(app, tmp_path))
    assert review is not None and review.reason == "timeout"


def test_summary_is_logged_once_when_computed(app, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger=security_review.__name__)
    tool = make_tool(app, tmp_path)
    reviewer(tmp_path).review(tool)
    assert caplog.text.count("Security review of tool echo_ids version 1.0: 2 high finding(s)") == 1
    caplog.clear()
    reviewer(tmp_path).review(tool)
    assert "Security review of tool" not in caplog.text


def test_tool_without_command_is_not_reviewed(app, tmp_path):
    tool = make_tool(app, tmp_path, NO_COMMAND)
    assert reviewed_tool_source(tool) is None
    r = reviewer(tmp_path)
    assert r.review(tool) is None
    assert stored_files(r) == []


def test_tool_method(app, tmp_path):
    tool = make_tool(app, tmp_path)
    assert tool.security_review() is None  # MockApp has reviews off
    app.tool_security_reviewer = reviewer(tmp_path)
    review = tool.security_review()
    assert review is not None and review.status == ANALYSED


def test_warm_up(app, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger=security_review.__name__)
    r = reviewer(tmp_path)
    tools = [make_tool(app, tmp_path), make_tool(app, tmp_path, NO_COMMAND, "no_command.xml")]
    r.warm_up(lambda: tools)
    assert r._warm_up_thread is not None
    r._warm_up_thread.join(30)
    assert len(stored_files(r)) == 1
    assert "warm-up: 1 tool(s) reviewed" in caplog.text


# -- off ---------------------------------------------------------------------------------------


def test_off_does_nothing(app, tmp_path, monkeypatch):
    def fail(*args, **kwds):
        raise AssertionError("reviewed while off")

    monkeypatch.setattr(security_review, "review_tool_source", fail)
    r = reviewer(tmp_path, OFF)
    tool = make_tool(app, tmp_path)
    assert r.review(tool) is None
    r.warm_up(lambda: [tool])
    assert r._warm_up_thread is None
    assert not os.path.exists(r.cache.directory)
