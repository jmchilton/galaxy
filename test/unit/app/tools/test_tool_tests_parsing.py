from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError,
)
from threading import Event

import pytest

import galaxy.tools
from galaxy.app_unittest_utils.tools_support import UsesTools
from galaxy.tool_util.verify.parse import parse_tool_test_descriptions

TOOL_WITH_TESTS = """<tool id="${tool_id}" name="Test Tool" version="$version" profile="$profile">
    <command>echo "$param1" &gt; $out1</command>
    <inputs>
        <param type="text" name="param1" value="" />
    </inputs>
    <outputs>
        <data name="out1" format="txt" />
    </outputs>
    <tests>
        <test>
            <param name="param1" value="hello" />
            <output name="out1">
                <assert_contents>
                    <has_text text="hello" />
                </assert_contents>
            </output>
        </test>
    </tests>
</tool>
"""


class TestToolTestsParsing(UsesTools):
    def setup_method(self):
        self.setup_app()

    def teardown_method(self):
        self.tear_down_app()

    @pytest.fixture
    def parse_calls(self, monkeypatch):
        calls = []

        def counting_parse(*args, **kwds):
            calls.append(args)
            return parse_tool_test_descriptions(*args, **kwds)

        monkeypatch.setattr(galaxy.tools, "parse_tool_test_descriptions", counting_parse)
        return calls

    @pytest.mark.parametrize("profile", ["16.01", "24.2"])
    def test_tests_parsed_on_first_access(self, parse_calls, profile):
        tool = self._init_tool(TOOL_WITH_TESTS, profile=profile)
        assert parse_calls == []

        tests = tool.tests
        assert tests is not None
        assert len(tests) == 1
        assert tests[0].inputs == {"param1": "hello"}
        assert tests[0].error is False

        assert tool.tests is not None
        assert len(parse_calls) == 1

    def test_concurrent_first_access_waits_for_tests(self, monkeypatch):
        tool = self._init_tool(TOOL_WITH_TESTS, profile="24.2")
        parsing_started = Event()
        finish_parsing = Event()
        second_access_started = Event()
        parse_calls = []

        def blocking_parse(*args, **kwds):
            parse_calls.append(args)
            parsing_started.set()
            assert finish_parsing.wait(timeout=10)
            return parse_tool_test_descriptions(*args, **kwds)

        def second_access():
            second_access_started.set()
            return tool.tests

        monkeypatch.setattr(galaxy.tools, "parse_tool_test_descriptions", blocking_parse)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(lambda: tool.tests)
            try:
                assert parsing_started.wait(timeout=10)
                second = executor.submit(second_access)
                assert second_access_started.wait(timeout=10)
                with pytest.raises(TimeoutError):
                    second.result(timeout=0.1)
            finally:
                finish_parsing.set()
            for result in (first.result(timeout=10), second.result(timeout=10)):
                assert result is not None
                assert len(result) == 1
                assert result[0].inputs == {"param1": "hello"}
                assert result[0].error is False
        assert len(parse_calls) == 1
