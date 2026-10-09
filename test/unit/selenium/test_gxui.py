"""gxui tests: verb parsing without a browser, plus a real daemon and client driving the fixture pages."""

import http.server
import json
import os
import subprocess
import sys
import threading
import time
from datetime import (
    datetime,
    timezone,
)
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

import pytest
import yaml
from playwright.sync_api import sync_playwright

import galaxy.selenium
from galaxy.selenium.gxui.config import ConfigError
from galaxy.selenium.gxui.context import (
    _QUOTED_ARGUMENT,
    GxuiContext,
)
from galaxy.selenium.gxui.daemon import (
    _error_text,
    _summarize,
)
from galaxy.selenium.gxui.verbs import (
    _auto,
    _CONNECTION,
    _describe_line,
    _first_instance,
    _history_id,
    _open_form,
    _run_form_inputs,
    _terminal,
    invocation_wait,
    method_listing,
    method_verb,
    register_method_verbs,
    REGISTRY,
    UsageError,
    workflow_run,
)
from galaxy.selenium.navigates_galaxy import (
    NavigatesGalaxy,
    ToolFormParameter,
)
from .util import skip_unless_playwright_browser_cached

GALAXY_LIB = Path(galaxy.selenium.__file__).resolve().parents[2]

register_method_verbs(GxuiContext)


class TestVerbParsing:
    def test_positional_from_signature(self):
        assert REGISTRY["history-new"].parse(["My Analysis"]) == (["My Analysis"], {})

    def test_varargs_and_options(self):
        args, kwargs = REGISTRY["upload-url"].parse(["http://a/1.fq", "http://a/2.fq", "--ext", "fastqsanger"])
        assert args == ["http://a/1.fq", "http://a/2.fq"]
        assert kwargs == {"ext": "fastqsanger"}

    def test_unannotated_method_args_become_ints(self):
        assert REGISTRY["dataset-view"].parse(["3"]) == ([3], {})

    def test_method_verb_options_from_method_defaults(self):
        class Context:
            def wait_for(self, hid, allowed_force_refreshes=0):
                """Wait for HID."""

        method_verb("test-wait", "history", "wait_for", Context)
        try:
            assert REGISTRY["test-wait"].parse(["3", "--allowed-force-refreshes", "1"]) == (
                [3],
                {"allowed_force_refreshes": 1},
            )
            assert REGISTRY["test-wait"].summary() == "Wait for HID."
        finally:
            del REGISTRY["test-wait"]

    def test_boolean_flag(self):
        assert REGISTRY["workflow-run"].parse(["QC", "--no-submit"]) == ([], {"name": "QC", "submit": False})

    def test_missing_positional_reports_usage(self):
        with pytest.raises(UsageError, match="usage: gxui history-new NAME"):
            REGISTRY["history-new"].parse([])

    def test_unknown_option_reports_usage(self):
        with pytest.raises(UsageError, match="unexpected arguments"):
            REGISTRY["history-new"].parse(["x", "--colour", "red"])

    def test_help_comes_from_method_docstring(self):
        assert "(backs onto display_dataset)" in REGISTRY["dataset-view"].help()


@pytest.fixture
def fixture_url(base_url):
    return f"{base_url}/basic.html"


@pytest.fixture
def gxui(tmp_path):
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("GXUI_")},
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "GXUI_HOME": str(tmp_path),  # long on macOS, so this also exercises the short-socket fallback
        "GXUI_SESSION": "t",
        "PYTHONPATH": str(GALAXY_LIB),
    }

    def run(*argv, check=True):
        result = subprocess.run(
            [sys.executable, "-m", "galaxy.selenium.gxui.client", *argv], env=env, capture_output=True, text=True
        )
        if check:
            assert result.returncode == 0, result.stderr
        return result

    run.env = env
    yield run
    run("stop", check=False)


@skip_unless_playwright_browser_cached()
def test_daemon_drives_a_page(gxui, fixture_url, tmp_path):
    started = gxui("start", "--url", fixture_url, "--idle-timeout", "0", "--timeout-multiplier", "0.2").stdout
    cdp = next(line.split()[1] for line in started.splitlines() if line.startswith("cdp "))
    assert "already running" in gxui("start", "--url", fixture_url).stdout

    assert "'Basic Test Page'" in gxui("url").stdout
    assert gxui("call", "wait_for_selector_visible", "#header").returncode == 0

    snapshot_path = gxui("snapshot", "--label", "basic").stdout.split()[0]
    assert "Test Page" in Path(snapshot_path).read_text()
    assert Path(gxui("screenshot", "basic").stdout.strip()).exists()

    # Another client (playwright-cli in practice) sees the same page over CDP.
    with urlopen(f"{cdp}/json/list") as response:
        assert fixture_url in [t["url"] for t in json.load(response) if t["type"] == "page"]

    unknown = gxui("histroy-new", "x", check=False)
    assert unknown.returncode == 1 and "unknown verb 'histroy-new'" in unknown.stderr
    failed = gxui("call", "wait_for_selector_visible", "#nope", check=False)
    assert failed.returncode == 1

    gxui("gap", "need", "a", "hover", "verb")
    gxui("note", "box 1 done")
    # `last` skips notes and gaps: it is for recovering a verb result a shell timeout cut off.
    assert json.loads(gxui("last").stdout)["args"] == ["wait_for_selector_visible", "#nope"]

    lines = [json.loads(line) for line in (tmp_path / "t" / "transcript.jsonl").read_text().splitlines()]
    assert [(e["layer"], e["verb"]) for e in lines] == [
        ("verb", "url"),
        ("call", "call"),
        ("verb", "snapshot"),
        ("verb", "screenshot"),
        ("call", "call"),
        ("external", "gap"),
        ("note", "note"),
    ]
    assert lines[4]["ok"] is False and "screenshot" in lines[4]

    gxui("stop")
    assert "no gxui daemon" in gxui("status", check=False).stderr


@skip_unless_playwright_browser_cached()
def test_browser_death_relaunches(gxui, fixture_url):
    started = gxui("start", "--url", fixture_url, "--idle-timeout", "0").stdout
    port = next(line for line in started.splitlines() if line.startswith("cdp ")).rsplit(":", 1)[1]
    subprocess.run(["pkill", "-f", f"remote-debugging-port={port}"], check=True)

    died = gxui("url", check=False)
    assert died.returncode == 1 and "relaunched" in died.stderr
    assert "'Basic Test Page'" in gxui("url").stdout
    assert "browser relaunches 1" in gxui("status").stdout


def test_optional_positional_and_default_true_flag_usage():
    assert REGISTRY["components"].parse(["history_panel"]) == ([], {"prefix": "history_panel"})
    assert REGISTRY["components"].parse([]) == ([], {})
    assert REGISTRY["component"].usage() == "component PATH ACTION [VALUE] [--timeout TIMEOUT]"
    assert "[--no-submit]" in REGISTRY["workflow-run"].usage()


def test_history_wait_is_an_adapter_with_a_deadline():
    assert REGISTRY["history-wait"].parse(["2", "--timeout", "30"]) == ([2], {"timeout": 30.0})


def test_results_are_summarized_for_the_transcript():
    assert _summarize(None) == "ok"
    assert _summarize("hid 2 ok") == "hid 2 ok"
    assert _summarize(object()) == "ok"


def test_verb_errors_keep_every_line_and_framework_errors_lose_their_call_log():
    assert _error_text(TimeoutError("invocation i1 scheduled\n  hid 3 ok")) == "invocation i1 scheduled\n  hid 3 ok"

    class FrameworkTimeout(Exception):
        pass

    assert _error_text(FrameworkTimeout("Timeout 5000ms\nCall log:\n  - waiting")) == "Timeout 5000ms"


def test_component_paths_accept_quoted_arguments():
    path = "workflow_run.input_data_div(label='FASTQ reads')"
    assert _QUOTED_ARGUMENT.sub(r"=\2", path) == "workflow_run.input_data_div(label=FASTQ reads)"


def test_workflow_extract_arguments():
    assert REGISTRY["workflow-extract"].parse(["QC", "--input-names", "FASTQ reads", "--exclude-hids", "5"]) == (
        ["QC"],
        {"input_names": "FASTQ reads", "exclude_hids": "5"},
    )


def test_component_rejects_unknown_actions_before_touching_the_page():
    with pytest.raises(UsageError, match="unknown action 'hover'"):
        REGISTRY["component"].func(None, "history_panel.item(hid=1)", "hover")


@skip_unless_playwright_browser_cached()
def test_last_reports_a_running_verb(gxui, fixture_url):
    gxui("start", "--url", fixture_url, "--idle-timeout", "0", "--timeout-multiplier", "0.5")
    env_run = subprocess.Popen(
        [sys.executable, "-m", "galaxy.selenium.gxui.client", "call", "wait_for_selector_visible", "#nope"],
        env={**os.environ, **gxui.env},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            if "still running: call wait_for_selector_visible" in gxui("last").stdout:
                break
            time.sleep(0.1)
        else:
            pytest.fail("`last` never reported the running verb")
    finally:
        env_run.wait()


def test_auto_leaves_css_attribute_selectors_alone():
    assert _auto('[data-description="name display"]') == '[data-description="name display"]'
    assert _auto('{"input1": 3}') == {"input1": 3}


def test_tool_describe_lines_carry_options_and_conditions():
    parameter = ToolFormParameter("cond|flag", "Flag", "boolean", False, [], "cond|test=b")
    assert _describe_line(parameter) == "cond|flag  (boolean) 'Flag' = False  [when cond|test=b]"
    select = ToolFormParameter("mode", "Mode", "select", "a", [("A", "a"), ("b", "b")])
    assert _describe_line(select) == "mode  (select) 'Mode' = 'a'  options: A=a, b"
    assert REGISTRY["tool-describe"].parse([]) == ([], {})
    assert REGISTRY["tool-describe"].parse(["cat1"]) == ([], {"tool_id": "cat1"})


def test_dataset_copy_and_history_share_arguments():
    assert REGISTRY["dataset-copy"].parse(["2", "--source", "My Analysis"]) == ([2], {"source": "My Analysis"})
    assert REGISTRY["history-share"].parse(["--publish"]) == ([], {"publish": True})


class _HistoriesStub:
    def __init__(self, histories):
        self.histories = histories

    def api_get(self, endpoint):
        assert endpoint.startswith("histories")
        return self.histories

    def current_history_id(self):
        return "c0"


def test_history_names_resolve_to_ids():
    ctx = _HistoriesStub(
        [{"id": "a1", "name": "My Analysis"}, {"id": "b2", "name": "Next"}, {"id": "b3", "name": "Next"}]
    )
    assert _history_id(ctx, "My Analysis") == "a1"
    assert _history_id(ctx, "b3") == "b3"
    assert _history_id(ctx, "") == "c0"
    with pytest.raises(UsageError, match="2 histories named 'Next'"):
        _history_id(ctx, "Next")
    with pytest.raises(UsageError, match="no history 'Nope'"):
        _history_id(ctx, "Nope")


def test_method_listing_filters_and_points_at_verbs():
    listing = method_listing(GxuiContext, "create_new_with_name")
    assert listing.splitlines()[0].startswith("history_panel_create_new_with_name(name)")
    assert "[verb: history-new]" in listing
    assert "_screenshot_path" not in method_listing(GxuiContext, "screenshot")
    assert REGISTRY["methods"].parse(["history"]) == ([], {"text": "history"})


class _RecordingContext:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append(name)

    def current_history_id(self):
        return "h1"


def test_history_new_goes_home_first():
    ctx = _RecordingContext()
    REGISTRY["history-new"].func(ctx, "Next Analysis")
    assert ctx.calls == ["home", "history_panel_create_new_with_name"]


class _MultiviewStub:
    """A Multiview whose drag never finds its columns; ``hooks`` is how many per-history hooks the page has."""

    def __init__(self, hooks):
        self.hooks = hooks
        self.page = self

    def api_get(self, endpoint):
        return [{"id": "a1", "name": "Source"}, {"id": "b2", "name": "Target"}]

    def current_history_id(self):
        return "b2"

    def history_contents(self, history_id=None):
        return []

    def home(self):
        pass

    def open_history_multi_view(self):
        pass

    def multi_history_copy_item(self, hid, from_history_id, to_history_id):
        raise TimeoutError("columns never appeared")

    def locator(self, selector):
        return self

    def count(self):
        return self.hooks


def test_dataset_copy_explains_a_multiview_without_column_hooks():
    with pytest.raises(RuntimeError, match="predates"):
        REGISTRY["dataset-copy"].func(_MultiviewStub(hooks=0), 1, source="Source")
    with pytest.raises(RuntimeError, match="Select Histories"):
        REGISTRY["dataset-copy"].func(_MultiviewStub(hooks=2), 1, source="Source")


class _UrlContext:
    def __init__(self, url):
        self.current_url = url


def test_open_form_comes_from_the_tool_or_rerun_url():
    assert _open_form(_UrlContext("https://g/?tool_id=cat1&version=latest")) == {"tool_id": "cat1"}
    assert _open_form(_UrlContext("https://g/?tool_id=cat1&version=1.0")) == {"tool_id": "cat1", "tool_version": "1.0"}
    assert _open_form(_UrlContext("https://g/root?job_id=bbd44e69cb8906b5")) == {"job_id": "bbd44e69cb8906b5"}
    with pytest.raises(UsageError, match="dataset-rerun"):
        _open_form(_UrlContext("https://g/"))


def test_workflow_editor_verb_arguments():
    assert REGISTRY["workflow-add-input"].parse(["data_collection_input", "--label", "A text dataset collection"]) == (
        [],
        {"kind": "data_collection_input", "label": "A text dataset collection"},
    )
    args, kwargs = REGISTRY["workflow-output"].parse(
        ["Select first lines", "out_file1", "--add-tags", "name:first", "--rename", "Renamed datasets"]
    )
    assert args == ["Select first lines", "out_file1"]
    assert kwargs == {"add_tags": "name:first", "rename": "Renamed datasets"}


def test_workflow_terminals_are_step_hash_name():
    with pytest.raises(UsageError, match="STEP#INPUT"):
        _terminal(object(), "Reverse dataset", "input")


def test_connection_ids_name_both_ends():
    match = _CONNECTION.match("connection-node-2-input-input-node-1-output-out_file1")
    assert match and match.groups() == ("2", "input", "1", "out_file1")


class _EditorPage:
    url = "https://g/workflows/edit?id=abc"

    def locator(self, selector):
        return self

    def count(self):
        return 0


class _EditorContext:
    current_url = _EditorPage.url
    page = _EditorPage()


def test_open_form_in_the_editor_needs_an_open_tool_step():
    with pytest.raises(UsageError, match="workflow-step"):
        _open_form(_EditorContext())


def test_tool_fill_checks_later_repeat_instances_against_the_first():
    repeats = {"components", "queries"}
    assert (
        _first_instance("components_2|param_type|component_value", repeats) == "components_0|param_type|component_value"
    )
    assert _first_instance("queries_1|inner_3|x", repeats) == "queries_0|inner_3|x"
    assert _first_instance("lineNum", repeats) == "lineNum"


class _WorkflowApi:
    def api_get(self, endpoint):
        assert endpoint == "workflows/w1"
        return {
            "inputs": {"1": {"label": "Number of lines"}, "0": {"label": ""}},
            "steps": {"0": {"type": "data_input"}, "1": {"type": "parameter_input"}},
        }


def test_run_form_inputs_number_unlabelled_inputs_like_the_form():
    assert _run_form_inputs(_WorkflowApi(), "w1") == {"1": "data_input", "Number of lines": "parameter_input"}


class _RunFormContext(_WorkflowApi):
    def __init__(self):
        self.filled = []
        self.page = SimpleNamespace(url="https://galaxy.example/workflows/run?id=w1")
        run_workflow = SimpleNamespace(is_absent=False, wait_for_visible=lambda: None)
        self.components = SimpleNamespace(workflow_run=SimpleNamespace(run_workflow=run_workflow))

    def workflow_run_with_name(self, name):
        pass

    def workflow_run_specify_inputs(self, inputs):
        self.filled.append(inputs)


def test_workflow_run_refuses_to_submit_on_a_preselected_dataset(monkeypatch):
    monkeypatch.setattr("galaxy.selenium.gxui.verbs._wait_for_run_form", lambda ctx: None)
    ctx = _RunFormContext()
    with pytest.raises(UsageError, match=r"\['1'\] not given"):
        workflow_run(ctx, "lines", params='{"Number of lines": 5}')
    assert ctx.filled == []


def test_workflow_run_name_is_optional_for_an_open_form():
    assert REGISTRY["workflow-run"].parse(["--inputs", '{"1": 3}', "--new-history", "results"]) == (
        [],
        {"inputs": '{"1": 3}', "new_history": "results"},
    )
    assert REGISTRY["invocation-cancel"].parse(["abc123"]) == (["abc123"], {})


class _InvocationsApi:
    def __init__(self, update_time):
        self.update_time = update_time
        self.page = SimpleNamespace(url="https://galaxy.example/workflows/run?id=w1")

    def api_get(self, endpoint):
        if endpoint.startswith("invocations?"):
            return [{"id": "inv1"}]
        if endpoint == "invocations/inv1":
            return {"state": "scheduled", "update_time": self.update_time, "history_id": "h1"}
        if endpoint == "invocations/inv1/jobs_summary":
            return {"states": {"ok": 1}}
        if endpoint == "invocations/inv1?step_details=true":
            step = {"jobs": [{}], "order_index": 1, "workflow_step_label": None, "outputs": {"out": {"id": "d2"}}}
            return {"history_id": "h1", "outputs": {}, "steps": [{"jobs": [], "outputs": {"in": {"id": "d1"}}}, step]}
        if endpoint.startswith("histories/h1/contents"):
            return [
                {"id": "d1", "hid": 1, "state": "ok", "name": "in"},
                {"id": "d2", "hid": 2, "state": "ok", "name": "x"},
            ]
        raise AssertionError(endpoint)


def test_invocation_wait_without_an_id_refuses_a_long_finished_invocation():
    with pytest.raises(UsageError, match="inv1"):
        invocation_wait(_InvocationsApi("2020-01-01T00:00:00"))


def test_invocation_wait_lists_step_outputs_but_not_inputs():
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    assert invocation_wait(_InvocationsApi(now)) == "invocation inv1 scheduled; jobs: 1 ok\n  hid 2 ok 'x' (step 2 out)"


def test_api_get_backs_off_while_the_server_rate_limits(monkeypatch):
    responses = [SimpleNamespace(status_code=429, content=b"<html>"), SimpleNamespace(status_code=200, content=b"[]")]
    monkeypatch.setattr(NavigatesGalaxy, "api_get", lambda self, endpoint, data=None, raw=False: responses.pop(0))
    monkeypatch.setattr(NavigatesGalaxy, "_handle_response", lambda self, response, raw=False: response.status_code)
    sleeps = []
    monkeypatch.setattr("galaxy.selenium.gxui.context.time.sleep", sleeps.append)
    assert GxuiContext.__new__(GxuiContext).api_get("histories") == 200
    assert sleeps == [5]


def test_collection_build_arguments_and_kinds():
    assert REGISTRY["collection-build"].parse(["list:paired", "1,2,3,4", "--name", "reads"]) == (
        ["list:paired", "1,2,3,4"],
        {"name": "reads"},
    )
    with pytest.raises(UsageError, match="list:paired"):
        REGISTRY["collection-build"].func(object(), "paired", "1,2")


@pytest.fixture
def login_server():
    """A tiny fixture exercises the existing Galaxy login helpers and user observation API."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/api/users/current":
                logged_in = "galaxysession=fixture-login" in self.headers.get("Cookie", "")
                body = json.dumps(
                    {"id": "fixture", "email": "fixture@example.org", "username": "fixture"} if logged_in else {}
                ).encode()
                content_type = "application/json"
            else:
                body = b"""<!doctype html><title>Login fixture</title>
                <div id="masthead"><button class="loggedout-only" data-description="login masthead button"
                  onclick="document.querySelector('form').hidden=false">Login</button>
                  <span class="loggedin-only" hidden>Signed in</span></div>
                <form id="login" hidden onsubmit="event.preventDefault();
                  if (this.elements.password.value !== 'unit-password') return;
                  document.cookie='galaxysession=fixture-login; Path=/';
                  localStorage.setItem('fixture-auth', 'restored');
                  document.querySelector('.loggedout-only').hidden=true;
                  document.querySelector('.loggedin-only').hidden=false; this.hidden=true;">
                  <input name="login"><input type="password" name="password"><button name="login">Submit</button>
                </form><script>if(document.cookie.includes('fixture-login')) {
                  document.querySelector('.loggedin-only').hidden=false;
                  document.querySelector('.loggedout-only').hidden=true; }</script>"""
                content_type = "text/html"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@skip_unless_playwright_browser_cached()
def test_profile_login_save_restore_and_bound_session(gxui, login_server, tmp_path):
    config = tmp_path / "profiles.yml"
    config.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "default_profile": "fixture",
                "profiles": {
                    "fixture": {
                        "url": login_server,
                        "auth": {"username": "fixture@example.org", "password_env": "FIXTURE_PASSWORD"},
                    }
                },
            }
        )
    )
    gxui.env["GXUI_CONFIG"] = str(config)
    gxui.env["FIXTURE_PASSWORD"] = "unit-password"
    gxui("start", "--timeout-multiplier", "0.1", "--idle-timeout", "0")
    assert "fixture" in gxui("status").stdout
    assert "logged in as fixture@example.org" in gxui("login", "--save").stdout
    saved_config = yaml.safe_load(config.read_text())
    auth = saved_config["profiles"]["fixture"]["auth"]
    state_path = Path(auth["storage_state"])
    state = json.loads(state_path.read_text())
    assert state["_gxui"]["url"] == login_server.rstrip("/")
    assert state["origins"][0]["localStorage"] == [{"name": "fixture-auth", "value": "restored"}]
    assert state_path.stat().st_mode & 0o777 == 0o600
    assert "unit-password" not in (tmp_path / "t" / "transcript.jsonl").read_text()
    assert "unit-password" not in (tmp_path / "t.log").read_text()
    assert "already running" in gxui("start").stdout
    assert "different" in gxui("start", "--url", "https://different.example.org", check=False).stderr
    gxui("stop")
    for _ in range(50):
        if gxui("status", check=False).returncode:
            break
        time.sleep(0.1)
    gxui("start", "--idle-timeout", "0")
    assert "logged in as fixture@example.org" in gxui("login").stdout
    cdp = next(line.split()[1] for line in gxui("status").stdout.splitlines() if line.startswith("cdp "))
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(cdp)
        assert browser.contexts[0].pages[0].evaluate("localStorage.getItem('fixture-auth')") == "restored"
        browser.close()


@skip_unless_playwright_browser_cached()
def test_explicit_login_password_is_not_in_transcript(gxui, login_server, tmp_path):
    gxui("start", "--url", login_server, "--timeout-multiplier", "0.1", "--idle-timeout", "0")
    assert (
        "logged in as fixture@example.org" in gxui("login", "fixture@example.org", "--password", "unit-password").stdout
    )
    assert "unit-password" not in gxui("last").stdout
    assert "unit-password" not in (tmp_path / "t" / "transcript.jsonl").read_text()
    assert "unit-password" not in (tmp_path / "t.log").read_text()


@skip_unless_playwright_browser_cached()
@pytest.mark.skipif(
    sys.platform == "linux" and not os.environ.get("DISPLAY"), reason="needs a display for a headed browser"
)
def test_interactive_login_uses_headed_browser_and_saves(gxui, login_server, tmp_path):
    gxui("start", "--url", login_server, "--idle-timeout", "0")
    process = subprocess.Popen(
        [sys.executable, "-m", "galaxy.selenium.gxui.client", "login", "--interactive", "--timeout", "20"],
        env=gxui.env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status = gxui("status").stdout
            if "browser headed" in status and "browser relaunches 1" in status:
                break
            if process.poll() is not None:
                pytest.fail(str(process.communicate()))
            time.sleep(0.1)
        else:
            pytest.fail("interactive login did not open a headed browser")
        cdp = next(line.split()[1] for line in status.splitlines() if line.startswith("cdp "))
        # Simulate the human completing login in the displayed browser, independently of the daemon.
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(cdp)
            page = browser.contexts[0].pages[0]
            page.locator('[data-description="login masthead button"]').click()
            page.locator('input[name="login"]').fill("fixture@example.org")
            page.locator('input[name="password"]').fill("unit-password")
            page.locator('button[name="login"]').click()
            browser.close()
        stdout, stderr = process.communicate(timeout=25)
        assert process.returncode == 0, stderr
        assert "logged in as fixture@example.org" in stdout
        assert (tmp_path / "state/gxui/t-auth.json").exists()
        assert "unit-password" not in (tmp_path / "t/transcript.jsonl").read_text()
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)


@skip_unless_playwright_browser_cached()
def test_saved_auth_state_rejects_a_different_base_url(tmp_path, fixture_url):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"cookies": [], "origins": [], "_gxui": {"url": "https://different.example.org"}}))
    with pytest.raises(ConfigError, match="different Galaxy URL"):
        GxuiContext(
            {
                "driver": {"backend_type": "playwright", "headless": True},
                "local_galaxy_url": fixture_url,
                "storage_state": str(state),
            },
            str(tmp_path),
        )


def test_gxui_url_join_keeps_galaxy_path_prefix():
    context = object.__new__(GxuiContext)
    context.url = context.target_url_from_selenium = "https://example.org/galaxy"
    assert context.build_url("api/users/current") == "https://example.org/galaxy/api/users/current"
    assert context.build_url("") == context.url
