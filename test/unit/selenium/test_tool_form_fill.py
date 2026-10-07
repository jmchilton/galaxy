"""Unit tests for NavigatesGalaxy.tool_form_fill's ordering and retry logic, with a stub form."""

from types import SimpleNamespace

from galaxy.selenium.has_driver import SeleniumTimeoutException
from galaxy.selenium.navigates_galaxy import NavigatesGalaxy


class StubForm:
    """Stands in for NavigatesGalaxy: a form whose elements exist only once ``present`` names them."""

    _parse_repeat_key = staticmethod(NavigatesGalaxy._parse_repeat_key)

    def __init__(self, present, appears_late=()):
        self.present = set(present)
        self.appears_late = set(appears_late)
        self.set_calls = []
        self.wait_types = SimpleNamespace(UX_RENDER=None)
        self.components = SimpleNamespace(
            tool_form=SimpleNamespace(
                parameter_div=lambda parameter: SimpleNamespace(is_absent=parameter not in self.present)
            )
        )

    def sleep_for(self, wait_type):
        # A conditional reveals its late parameters while the form waits.
        self.present |= self.appears_late

    def _add_repeat_instances(self, repeat_name, count):
        pass

    def _expand_collapsed_sections(self):
        pass

    def tool_form_set_parameter(self, key, value):
        if key not in self.present:
            raise SeleniumTimeoutException(f"no {key}")
        self.set_calls.append((key, value))


def test_tool_form_fill_sets_shallow_parameters_first():
    form = StubForm(present={"cond|test", "cond|nested", "top"})
    NavigatesGalaxy.tool_form_fill(form, values={"cond|nested": 1, "top": 2, "cond|test": "a"})
    assert [key for key, _ in form.set_calls] == ["top", "cond|nested", "cond|test"]


def test_tool_form_fill_retries_parameter_a_conditional_reveals_late():
    # Same depth, so the nested parameter is tried first, fails, and must be retried once revealed.
    form = StubForm(present={"cond|test"}, appears_late={"cond|nested"})
    NavigatesGalaxy.tool_form_fill(form, values={"cond|nested": 5, "cond|test": "b"})
    assert form.set_calls == [("cond|test", "b"), ("cond|nested", 5)]


def test_tool_form_fill_skips_parameters_that_never_appear():
    form = StubForm(present={"cond|test"})
    NavigatesGalaxy.tool_form_fill(form, values={"cond|test": "b", "cond|other_case": 5})
    assert form.set_calls == [("cond|test", "b")]


def test_tool_form_fill_works_without_an_execute_button():
    # A workflow editor step's form shares the tool form's header but has no execute button.
    waited = []
    header = SimpleNamespace(wait_for_visible=lambda: waited.append("header"))
    form = SimpleNamespace(
        components=SimpleNamespace(
            tool_form=SimpleNamespace(tool_version=header, section_header=SimpleNamespace(all=list))
        ),
        sleep_for=lambda wait_type: None,
        wait_types=SimpleNamespace(UX_RENDER=None),
    )
    NavigatesGalaxy._expand_collapsed_sections(form)
    assert waited == ["header"]
