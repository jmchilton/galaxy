"""Verb registry. Each verb is a NavigatesGalaxy/mixin method, or a short adapter composing them.

CLI arguments come from the callable's signature and help from its docstring, so nothing is written
twice. Adapters take the context first; method verbs are bound to the context at call time.
"""

import argparse
import inspect
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import (
    parse_qs,
    quote,
    unquote,
    urlparse,
)

DOMAINS = ["session", "history", "upload", "dataset", "tool", "workflow", "observe", "generic"]


@dataclass
class Verb:
    name: str
    domain: str
    func: Callable[..., Any]
    method: str | None  # backing NavigatesGalaxy method, for help and transcript replay
    layer: str = "verb"
    optional_positional: tuple[str, ...] = ()  # defaulted params taken positionally, e.g. `components PREFIX`

    def parameters(self) -> list[inspect.Parameter]:
        params = list(inspect.signature(self.func).parameters.values())
        return params[1:]  # self or ctx

    def summary(self) -> str:
        doc = inspect.getdoc(self.func) or ""
        return doc.splitlines()[0] if doc else ""

    def usage(self) -> str:
        parts = [self.name]
        for p in self.parameters():
            flag = p.name.replace("_", "-")
            if p.kind is p.VAR_POSITIONAL:
                parts.append(f"{p.name.upper()}...")
            elif p.default is p.empty:
                parts.append(p.name.upper())
            elif p.name in self.optional_positional:
                parts.append(f"[{p.name.upper()}]")
            elif p.default is False:
                parts.append(f"[--{flag}]")
            elif p.default is True:
                parts.append(f"[--no-{flag}]")
            else:
                parts.append(f"[--{flag} {p.name.upper()}]")
        return " ".join(parts)

    def help(self) -> str:
        backing = f"  (backs onto {self.method})" if self.method else ""
        doc = inspect.getdoc(self.func) or ""
        return f"gxui {self.usage()}{backing}\n\n{doc}".rstrip()

    def parse(self, argv: list[str]) -> tuple[list[Any], dict[str, Any]]:
        parser = argparse.ArgumentParser(prog=f"gxui {self.name}", add_help=False, exit_on_error=False)
        positional: list[str] = []
        varargs: str | None = None
        for p in self.parameters():
            convert = _converter(p)
            if p.kind is p.VAR_POSITIONAL:
                parser.add_argument(p.name, nargs="*", type=convert)
                varargs = p.name
            elif p.kind is p.VAR_KEYWORD:
                continue
            elif p.default is p.empty:
                parser.add_argument(p.name, type=convert)
                positional.append(p.name)
            elif p.name in self.optional_positional:
                parser.add_argument(p.name, nargs="?", type=convert)
            elif isinstance(p.default, bool):
                parser.add_argument(f"--{p.name.replace('_', '-')}", dest=p.name, action=argparse.BooleanOptionalAction)
            else:
                parser.add_argument(f"--{p.name.replace('_', '-')}", dest=p.name, type=convert)
        try:
            namespace, extra = parser.parse_known_args(argv)
        except (argparse.ArgumentError, SystemExit) as e:
            raise UsageError(f"{e}; usage: gxui {self.usage()}") from None
        if extra:
            raise UsageError(f"unexpected arguments {extra}; usage: gxui {self.usage()}")
        values = vars(namespace)
        missing = [name for name in positional if values.get(name) is None]
        if missing:
            raise UsageError(f"missing {', '.join(m.upper() for m in missing)}; usage: gxui {self.usage()}")
        args = [values.pop(name) for name in positional]
        if varargs:
            args += values.pop(varargs) or []
        kwargs = {k: v for k, v in values.items() if v is not None}
        return args, kwargs


class UsageError(Exception):
    pass


def _converter(p: inspect.Parameter) -> Callable[[str], Any]:
    annotation = p.annotation
    if isinstance(annotation, str):
        annotation = {"int": int, "float": float, "str": str}.get(annotation, annotation)
    if annotation in (int, float, str):
        return annotation
    if p.default is not p.empty and p.default is not None and type(p.default) in (int, float):
        return type(p.default)
    return _auto


def _auto(value: str) -> Any:
    """Unannotated Galaxy methods take hids as ints and dicts/lists as values."""
    if value.lstrip("-").isdigit():
        return int(value)
    if value[:1] in "[{":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value  # a CSS selector such as [data-description="..."]
    return value


REGISTRY: dict[str, Verb] = {}


def verb(name: str, domain: str, method: str | None = None, layer: str = "verb", positional: tuple[str, ...] = ()):
    def register(func):
        REGISTRY[name] = Verb(name, domain, func, method, layer, positional)
        return func

    return register


def method_verb(name: str, domain: str, method: str, context_class: type, doc: str = "") -> None:
    """Expose a context method unchanged; signature and docstring come from the method.

    ``doc`` covers Galaxy methods that have no docstring yet - each one is a docstring to upstream.
    """
    unbound = getattr(context_class, method)

    def call(ctx, *args, **kwargs):
        return getattr(ctx, method)(*args, **kwargs)

    call.__signature__ = inspect.signature(unbound)  # type: ignore[attr-defined]
    call.__doc__ = inspect.getdoc(unbound) or doc or f"Call {method}."
    REGISTRY[name] = Verb(name, domain, call, method)


def register_method_verbs(context_class: type) -> None:
    for name, domain, method in [
        ("home", "session", "home"),
        ("tool-panel", "tool", "open_toolbox"),
        ("logout", "session", "logout"),
        ("history-rename", "history", "history_panel_rename"),
        ("multiview", "history", "open_history_multi_view"),
        ("dataset-view", "dataset", "display_dataset"),
        ("dataset-details", "dataset", "show_dataset_details"),
        ("workflow-extract-open", "workflow", "navigate_to_workflow_extraction"),
        ("workflow-import-url", "workflow", "workflow_import_submit_url"),
    ]:
        method_verb(name, domain, method, context_class)


# --- session ---------------------------------------------------------------


@verb("login", "session", "submit_login", positional=("email",))
def login(ctx, email: str = "", password: str = ""):
    """Log in. Without arguments, uses the credentials in the daemon's --config (never printed)."""
    email = email or ctx.login_email
    password = password or ctx.login_password
    if not email:
        raise UsageError("no credentials: pass EMAIL --password, or start the daemon with --config")
    ctx.home()
    ctx.submit_login(email, password)
    return f"logged in as {email}"


@verb("register", "session", "register")
def register(ctx, email: str, password: str = "", username: str = ""):
    """Register a new user and log in as them. Never on shared servers that allow one account."""
    ctx.register(email, password or None, username or None)
    return f"registered {email}"


# --- history ---------------------------------------------------------------


@verb("history-new", "history", "history_panel_create_new_with_name")
def history_new(ctx, name: str):
    """Create a history, make it current and name it; waits for the rename to land.

    Creating opens from the history panel, so this goes home first.
    """
    ctx.home()
    ctx.history_panel_create_new_with_name(name)
    return f"history {ctx.current_history_id()} {name!r}"


@verb("history-tag", "history", "history_panel_add_tags")
def history_tag(ctx, *tags: str):
    """Add tags to the current history."""
    ctx.history_panel_add_tags(list(tags))
    return f"tagged {', '.join(tags)}"


@verb("history-items", "history", "history_contents")
def history_items(ctx, deleted: bool = False):
    """List the current history: one line per item, `hid state extension name`.

    An observation verb: it reads what the history panel shows (via Galaxy's API, so it is compact
    and exact) and changes nothing. Allowed under UI-only rules.
    """
    lines = []
    history = ctx.current_history()
    for item in ctx.history_contents(datasets_only=True):
        if item.get("deleted") and not deleted:
            continue
        kind = item.get("extension") or item.get("collection_type") or item.get("history_content_type")
        lines.append(
            f"{item['hid']:>4} {item.get('state') or item.get('populated_state', '?'):<9} {kind:<10} {item['name']}"
        )
    header = f"history {history['id']} {history['name']!r} ({len(lines)} items)"
    return "\n".join([header, *lines])


@verb("history-share", "history", "click_history_option_sharing")
def history_share(ctx, publish: bool = False):
    """Make the current history accessible via link (--publish also publishes it); prints the link.

    Sharing opens from the history panel's menu, so this goes home first.
    """
    history_id = ctx.current_history_id()
    if not ctx.api_get("users/current").get("username"):
        raise RuntimeError(
            "the account has no public name; sharing asks for one first (Preferences > Manage Information)"
        )
    ctx.home()
    ctx.click_history_option_sharing()
    sharing = ctx.components.histories.sharing
    status = ctx.api_get(f"histories/{history_id}/sharing")
    if not status["importable"]:
        sharing.make_accessible.wait_for_and_click()
    if publish and not status["published"]:
        sharing.make_publishable.wait_for_and_click()

    def shared():
        status = ctx.api_get(f"histories/{history_id}/sharing")
        done = status["importable"] and status["username_and_slug"] and (status["published"] or not publish)
        return status if done else None

    status = ctx._wait_on(shared, "the history to become shared", wait_type=ctx.wait_types.DATABASE_OPERATION)
    state = "accessible via link and published" if status["published"] else "accessible via link"
    return f"{state}: {ctx.build_url(status['username_and_slug'], for_selenium=False)}"


def _history_id(ctx, history: str) -> str:
    """The id of a history given by name or id; empty means the current history."""
    if not history:
        return ctx.current_history_id()
    histories = ctx.api_get("histories?keys=id,name")
    if any(h["id"] == history for h in histories):
        return history
    named = [h["id"] for h in histories if h["name"] == history]
    if not named:
        raise UsageError(f"no history {history!r} (by name or id)")
    if len(named) > 1:
        raise UsageError(f"{len(named)} histories named {history!r}; pass an id: {', '.join(named)}")
    return named[0]


TERMINAL_BAD_STATES = {"error", "failed_metadata", "paused", "discarded", "deferred"}


def _hid_state(ctx, hid: int) -> str:
    for item in ctx.history_contents(datasets_only=True):
        if item["hid"] == hid:
            return item.get("state") or item.get("populated_state") or "?"
    return "absent"


@verb("history-wait", "history", "history_panel_wait_for_hid_ok")
def history_wait(ctx, hid: int, timeout: float = 240.0):
    """Wait until history item HID is ok, for up to TIMEOUT seconds. Fails at once on error states.

    Repeats Galaxy's job-completion wait (sized for test servers) until the deadline, so long jobs on
    public servers are fine. On timeout it reports the item's current state.
    """
    deadline = time.time() + timeout
    while True:
        try:
            ctx.history_panel_wait_for_hid_ok(hid, allowed_force_refreshes=1)
            return f"hid {hid} ok"
        except Exception as e:
            if "Timeout" not in type(e).__name__ and "timeout" not in str(e).lower():
                raise
            state = _hid_state(ctx, hid)
            if state == "ok":
                return f"hid {hid} ok"
            if state in TERMINAL_BAD_STATES:
                raise RuntimeError(f"hid {hid} is {state}") from None
            if time.time() >= deadline:
                raise TimeoutError(f"hid {hid} still {state} after {timeout:.0f}s; run history-wait again") from None


# --- upload ----------------------------------------------------------------


def _upload(ctx, method: str, stage, timeout: float) -> str:
    uploader = ctx.upload_context(method)
    stage(uploader)
    # Not start_and_wait_for_uploaded_hids: its per-item wait is sized for test servers and a slow
    # fetch from Zenodo outlives it, so wait with history-wait's deadline instead.
    hids = uploader.start_for_uploaded_hids()
    for hid in hids:
        history_wait(ctx, hid, timeout=timeout)
    return "ok hids " + " ".join(str(h) for h in hids)


@verb("upload-url", "upload", "upload_context('paste-links')")
def upload_url(ctx, *urls: str, ext: str = "", name: str = "", timeout: float = 240.0):
    """Upload one or more URLs (Import Data > Paste Links/URLs); waits until every new item is ok."""
    metadata = {k: v for k, v in (("extension", ext), ("name", name)) if v}
    return _upload(ctx, "paste-links", lambda up: up.stage_paste_links([(u, metadata or None) for u in urls]), timeout)


@verb("upload-paste", "upload", "upload_context('paste-content')")
def upload_paste(ctx, content: str, ext: str = "", name: str = "", timeout: float = 240.0):
    """Upload pasted text as one dataset; waits until it is ok."""
    metadata = {k: v for k, v in (("extension", ext), ("name", name)) if v}
    return _upload(ctx, "paste-content", lambda up: up.stage_paste_content(content, metadata or None), timeout)


@verb("upload-file", "upload", "upload_context('local-file')")
def upload_file(ctx, path: str, ext: str = "", name: str = "", timeout: float = 240.0):
    """Upload a local file as one dataset; waits until it is ok."""
    metadata = {k: v for k, v in (("extension", ext), ("name", name)) if v}
    path = os.path.abspath(os.path.expanduser(path))
    return _upload(ctx, "local-file", lambda up: up.stage_local_file(path, metadata or None), timeout)


# --- dataset ---------------------------------------------------------------


@verb("dataset-peek", "dataset", "history_panel_click_item_title")
def dataset_peek(ctx, hid: int):
    """Expand a history item and print its peek (bounded)."""
    ctx.history_panel_wait_for_hid_ok(hid)
    item = ctx.history_panel_item_component(hid=hid)
    if item.peek.is_absent:
        ctx.history_panel_click_item_title(hid=hid, wait=True)
    return _bounded(item.peek.wait_for_text())


@verb("dataset-copy", "dataset", "multi_history_copy_item")
def dataset_copy(ctx, hid: int, source: str = "", target: str = ""):
    """Copy item HID between histories by dragging it in History Multiview; prints its new hid.

    --source and --target take a history name or id and default to the current history; pass one.
    Both must be Multiview columns: pinned, or among the most recently updated histories.
    """
    source_id, target_id = _history_id(ctx, source), _history_id(ctx, target)
    if source_id == target_id:
        raise UsageError("source and target are the same history; pass --source or --target")
    before = {item["hid"] for item in ctx.history_contents(history_id=target_id)}
    ctx.home()
    ctx.open_history_multi_view()
    try:
        ctx.multi_history_copy_item(hid, from_history_id=source_id, to_history_id=target_id)
    except Exception as e:
        if "imeout" not in type(e).__name__:
            raise
        if not ctx.page.locator(".multi-history-panel [data-history-id]").count():
            raise RuntimeError(
                "this Galaxy's Multiview has no per-history column hooks (it predates the Galaxy gxui runs "
                "from): drag the item in Multiview by hand"
            ) from None
        raise RuntimeError(
            f"hid {hid} of {source or 'the current history'} or the {target or 'current'} history is not a "
            "Multiview column; pin both with Multiview's Select Histories"
        ) from None

    def copied():
        return [item["hid"] for item in ctx.history_contents(history_id=target_id) if item["hid"] not in before]

    new_hids = ctx._wait_on(copied, "the copy to appear", wait_type=ctx.wait_types.DATABASE_OPERATION)
    return f"copied hid {hid} as hid {' '.join(str(h) for h in new_hids)} of {target or 'the current history'}"


@verb("dataset-rerun", "dataset", "hda_click_primary_action_button")
def dataset_rerun(ctx, hid: int):
    """Open the rerun form for the job that made item HID, holding that job's settings. Does not submit.

    Change fields with `tool-fill` (`tool-describe` shows the job's values), submit with `tool-run`.
    """
    ctx.home()
    ctx.hda_click_primary_action_button(hid, "rerun")
    ctx.components.tool_form.execute.wait_for_visible()
    job_id = _open_form(ctx).get("job_id", "?")
    return f"rerun form open for job {job_id} (made hid {hid}); `gxui tool-describe` shows its settings"


# --- tool ------------------------------------------------------------------


@verb("tool-open", "tool", "tool_open")
def tool_open(ctx, tool_id: str):
    """Open a tool's form by id; waits for the form.

    Simple ids go through the tool panel search. Tool Shed GUIDs open the form's URL instead: the
    panel's `id:` search and tool_link selector both miss them today.
    """
    if "/" in tool_id:
        ctx.navigate_to(ctx.build_url(f"?tool_id={quote(tool_id, safe='')}&version=latest"))
        route = " (via URL)"
    else:
        ctx.tool_open(tool_id)
        route = ""
    ctx.components.tool_form.execute.wait_for_visible()
    version = ctx.components.tool_form.tool_version
    return f"form open: {tool_id}{route}" + (f" {version.wait_for_text()}" if not version.is_absent else "")


@verb("tool-search", "tool", "components.tools.search")
def tool_search(ctx, text: str):
    """Open the Tools panel and search it for TEXT (a tool name, or `id:<tool id>`); lists matching tools."""
    ctx.open_toolbox()
    ctx.components.tools.clear_search.wait_for_and_click()
    ctx.components.tools.search.wait_for_and_send_keys(text)
    ctx.sleep_for(ctx.wait_types.UX_RENDER)
    # navigation.yml has no tool-title component yet.
    lines = []
    for title in ctx.page.locator("#toolbox-panel .toolTitle").all()[:20]:
        text = title.inner_text().strip().splitlines()
        links = title.locator("a")
        href = (links.first.get_attribute("href") or "") if links.count() else ""
        tool_id = unquote(href.split("tool_id=", 1)[1].split("&", 1)[0]) if "tool_id=" in href else "?"
        lines.append(f"{text[0] if text else '?'}  [{tool_id}]")
    return "\n".join(lines) or "no matching tools"


def _open_form(ctx) -> dict[str, str]:
    """The open tool or rerun form, as tool_form_parameters arguments, read from the URL."""
    query = {key: values[0] for key, values in parse_qs(urlparse(ctx.current_url).query).items()}
    if "job_id" in query:
        return {"job_id": query["job_id"]}
    if "tool_id" not in query:
        raise UsageError("no tool form open; run `gxui tool-open TOOL_ID` or `gxui dataset-rerun HID`, or pass TOOL_ID")
    form = {"tool_id": query["tool_id"]}
    if query.get("version", "latest") != "latest":
        form["tool_version"] = query["version"]
    return form


def _describe_line(parameter) -> str:
    line = f"{parameter.path}  ({parameter.type}) {parameter.label!r} = {parameter.value!r}"
    if parameter.options:
        shown = [label if label == value else f"{label}={value}" for label, value in parameter.options[:12]]
        line += "  options: " + ", ".join(shown) + (" ..." if len(parameter.options) > 12 else "")
    if parameter.condition:
        line += f"  [when {parameter.condition}]"
    return line


@verb("tool-describe", "tool", "tool_form_parameters", positional=("tool_id",))
def tool_describe(ctx, tool_id: str = ""):
    """List a tool form's fields: path, type, label, value, options, and the conditional case showing each.

    Defaults to the open form; a rerun form shows the job's settings. Tutorials name fields by label;
    `tool-fill` takes the path.
    """
    form = {"tool_id": tool_id} if tool_id else _open_form(ctx)
    return "\n".join(_describe_line(p) for p in ctx.tool_form_parameters(**form))


@verb("tool-fill", "tool", "tool_form_fill")
def tool_fill(ctx, values: str):
    """Fill the open tool form from a JSON object of {path: value}; data fields take a hid. Does not submit.

    Paths come from `tool-describe`. Set a conditional's test parameter in the same call as the fields
    it reveals; repeats get the instances their paths name.
    """
    try:
        requested = json.loads(values)
    except json.JSONDecodeError as e:
        raise UsageError(f"VALUES must be a JSON object: {e}") from None
    types = {p.path: p.type for p in ctx.tool_form_parameters(**_open_form(ctx))}
    unknown = sorted(set(requested) - set(types))
    if unknown:
        raise UsageError(f"unknown paths {unknown}; see `gxui tool-describe`")
    data = {k: v for k, v in requested.items() if types[k] in ("data", "data_collection")}
    ctx.tool_form_fill({k: v for k, v in requested.items() if k not in data}, data)
    return f"filled {len(requested)} fields; review with `gxui screenshot`, submit with `gxui tool-run`"


@verb("tool-run", "tool", "tool_form_execute")
def tool_run(ctx):
    """Submit the open tool form; prints the new output hids. Follow with `history-wait HID`."""
    before = (ctx._latest_history_item() or {}).get("hid", 0)
    ctx.tool_form_execute()
    new_hids: list[int] = []

    def outputs_appeared(driver=None):
        nonlocal new_hids
        new_hids = [i["hid"] for i in ctx.history_contents(datasets_only=True) if i["hid"] > before]
        return True if new_hids else None

    ctx._wait_on(outputs_appeared, "tool outputs to appear in the history", wait_type=ctx.wait_types.DATABASE_OPERATION)
    return "submitted; output hids " + " ".join(str(h) for h in new_hids)


# --- workflow --------------------------------------------------------------


@verb("workflow-run", "workflow", "workflow_run_with_name")
def workflow_run(ctx, name: str, inputs: str = "", submit: bool = True):
    """Open the run form for the named workflow, set data inputs, submit.

    INPUTS is JSON mapping input label to hid, e.g. '{"input1": 1}'.
    """
    ctx.workflow_run_with_name(name)
    if inputs:
        ctx.workflow_run_specify_inputs({label: {"hid": hid} for label, hid in json.loads(inputs).items()})
    if submit:
        ctx.workflow_run_submit()
        return f"submitted {name!r}"
    return f"run form open for {name!r}"


@verb("workflow-extract", "workflow", "extract_workflow_name_and_submit")
def workflow_extract(ctx, name: str, input_names: str = "", exclude_hids: str = "", submit: bool = True):
    """Extract a workflow from the current history, name it, and create it.

    --input-names 'FASTQ reads' renames the input cards in order (comma-separated for several).
    --exclude-hids 5 leaves out the tool steps that created those history items (comma-separated).
    --no-submit stops before creating, to check the form (`gxui snapshot workflow_extract`).
    """
    ctx.navigate_to_workflow_extraction()
    extract = ctx.components.workflow_extract
    for hid in _int_list(exclude_hids):
        job_id = ctx.api_get(f"datasets/{_dataset_id(ctx, hid)}")["creating_job"]
        checkbox = extract.card_checkbox_by_job_id(job_id=job_id)
        element = checkbox.wait_for_present()
        if ctx.locator(checkbox).is_checked():
            # The card checkbox is an opacity-0 input; Galaxy's own extraction tests click it by script.
            ctx.execute_script_click(element)
        if ctx.locator(checkbox).is_checked():
            raise RuntimeError(f"could not exclude the step that created hid {hid}")
    # navigation.yml has no input-card rename components yet.
    for index, label in enumerate(n.strip() for n in input_names.split(",") if n.strip()):
        ctx.page.locator('[data-step-type^="input_"] .g-card-rename').nth(index).click()
        ctx.page.locator("#input-name-input").fill(label)
        ctx.page.locator("#rename-modal-input .g-modal-confirm-buttons button:last-of-type").click()
        ctx.page.locator("#input-name-input").wait_for(state="detached")
    if not submit:
        ctx.extract_workflow_set_name(name)
        return "form filled, not submitted"
    ctx.extract_workflow_name_and_submit(name)
    extract._.wait_for_absent()
    return f"extracted {name!r}; now on {ctx.page.url}"


def _int_list(text: str) -> list[int]:
    return [int(part) for part in str(text).split(",") if part.strip()]


def _dataset_id(ctx, hid: int) -> str:
    for item in ctx.history_contents(datasets_only=True):
        if item["hid"] == hid:
            return item["id"]
    raise UsageError(f"no hid {hid} in the current history")


# --- observe ---------------------------------------------------------------


@verb("url", "observe")
def url(ctx):
    """Print the current URL and page title."""
    return f"{ctx.page.url}  {ctx.page.title()!r}"


@verb("screenshot", "observe", "screenshot")
def screenshot(ctx, label: str):
    """Save a PNG of the page; prints the path."""
    return ctx.screenshot(label)


@verb("snapshot", "observe", positional=("component",))
def snapshot(ctx, component: str = "", label: str = ""):
    """Write the page's (or one component's) accessibility tree to a file; prints the path and size."""
    scope = ""
    if component:
        try:
            target = ctx.component(component)
        except ValueError:
            # A group such as tool_form has no element of its own; its parts are in the center panel.
            target = ctx.component("_.center_panel")
            scope = f"; {component} groups components, so this is the center panel"
        target.wait_for_visible()
        tree = ctx.locator(target).aria_snapshot()
    else:
        tree = ctx.page.locator("body").aria_snapshot()
    directory = os.path.join(ctx.artifacts, "aria")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{time.strftime('%H%M%S')}-{label or component or 'page'}.yml")
    with open(path, "w") as f:
        f.write(tree)
    return f"{path} ({tree.count(chr(10)) + 1} lines{scope})"


# --- generic: components and raw calls -------------------------------------

COMPONENT_ACTIONS = [
    "click",
    "check",
    "uncheck",
    "text",
    "value",
    "visible",
    "absent",
    "wait",
    "send-keys",
    "clear-send-keys",
]


@verb("component", "generic", "components.<path>", layer="component", positional=("value",))
def component(ctx, path: str, action: str, value: str = "", timeout: float = 30.0):
    """Act on one navigation.yml component: click|check|uncheck|text|value|visible|absent|wait|send-keys|clear-send-keys.

    PATH uses the tour grammar, e.g. 'history_panel.item(hid=3).title'. Waits up to TIMEOUT seconds.
    check/uncheck also work on styled checkboxes whose input is invisible.
    """
    if action not in COMPONENT_ACTIONS:
        raise UsageError(f"unknown action {action!r}; one of {', '.join(COMPONENT_ACTIONS)}")
    target = ctx.component(path)
    try:
        if action == "click":
            target.wait_for_and_click(timeout=timeout)
            return "clicked"
        if action in ("check", "uncheck"):
            want = action == "check"
            element = target.wait_for_present(timeout=timeout)
            if ctx.locator(target).is_checked() != want:
                ctx.execute_script_click(element)
            if ctx.locator(target).is_checked() != want:
                raise RuntimeError(f"{path} did not become {action}ed")
            return f"{action}ed"
        if action == "text":
            return _bounded(target.wait_for_text(timeout=timeout))
        if action == "value":
            return target.wait_for_value(timeout=timeout)
        if action in ("visible", "wait"):
            target.wait_for_visible(timeout=timeout)
            return "visible"
        if action == "absent":
            target.wait_for_absent_or_hidden(timeout=timeout)
            return "absent"
        target.wait_for_visible(timeout=timeout)
        if action == "send-keys":
            target.wait_for_and_send_keys(value)
        else:
            target.wait_for_and_clear_and_send_keys(value)
        return "sent"
    except Exception as e:
        if "imeout" in type(e).__name__ and action != "absent" and not target.is_absent:
            raise RuntimeError(
                f"{path} is in the page but not visible/clickable after {timeout:.0f}s "
                "(a styled checkbox or hidden input?): try `check`/`uncheck`, or its visible label"
            ) from None
        raise


@verb("components", "generic", layer="component", positional=("prefix",))
def components(ctx, prefix: str = ""):
    """Browse the navigation.yml tree: child components and selectors under PREFIX."""
    node = ctx.navigation
    for part in [p for p in prefix.split(".") if p]:
        node = getattr(node, part)
    children = sorted(node.sub_components)
    selectors = dict(node.selectors.items())
    labels = dict(node.labels.items())
    lines = [f"{prefix or '<root>'}: {len(children)} components, {len(selectors)} selectors, {len(labels)} labels"]
    lines += [f"  {name}/" for name in children]
    lines += [f"  {name}: {_selector_text(sel)}" for name, sel in sorted(selectors.items())]
    lines += [f"  {name}: label {label.text!r}" for name, label in sorted(labels.items())]
    return "\n".join(lines)


@verb("call", "generic", layer="call")
def call(ctx, method: str, *args: str):
    """Call any public context method with no verb yet; `gxui methods TEXT` finds them.

    Logged; frequent calls are verbs to promote.
    """
    if method.startswith("_"):
        raise UsageError("private methods are off limits")
    if not callable(getattr(ctx, method, None)):
        raise UsageError(f"no method {method!r}; see `gxui methods TEXT`")
    value = getattr(ctx, method)(*[_auto(a) for a in args])
    return "ok" if value is None else _bounded(repr(value))


@verb("methods", "generic", positional=("text",))
def methods(ctx, text: str = ""):
    """List the context methods `call` reaches whose names contain TEXT: signature, summary, covering verb."""
    return method_listing(type(ctx), text)


def method_listing(context_class: type, text: str = "") -> str:
    covered = {v.method: v.name for v in REGISTRY.values() if v.method}
    names = [
        name
        for name in sorted(dir(context_class))
        if not name.startswith("_") and text in name and inspect.isfunction(inspect.getattr_static(context_class, name))
    ]
    if not text:
        return f"{len(names)} methods; pass TEXT for signatures\n" + " ".join(names)
    lines = []
    for name in names:
        function = getattr(context_class, name)
        signature = inspect.signature(function)
        signature = signature.replace(parameters=list(signature.parameters.values())[1:])
        doc = inspect.getdoc(function) or ""
        line = f"{name}{signature}"
        if doc:
            line += f"  - {doc.splitlines()[0]}"
        if name in covered:
            line += f"  [verb: {covered[name]}]"
        lines.append(line)
    return "\n".join(lines) or f"no methods contain {text!r}"


def _selector_text(selector) -> str:
    return getattr(selector, "_selector", None) or str(selector)


def _bounded(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else text[:limit] + f"... [{len(text) - limit} more chars]"


def help_text(topic: str = "") -> str:
    if topic in REGISTRY:
        return REGISTRY[topic].help()
    domains = [topic] if topic in DOMAINS else DOMAINS
    lines = []
    for domain in domains:
        verbs = [v for v in REGISTRY.values() if v.domain == domain]
        if not verbs:
            continue
        lines.append(f"{domain}:")
        lines += [f"  {v.usage():<44} {v.summary()}" for v in verbs]
    lines.append(
        "built in: start, stop, status, last, help [DOMAIN|VERB], note TEXT, gap REASON, dialog accept|dismiss"
    )
    return "\n".join(lines)
