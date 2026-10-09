"""Verb registry. Each verb is a NavigatesGalaxy/mixin method, or a short adapter composing them.

CLI arguments come from the callable's signature and help from its docstring, so nothing is written
twice. Adapters take the context first; method verbs are bound to the context at call time.
"""

import argparse
import inspect
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import (
    datetime,
    timezone,
)
from typing import Any
from urllib.parse import (
    parse_qs,
    quote,
    unquote,
    urlparse,
)

from selenium.webdriver.common.keys import Keys

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
    """Log in using the session profile, environment credentials or a masked prompt.

    The client also supports --password-stdin, --save and --interactive for browser/SSO login."""
    # The client runs `gxui login` itself (prompts, saved state); this entry is its help text.
    raise UsageError("run `gxui login` through the gxui client")


@verb("register", "session", "register")
def register(ctx, email: str, password: str = "", username: str = ""):
    """Register a new user and log in as them. Never on shared servers that allow one account."""
    ctx.register(email, password or None, username or None)
    return f"registered {email}"


@verb("preferences", "session", "navigate_to_user_preferences")
def preferences(ctx):
    """Open User Preferences from the masthead's user menu; list its cards, `id  title`.

    Which cards show depends on the server's config. Check one with
    `gxui component 'preferences.card(id=ID)' visible`.
    """
    ctx.navigate_to_user_preferences()
    cards = ctx.components.preferences.cards
    cards.wait_for_visible()
    lines = []
    for card in ctx.locators(cards):
        card_id = (card.get_attribute("id") or "").removeprefix("g-card-")
        title = ctx.page.locator(f"#g-card-title-{card_id}").inner_text().strip()
        lines.append(f"{card_id}  {title}")
    return "\n".join(lines)


@verb("preferences-new-datasets-private", "session", "user_preferences_set_new_datasets_private")
def preferences_new_datasets_private(ctx, off: bool = False):
    """Turn on (--off: off) Preferences > Set Dataset Permissions for New Histories > Make new datasets private.

    Only histories created afterwards are affected.
    """
    ctx.user_preferences_set_new_datasets_private(not off)
    return f"new histories' datasets are {'not ' if off else ''}private"


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


@verb("collection-tag", "history", "history_panel_add_tags")
def collection_tag(ctx, hid: int, *tags: str):
    """Add tags to collection HID from its panel view (pencil > Add Tags > Save); prints its tags."""
    ctx.home()
    ctx.history_panel_wait_for_hid_ok(hid)
    view = ctx.history_panel_expand_collection(hid)
    try:
        ctx.history_panel_add_tags(list(tags))
    finally:
        view.back_to_history.wait_for_and_click()
    return "tags " + " ".join(ctx.history_panel_item_get_tags(hid))


@verb("dataset-tag", "history", "history_panel_item_add_tags")
def dataset_tag(ctx, hid: int, *tags: str):
    """Add tags to item HID (expand it > Add Tags > type, Enter); prints its tags once saved."""
    ctx.home()
    ctx.history_panel_wait_for_hid_ok(hid)
    ctx.history_panel_item_add_tags(hid, list(tags))
    expected = {t.replace("name:", "#", 1) for t in tags}
    ctx._wait_on(
        lambda: expected <= set(ctx.history_panel_item_get_tags(hid)),
        f"hid {hid} to show tags {sorted(expected)}",
    )
    return "tags " + " ".join(ctx.history_panel_item_get_tags(hid))


def _hda(ctx, hid: int) -> dict:
    item = next((i for i in ctx.history_contents(datasets_only=True) if i["hid"] == hid), None)
    if not item or item.get("history_content_type") != "dataset":
        raise UsageError(f"hid {hid} is not a dataset in the current history")
    return ctx.api_get(f"histories/{ctx.current_history_id()}/contents/datasets/{item['id']}")


@verb("dataset-change-datatype", "history", "edit_dataset_datatype")
def dataset_change_datatype(ctx, hid: int, datatype: str):
    """Set dataset HID's datatype (pencil > Datatypes > New Type > Save); waits for it."""
    ctx.home()
    ctx.history_panel_wait_for_hid_ok(hid)
    ctx.history_panel_item_edit(hid)
    ctx.edit_dataset_datatype(datatype)
    ctx._wait_on(lambda: _hda(ctx, hid)["extension"] == datatype, f"hid {hid} to be {datatype}")
    ctx.history_panel_wait_for_hid_ok(hid)
    return f"hid {hid} is {datatype}"


@verb("dataset-convert", "history", "edit_dataset_convert")
def dataset_convert(ctx, hid: int, datatype: str, timeout: float = 240.0):
    """Convert dataset HID to DATATYPE (pencil > Datatypes > Target datatype > Create Dataset); waits for the new item."""
    ctx.home()
    ctx.history_panel_wait_for_hid_ok(hid)
    before = {item["hid"] for item in ctx.history_contents(datasets_only=True)}
    ctx.history_panel_item_edit(hid)
    ctx.edit_dataset_convert(datatype)
    deadline = time.time() + timeout
    new: list[int] = []

    def appeared():
        new[:] = sorted({item["hid"] for item in ctx.history_contents(datasets_only=True)} - before)
        return bool(new)

    ctx._wait_on(appeared, f"a {datatype} conversion of hid {hid} to appear")
    _history_wait(ctx, new[-1], deadline)
    return f"hid {new[-1]} is hid {hid} as {_hda(ctx, new[-1])['extension']}"


@verb("dataset-change-dbkey", "history", "edit_dataset_dbkey")
def dataset_change_dbkey(ctx, hid: int, dbkey: str):
    """Set dataset HID's Database/Build to DBKEY, e.g. hg19 (expand it > database link > Save); waits for it."""
    labels = {key: label for label, key in ctx.api_get("genomes")}
    if dbkey not in labels:
        raise UsageError(f"no build {dbkey!r} on this server")
    ctx.home()
    ctx.history_panel_wait_for_hid_ok(hid)
    ctx.history_panel_ensure_showing_item_details(hid).dbkey.wait_for_and_click()
    ctx.components.edit_dataset_attributes._.wait_for_visible()
    ctx.edit_dataset_dbkey(labels[dbkey])
    ctx._wait_on(lambda: _hda(ctx, hid)["genome_build"] == dbkey, f"hid {hid}'s build to be {dbkey}")
    ctx.history_panel_wait_for_hid_ok(hid)
    # the panel picks the change up on its next poll
    ctx._wait_on(
        lambda: ctx.history_panel_item_component(hid=hid).dbkey.wait_for_text() == dbkey,
        f"hid {hid} to show build {dbkey}",
    )
    return f"hid {hid} build {dbkey}"


@verb("dataset-detect-datatype", "history", "edit_dataset_auto_detect_datatype")
def dataset_detect_datatype(ctx, hid: int, timeout: float = 120.0):
    """Re-detect dataset HID's datatype (pencil > Datatypes > Auto-detect); waits for it, prints the result."""
    ctx.home()
    ctx.history_panel_wait_for_hid_ok(hid)
    before = _hda(ctx, hid)["update_time"]
    ctx.history_panel_item_edit(hid)
    ctx.edit_dataset_auto_detect_datatype()
    # the success alert can clear before it is seen, so wait on the dataset itself
    ctx._wait_on(lambda: _hda(ctx, hid)["update_time"] != before, f"hid {hid} to be re-detected", timeout)
    _history_wait(ctx, hid, time.time() + timeout)
    return f"hid {hid} is {_hda(ctx, hid)['extension']}"


@verb("dataset-attributes", "history", "edit_dataset_attribute_fields")
def dataset_attributes(ctx, hid: int):
    """Open dataset HID's Attributes tab (pencil); print each field: name, label, shown value."""
    ctx.home()
    ctx.history_panel_wait_for_hid_visible(hid)
    ctx.history_panel_item_edit(hid)
    return "\n".join(f"{name}  {label!r} = {value!r}" for name, label, value in ctx.edit_dataset_attribute_fields())


@verb("dataset-set-metadata", "history", "edit_dataset_set_metadata_select")
def dataset_set_metadata(ctx, hid: int, name: str, value: str):
    """Pick VALUE in select field NAME on dataset HID's Attributes tab (e.g. chromCol 2) and Save; waits for it.

    NAME is a path `dataset-attributes` prints.
    """
    ctx.home()
    ctx.history_panel_wait_for_hid_ok(hid)
    ctx.history_panel_item_edit(hid)
    ctx.edit_dataset_set_metadata_select(name, value)
    attributes = ctx.components.edit_dataset_attributes
    attributes.save_button.wait_for_and_click()
    attributes.alert.wait_for_visible()
    ctx._wait_on(
        lambda: str(_hda(ctx, hid).get(f"metadata_{name}")) == value, f"hid {hid} metadata {name} to be {value}"
    )
    return f"hid {hid} {name} = {value}"


@verb("dataset-permissions", "history", "edit_dataset_permission_roles")
def dataset_permissions(ctx, hid: int):
    """Open dataset HID's Permissions tab (pencil > Permissions); print its manage and access roles.

    No access role means anyone with a link can see it; the owner's private role alone means only them.
    """
    ctx.home()
    ctx.history_panel_wait_for_hid_visible(hid)
    ctx.history_panel_item_edit(hid)
    roles = ctx.edit_dataset_permission_roles()
    return "\n".join(f"{key}: {', '.join(names) or '(none)'}" for key, names in roles.items())


@verb("dataset-delete", "history", "history_panel_item_delete")
def dataset_delete(ctx, hid: int):
    """Delete item HID with its trash button; waits for it. `dataset-undelete` restores it."""
    ctx.home()
    ctx.history_panel_wait_for_hid_visible(hid)
    ctx.history_panel_item_delete(hid)
    ctx._wait_on(lambda: _item(ctx, hid)["deleted"], f"hid {hid} to be deleted")
    return f"hid {hid} deleted"


@verb("dataset-undelete", "history", "history_panel_item_undelete")
def dataset_undelete(ctx, hid: int):
    """Undelete item HID (Include deleted, the history's trash counter > the item's Undelete); waits for it."""
    item = _item(ctx, hid)
    if item.get("purged"):
        raise UsageError(f"hid {hid} is purged; it cannot be undeleted")
    if not item["deleted"]:
        return f"hid {hid} is not deleted"
    ctx.home()
    ctx.history_panel_include_deleted()
    ctx.history_panel_item_undelete(hid)
    ctx._wait_on(lambda: not _item(ctx, hid)["deleted"], f"hid {hid} to be undeleted")
    return f"hid {hid} undeleted"


@verb("dataset-unhide", "history", "history_panel_item_unhide")
def dataset_unhide(ctx, hid: int):
    """Unhide item HID (Include hidden, the history's hidden counter > the item's Unhide); waits for it."""
    if _item(ctx, hid)["visible"]:
        return f"hid {hid} is not hidden"
    ctx.home()
    ctx.history_panel_include_hidden()
    ctx.history_panel_item_unhide(hid)
    ctx._wait_on(lambda: _item(ctx, hid)["visible"], f"hid {hid} to be unhidden")
    return f"hid {hid} unhidden"


@verb("dataset-rename", "history", "components.edit_dataset_attributes.save_button")
def dataset_rename(ctx, hid: int, name: str):
    """Rename dataset HID (pencil > Name > Save); waits for it."""
    ctx.home()
    ctx.history_panel_wait_for_hid_ok(hid)
    ctx.history_panel_item_edit(hid)
    attributes = ctx.components.edit_dataset_attributes
    attributes.name_input.wait_for_and_clear_and_send_keys(name)
    attributes.save_button.wait_for_and_click()
    ctx._wait_on(lambda: _item(ctx, hid)["name"] == name, f"hid {hid} to be named {name!r}")
    return f"hid {hid} is {name!r}"


def _item(ctx, hid: int) -> dict:
    item = next((i for i in ctx.history_contents(datasets_only=True) if i["hid"] == hid), None)
    if not item:
        raise UsageError(f"no hid {hid} in the current history")
    return item


@verb("collection-rename", "history", "history_panel_collection_rename")
def collection_rename(ctx, hid: int, name: str):
    """Rename collection HID from its panel view (click the name, type, Enter); prints the new name."""
    ctx.home()
    ctx.history_panel_wait_for_hid_ok(hid)
    view = ctx.history_panel_expand_collection(hid)
    try:
        ctx.history_panel_collection_rename(hid, name)
        ctx._wait_on(
            lambda: ctx.history_panel_collection_name_element().text == name,
            f"hid {hid} to be named {name!r}",
        )
    finally:
        view.back_to_history.wait_for_and_click()
    item = next(i for i in ctx.history_contents(datasets_only=True) if i["hid"] == hid)
    return f"hid {hid} named {item['name']!r}"


@verb("history-change-datatype", "history", "history_panel_change_datatype_of_selected")
def history_change_datatype(ctx, datatype: str, *hids: int):
    """Select HIDs (Select Items) and set their data type from the Selection menu; waits for it.

    The menu only offers Change data type when the server runs Celery.
    """
    if not hids:
        raise ValueError("give the hids to change")
    for hid in hids:
        _history_wait(ctx, hid, time.time() + 240)
    _select_items(ctx, hids)
    ctx.history_panel_change_datatype_of_selected(datatype)
    deadline = time.time() + 120
    while True:
        extensions = {item["hid"]: item.get("extension") for item in ctx.history_contents(datasets_only=True)}
        pending = [hid for hid in hids if extensions.get(hid) != datatype]
        if not pending:
            return f"hids {' '.join(map(str, hids))} are {datatype}"
        if time.time() > deadline:
            raise RuntimeError(f"hids {pending} still not {datatype} after 120s")
        time.sleep(1)


@verb("history-delete", "history", "history_panel_delete_selected")
def history_delete(ctx, *hids: int, purge: bool = False):
    """Select HIDs (Select Items) and Delete them from the Selection menu, confirming; waits for it.

    --purge picks Delete (permanently) instead; purged items cannot be undeleted. Already-deleted HIDs
    are shown with the `deleted:any` filter first.
    """
    if not hids:
        raise ValueError("give the hids to delete")
    ctx.home()
    if any(_item(ctx, hid)["deleted"] for hid in hids):
        ctx.history_panel_filter("deleted:any")
    _select_items(ctx, hids)
    ctx.history_panel_delete_selected(purge=purge)
    key = "purged" if purge else "deleted"
    ctx._wait_on(lambda: all(_item(ctx, hid)[key] for hid in hids), f"hids {list(hids)} to be {key}")
    return f"hids {' '.join(map(str, hids))} {key}"


@verb("history-undelete", "history", "history_panel_undelete_selected")
def history_undelete(ctx, *hids: int):
    """Filter the history by `deleted:true`, select HIDs (Select Items) and Undelete them from the Selection menu, confirming; waits for it."""
    if not hids:
        raise ValueError("give the hids to undelete")
    purged = [hid for hid in hids if _item(ctx, hid).get("purged")]
    if purged:
        raise UsageError(f"hids {purged} are purged; they cannot be undeleted")
    ctx.home()
    ctx.history_panel_filter("deleted:true")
    _select_items(ctx, hids)
    ctx.history_panel_undelete_selected()
    ctx._wait_on(lambda: not any(_item(ctx, hid)["deleted"] for hid in hids), f"hids {list(hids)} to be undeleted")
    return f"hids {' '.join(map(str, hids))} undeleted"


@verb("history-filter", "history", "history_panel_filter")
def history_filter(ctx, text: str):
    """Type TEXT (e.g. `deleted:true`, `visible:hidden`) into the history's search box; print the hids it shows.

    Verbs that start from `home` clear the filter again.
    """
    ctx.home()
    ctx.history_panel_filter(text)
    time.sleep(2)  # the search box applies its text after a 1s pause
    hids = [item.get_attribute("data-hid") for item in ctx.locators(ctx.components.history_panel.contents)]
    return f"filter {ctx.history_panel_filter_text()!r}; shown hids {' '.join(hids) or '(none)'}"


@verb("history-hide", "history", "history_panel_hide_selected")
def history_hide(ctx, *hids: int, unhide: bool = False):
    """Select HIDs (Select Items) and Hide them from the Selection menu, confirming; waits for it.

    --unhide shows hidden items again (Include hidden, the history's hidden counter, first).
    """
    if not hids:
        raise ValueError("give the hids to hide")
    ctx.home()
    if unhide:
        ctx.history_panel_include_hidden()
    _select_items(ctx, hids)
    ctx.history_panel_hide_selected(unhide=unhide)
    ctx._wait_on(lambda: all(_item(ctx, hid)["visible"] == unhide for hid in hids), f"hids {list(hids)} to change")
    return f"hids {' '.join(map(str, hids))} {'unhidden' if unhide else 'hidden'}"


def _select_items(ctx, hids) -> None:
    first = ctx.history_panel_item_selector(hids[0], wait=True)
    if not ctx.selector_is_displayed(f"{first} .selector"):
        ctx.history_panel_multi_operations_show()
    for hid in hids:
        ctx.history_panel_multi_operation_select_hid(hid)


def _collection_extensions(ctx, hid: int) -> set[str]:
    item = next((i for i in ctx.history_contents(datasets_only=True) if i["hid"] == hid), None)
    if not item or item.get("history_content_type") != "dataset_collection":
        raise UsageError(f"hid {hid} is not a collection in the current history")
    path = f"histories/{ctx.current_history_id()}/contents/dataset_collections/{item['id']}"
    return {e["object"].get("file_ext") for e in ctx.api_get(path)["elements"]}


@verb("collection-change-datatype", "history", "collection_edit_change_datatype")
def collection_change_datatype(ctx, hid: int, datatype: str):
    """Set every element of collection HID to DATATYPE (pencil > Datatypes > Save); waits for it.

    The Datatypes tab only shows when the server runs Celery.
    """
    ctx.home()
    ctx.history_panel_wait_for_hid_ok(hid)
    current = _collection_extensions(ctx, hid)
    if len(current) != 1:
        raise UsageError(f"hid {hid}'s elements have several datatypes: {sorted(current)}")
    ctx.history_panel_collection_edit(hid)
    ctx.collection_edit_change_datatype(current.pop(), datatype)
    ctx._wait_on(
        lambda: _collection_extensions(ctx, hid) == {datatype},
        f"hid {hid}'s elements to be {datatype}",
        wait_type=ctx.wait_types.JOB_COMPLETION,
    )
    return f"hid {hid} elements are {datatype}"


@verb("collection-convert", "history", "collection_edit_convert")
def collection_convert(ctx, hid: int, converter: str, timeout: float = 240.0):
    """Convert collection HID with the converter tool named CONVERTER (pencil > Convert); prints the new hid.

    The Convert tab only shows when a converter exists for the elements' datatype. Waits for the
    new collection's jobs.
    """
    ctx.home()
    ctx.history_panel_wait_for_hid_ok(hid)
    before = max((i["hid"] for i in ctx.history_contents(datasets_only=True)), default=0)
    ctx.history_panel_collection_edit(hid)
    ctx.collection_edit_convert(converter)
    new = ctx.history_wait_for_new_collection(before)
    ctx.home()
    status = _history_wait(ctx, new["hid"], time.time() + timeout)
    return f"converted to {new['name']!r}: {status}"


@verb("history-references", "history", "click_history_option_tool_references")
def history_references(ctx, bibtex: bool = False):
    """History options > Export Tool References; print one line per reference (APA, or --bibtex)."""
    ctx.home()
    ctx.click_history_option_tool_references()
    citations = ctx.components.citations
    if bibtex:
        citations.bibtex_tab.wait_for_and_click()
        ctx._wait_on(lambda: citations._.reference.wait_for_text().lstrip().startswith("@"), "BibTeX references")
    texts = [" ".join(reference.text.split()) for reference in citations._.reference.all()]
    return "\n".join(_bounded(text, 300) for text in texts)


@verb("history-items", "history", "history_contents")
def history_items(ctx, deleted: bool = False):
    """List the current history: one line per item, `hid state extension name`; --deleted adds deleted items.

    An observation verb: it reads what the history panel shows (via Galaxy's API, so it is compact
    and exact) and changes nothing. Allowed under UI-only rules.
    """
    lines = []
    history = ctx.current_history()
    for item in ctx.history_contents(datasets_only=True):
        if item.get("deleted") and not deleted:
            continue
        kind = item.get("extension") or item.get("collection_type") or item.get("history_content_type")
        flags = [] if item.get("visible", True) else ["hidden"]
        flags += [flag for flag in ("deleted", "purged") if item.get(flag)]
        marks = f"  ({', '.join(flags)})" if flags else ""
        lines.append(
            f"{item['hid']:>4} {item.get('state') or item.get('populated_state', '?'):<9} {kind:<10} {item['name']}{marks}"
        )
    header = f"history {history['id']} {history['name']!r} ({len(lines)} items)"
    return "\n".join([header, *lines])


@verb("history-make-private", "history", "make_history_private")
def history_make_private(ctx):
    """History options > Share & Manage Access > Make Private > Make History Private; waits for it.

    Makes the history's datasets and its new datasets private to you, and stops sharing it.
    """
    ctx.home()
    ctx.make_history_private()
    ctx.components.toast.message_with_text(text="Successfully made history private").wait_for_visible()
    return f"history {ctx.current_history_id()} is private"


@verb("history-resume-paused", "history", "click_history_option_resume_paused_jobs")
def history_resume_paused(ctx):
    """History options > Resume Paused Jobs; prints Galaxy's message.

    Fix the paused jobs' inputs first, or they pause again.
    """
    ctx.home()
    ctx.click_history_option_resume_paused_jobs()
    return ctx.components.toast.message.wait_for_text()


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


@verb("history-switch", "history", "history_panel_switch_to")
def history_switch(ctx, history: str):
    """Make HISTORY (a name or id) current from the history panel's Switch to history modal."""
    history_id = _history_id(ctx, history)
    if history_id == ctx.current_history_id():
        return f"history {history_id} is already current"
    ctx.home()
    ctx.history_panel_switch_to(history_id)
    return f"current history is now {history_id} {ctx.current_history()['name']!r}"


@verb("history-import", "history", "history_view_import")
def history_import(ctx, history: str, name: str = ""):
    """Open HISTORY (a shared link, or another user's history id) and import it with Import this history >
    Copy History, optionally as --name NAME; prints the imported history, now current."""
    before = ctx.current_history_id()
    if "/" in history:
        ctx.navigate_to(history)
    else:
        ctx.navigate_to_history_view(history)
    ctx.history_view_import(new_name=name or None)
    ctx._wait_on(
        lambda: ctx.current_history_id() != before,
        "the imported history to become current",
        wait_type=ctx.wait_types.DATABASE_OPERATION,
    )
    return f"imported as {ctx.current_history_id()} {ctx.current_history()['name']!r}"


@verb("history-archive", "history", "history_panel_archive")
def history_archive(ctx):
    """Archive the current history from History options > Archive History; prints the history now current."""
    history_id = ctx.current_history_id()
    ctx.home()
    ctx.history_panel_archive()
    ctx._wait_on(lambda: ctx.api_get(f"histories/{history_id}")["archived"], f"history {history_id} to be archived")
    return f"archived {history_id}; current history is {ctx.current_history_id()} {ctx.current_history()['name']!r}"


@verb("history-multiview", "history", "open_history_multi_view")
def history_multiview(ctx):
    """History options > Show Histories Side-by-Side; one line per shown history column id."""
    ctx.home()
    ctx.open_history_multi_view()
    ctx.components.multi_history_panel.histories.wait_for_visible()
    columns = ctx.find_elements_by_selector(".multi-history-panel .history-column[data-history-id]")
    return "\n".join(c.get_attribute("data-history-id") for c in columns)


@verb("histories-archived", "history", "navigate_to_archived_histories")
def histories_archived(ctx):
    """Open Histories > Archived Histories; one line per history name."""
    ctx.navigate_to_archived_histories()
    names = ctx.get_history_titles(len(ctx.components.histories.history_cards.all()))
    return "\n".join(names) or "no archived histories"


@verb("histories-purge-all", "history", "histories_purge_all")
def histories_purge_all(ctx):
    """Histories > Select all > Purge (N) > Purge histories; prints how many were purged."""
    ids = [h["id"] for h in ctx.api_get("histories?keys=id")]
    ctx.navigate_to_histories_page()
    ctx.histories_purge_all()
    ctx._wait_on(
        lambda: all(ctx.api_get(f"histories/{history_id}")["purged"] for history_id in ids),
        "the histories to be purged",
        wait_type=ctx.wait_types.DATABASE_OPERATION,
    )
    return f"purged {len(ids)} histories; current history is {ctx.current_history_id()}"


@verb("histories-delete", "history", "components.confirm_dialog.ok_button")
def histories_delete(ctx, history: str):
    """Histories > More options > Delete on HISTORY's card (a name or id), then confirm."""
    history_id = _history_id(ctx, history)
    name = ctx.api_get(f"histories/{history_id}")["name"]
    ctx.navigate_to_histories_page()
    ctx.select_history_card_operation(name, '[id^="g-card-action-delete-history-"]', True)
    ctx.components.confirm_dialog.ok_button.wait_for_and_click()
    ctx._wait_on(
        lambda: ctx.api_get(f"histories/{history_id}")["deleted"],
        "the history to be deleted",
        wait_type=ctx.wait_types.DATABASE_OPERATION,
    )
    return f"deleted history {history_id} {name!r}"


@verb("histories-restore", "history", "check_advanced_search_filter")
def histories_restore(ctx, history: str):
    """Histories > Advanced search > Deleted > Restore on HISTORY's card (a name or id)."""
    histories = ctx.api_get("histories?deleted=true&keys=id,name")
    matches = [h for h in histories if history in (h["id"], h["name"])]
    if len(matches) != 1:
        raise UsageError(f"{len(matches)} deleted histories match {history!r}")
    history_id, name = matches[0]["id"], matches[0]["name"]
    ctx.navigate_to_histories_page()
    ctx.components.histories.advanced_search_toggle.wait_for_and_click()
    ctx.check_advanced_search_filter("deleted")
    ctx.sleep_for(ctx.wait_types.UX_RENDER)
    ctx.select_history_card_operation(name, '[id^="g-card-action-restore-history-"]')
    ctx._wait_on(
        lambda: not ctx.api_get(f"histories/{history_id}")["deleted"],
        "the history to be restored",
        wait_type=ctx.wait_types.DATABASE_OPERATION,
    )
    return f"restored history {history_id} {name!r}"


@verb("history-export", "history", "click_history_option_export_to_file")
def history_export(ctx, format: str = "tar.gz"):
    """History options > Export History to File as --format tar.gz (default) or rocrate.zip, to Temporary
    Direct Download; waits until the Download button shows."""
    if format not in ("tar.gz", "rocrate.zip"):
        raise UsageError("--format is tar.gz or rocrate.zip")
    ctx.home()
    ctx.click_history_option_export_to_file()
    export = ctx.components.history_export_tasks
    export.select_format(format=format).wait_for_and_click()
    export.next_button.wait_for_and_click()
    export.select_destination(destination="download").wait_for_and_click()
    export.next_button.wait_for_and_click()
    export.export_button.wait_for_and_click()
    record = ctx.components.last_export_record
    record.download_btn.wait_for_visible(wait_type=ctx.wait_types.DATABASE_OPERATION)
    return f"{format} export of {ctx.current_history_id()} ready to download"


@verb("history-copy-datasets", "history", "history_panel_click_copy_elements")
def history_copy_datasets(ctx, *hids: int, new_history: str = ""):
    """Copy dataset HIDs of the current history with History options > Copy Datasets into a --new-history NAME; prints its id."""
    if not hids or not new_history:
        raise UsageError("give the hids to copy and --new-history NAME")
    ctx.home()
    ctx.history_panel_click_copy_elements()
    copy = ctx.components.history_copy_elements
    for hid in hids:
        copy.dataset_checkbox(id=_item(ctx, hid)["id"]).wait_for_and_click()
    copy.new_history_name.wait_for_and_click().send_keys(new_history)
    copy.copy_button.wait_for_and_click()
    copy.new_history_link.wait_for_visible()
    return f"copied hids {' '.join(map(str, hids))} to {_history_id(ctx, new_history)} {new_history!r}"


# "failed" is a collection's populated_state, e.g. an upload with a dead URL
TERMINAL_BAD_STATES = {"error", "failed_metadata", "paused", "discarded", "deferred", "failed"}


def _hid_state(ctx, hid: int) -> str:
    for item in ctx.history_contents(datasets_only=True):
        if item["hid"] == hid:
            return item.get("state") or item.get("populated_state") or "?"
    return "absent"


@verb("history-wait", "history", "history_panel_wait_for_hid_ok", positional=("hid",))
def history_wait(ctx, hid: int = 0, timeout: float = 240.0):
    """Wait until history item HID is ok, for up to TIMEOUT seconds. Fails at once on error states.

    No HID: wait until no dataset in the current history is still busy, hidden ones too (such as a
    converter's outputs). Repeats Galaxy's job-completion wait (sized for test servers) until the
    deadline, so long jobs on public servers are fine. On timeout it reports the current state.
    """
    if not hid:
        return _history_wait_all(ctx, time.time() + timeout)
    return _history_wait(ctx, hid, time.time() + timeout)


BUSY_STATES = {"new", "upload", "queued", "running", "setting_metadata"}


def _history_wait_all(ctx, deadline: float) -> str:
    path = f"histories/{ctx.current_history_id()}?keys=state_details"
    while True:
        counts = {state: n for state, n in (ctx.api_get(path).get("state_details") or {}).items() if n}
        bad = {state: n for state, n in counts.items() if state in TERMINAL_BAD_STATES}
        if bad:
            raise RuntimeError(f"history datasets: {counts}")
        if not BUSY_STATES & set(counts):
            return f"history ok: {counts}"
        if time.time() >= deadline:
            raise TimeoutError(f"history datasets still {counts}; run history-wait again")
        time.sleep(min(3, max(deadline - time.time(), 0)))


# One history_panel_wait_for_hid_ok can take this long (a visible wait, then a job-completion wait
# per refresh); nearer the deadline than this, poll the item's state instead.
FRAMEWORK_WAIT = 100


def _history_wait(ctx, hid: int, deadline: float) -> str:
    start = time.time()
    while True:
        if deadline - time.time() > FRAMEWORK_WAIT:
            try:
                ctx.history_panel_wait_for_hid_ok(hid, allowed_force_refreshes=1)
                return _wait_for_collection_jobs(ctx, hid, deadline)
            except Exception as e:
                if "Timeout" not in type(e).__name__ and "timeout" not in str(e).lower():
                    raise
        state = _hid_state(ctx, hid)
        if state == "ok":
            return _wait_for_collection_jobs(ctx, hid, deadline)
        if state in TERMINAL_BAD_STATES:
            raise RuntimeError(f"hid {hid} is {state}") from None
        if time.time() >= deadline:
            raise TimeoutError(
                f"hid {hid} still {state} after {time.time() - start:.0f}s; run history-wait again"
            ) from None
        if deadline - time.time() <= FRAMEWORK_WAIT:
            time.sleep(min(5, max(deadline - time.time(), 0)))


def _wait_for_collection_jobs(ctx, hid: int, deadline: float) -> str:
    """A collection shows ok once populated, before the jobs making its elements finish; wait for those too."""
    item: dict[str, Any] = next((i for i in ctx.history_contents(datasets_only=True) if i["hid"] == hid), {})
    if item.get("history_content_type") != "dataset_collection":
        return f"hid {hid} ok"
    path = f"histories/{ctx.current_history_id()}/contents/dataset_collections/{item['id']}"
    while True:
        jobs = {k: v for k, v in (ctx.api_get(path).get("job_state_summary") or {}).items() if v and k != "all_jobs"}
        bad = {state: n for state, n in jobs.items() if state in ("error", "failed", "paused", "deleted")}
        if bad:
            raise RuntimeError(f"collection hid {hid}: jobs {jobs}")
        if set(jobs) <= {"ok", "skipped"}:
            count = item.get("element_count")
            return f"hid {hid} ok" + (f" ({count} elements, their jobs done)" if count is not None else "")
        if time.time() >= deadline:
            raise TimeoutError(f"collection hid {hid} jobs {jobs}; run history-wait again")
        time.sleep(min(5, max(deadline - time.time(), 0)))


COLLECTION_BUILDERS = {"list": "history_panel_build_list_auto", "list:paired": "history_panel_build_list_of_pairs"}


def _renames(rename: str) -> dict[str, str]:
    pairs = [p.split("=", 1) for p in rename.split(",") if p]
    if any(len(p) != 2 or not all(p) for p in pairs):
        raise UsageError(f"--rename takes OLD=NEW pairs, comma-separated: {rename!r}")
    return dict(pairs)


def _rename_identifiers(ctx, renames: dict[str, str]) -> None:
    """Rename rows of the builder's grid by their current List Identifier."""
    wizard = ctx.components.collection_builders.list_wizard
    found = {}
    row = 2  # aria-rowindex 1 is the header
    wizard.cell(row_index=row, column_identifier="identifier").wait_for_visible()
    while not (cell := wizard.cell(row_index=row, column_identifier="identifier")).is_absent:
        found[cell.wait_for_text()] = row
        row += 1
    missing = set(renames) - set(found)
    if missing:
        raise UsageError(f"no identifiers {sorted(missing)} in the builder: {sorted(found)}")
    for old, new in renames.items():
        row = found[old]
        wizard.cell(row_index=row, column_identifier="identifier").wait_for_and_double_click()
        field = wizard.cell_input(row_index=row, column_identifier="identifier").wait_for_present()
        ctx.aggressive_clear(field)
        field.send_keys(new)
        ctx.send_enter(field)


def _rename_list_elements(ctx, hids: list[int], renames: dict[str, str]) -> None:
    """Rename flat list builder elements by their current (guessed) name."""
    wizard = ctx.components.collection_builders.list_wizard
    found = {wizard.element_name(hid=hid).wait_for_text(): hid for hid in hids}
    missing = set(renames) - set(found)
    if missing:
        raise UsageError(f"no elements {sorted(missing)} in the builder: {sorted(found)}")
    for old, new in renames.items():
        ctx.collection_builder_rename_element(found[old], new)


@verb("collection-build", "history", "history_panel_build_list_auto")
def collection_build(
    ctx,
    kind: str,
    hids: str,
    name: str = "",
    keep_originals: bool = False,
    keep_extensions: bool = False,
    rename: str = "",
    advanced: bool = False,
):
    """Build a collection from history items: KIND list or list:paired, HIDS comma-separated.

    Selects the items, runs Galaxy's builder (list:paired pairs by name, _1/_2), names it, creates
    it and waits for it. --keep-originals leaves the items visible (the builder hides them);
    --keep-extensions keeps file extensions in element identifiers (the builder strips them);
    --rename OLD=NEW,... edits guessed element identifiers before building; --advanced builds a
    list through Advanced Build List > Flat List (list:paired always goes that way).
    """
    if kind not in COLLECTION_BUILDERS:
        raise UsageError(f"KIND is one of {', '.join(COLLECTION_BUILDERS)}")
    renames = _renames(rename)
    before = max((i["hid"] for i in ctx.history_contents(datasets_only=True)), default=0)
    ctx.home()
    selected = _int_list(hids)
    ctx.history_panel_wait_for_and_select(selected)
    if advanced and kind == "list":
        ctx.history_panel_build_list_advanced_and_select_builder("list")
    else:
        getattr(ctx, COLLECTION_BUILDERS[kind])()
    if keep_originals:
        ctx.collection_builder_hide_originals()
    if keep_extensions:
        ctx.collection_builder_toggle_remove_extensions()
    if renames and kind == "list:paired":
        _rename_identifiers(ctx, renames)
    elif renames:
        _rename_list_elements(ctx, selected, renames)
    if name:
        ctx.collection_builder_set_name(name)
    ctx.collection_builder_create()
    created: list[dict] = []

    def appeared():
        created[:] = [
            i
            for i in ctx.history_contents(datasets_only=True)
            if i["hid"] > before and i.get("history_content_type") == "dataset_collection"
        ]
        return bool(created)

    ctx._wait_on(appeared, "the new collection", wait_type=ctx.wait_types.DATABASE_OPERATION)
    collection = created[-1]
    return f"built {collection.get('collection_type', kind)} {collection['name']!r} hid {collection['hid']}"


# --- upload ----------------------------------------------------------------


def _upload(ctx, method: str, stage, timeout: float) -> str:
    deadline = time.time() + timeout
    uploader = ctx.upload_context(method)
    stage(uploader)
    # Not start_and_wait_for_uploaded_hids: its per-item wait is sized for test servers and a slow
    # fetch from Zenodo outlives it, so wait with history-wait's deadline instead.
    hids = uploader.start_for_uploaded_hids()
    _wait_for_hids_to_appear(ctx, hids, min(time.time() + 60, deadline))
    for hid in hids:
        _history_wait(ctx, hid, deadline)
    return "ok hids " + " ".join(str(h) for h in hids)


UPLOAD_FAILED = re.compile(r"upload request failed|upload failed", re.IGNORECASE)


def _wait_for_hids_to_appear(ctx, hids: list[int], deadline: float) -> None:
    """An upload whose request failed (a rate-limited server, say) never makes its items; say so."""
    start = time.time()
    while True:
        present = {item["hid"] for item in ctx.history_contents(datasets_only=True)}
        if set(hids) <= present:
            return
        failure = ctx.page.get_by_text(UPLOAD_FAILED)
        if failure.count() and failure.first.is_visible():
            raise RuntimeError(
                f"the upload failed: {failure.first.inner_text().strip()!r}; nothing was added - upload again"
            )
        # The server's own message (e.g. "Action requires account activation.") replaces that text.
        # Rows are newest first and earlier uploads' rows stay, so only check this upload's.
        for row in range(1, len(hids) + 1):
            error = ctx.components.upload_activity.progress_row_error(row=row)
            if not error.is_absent and error.is_displayed:
                raise RuntimeError(f"the upload failed: {error.wait_for_text()!r}; nothing was added")
        if time.time() >= deadline:
            raise TimeoutError(
                f"hids {sorted(set(hids) - present)} did not appear within {time.time() - start:.0f}s; "
                "`gxui screenshot`"
            )
        time.sleep(min(3, max(deadline - time.time(), 0)))


@verb("upload-url", "upload", "upload_context('paste-links')")
def upload_url(
    ctx,
    *urls: str,
    ext: str = "",
    name: str = "",
    dbkey: str = "",
    collection: str = "",
    collection_type: str = "list",
    timeout: float = 240.0,
):
    """Upload one or more URLs (Import Data > Paste Links/URLs); waits until every new item is ok.

    --collection NAME uploads them into one new collection instead ("Create a collection from these
    files"); --collection-type is list or list:paired, which pairs the URLs in order.
    """
    if collection_type not in ("list", "list:paired"):
        raise UsageError(f"--collection-type is list or list:paired, not {collection_type!r}")
    metadata = {k: v for k, v in (("extension", ext), ("name", name), ("dbkey", dbkey)) if v}

    def stage(uploader):
        uploader.stage_paste_links([(u, metadata or None) for u in urls])
        if collection:
            (uploader.to_paired_list if collection_type == "list:paired" else uploader.to_list)(collection)

    return _upload(ctx, "paste-links", stage, timeout)


@verb("upload-paste", "upload", "upload_context('paste-content')")
def upload_paste(
    ctx,
    content: str,
    ext: str = "",
    name: str = "",
    dbkey: str = "",
    space_to_tab: bool = False,
    timeout: float = 240.0,
):
    """Upload pasted text as one dataset; waits until it is ok. --space-to-tab ticks the row's Spaces→Tabs."""
    metadata = {
        k: v for k, v in (("extension", ext), ("name", name), ("dbkey", dbkey), ("space_to_tab", space_to_tab)) if v
    }
    return _upload(ctx, "paste-content", lambda up: up.stage_paste_content(content, metadata or None), timeout)


@verb("upload-file", "upload", "upload_context('local-file')")
def upload_file(ctx, *paths: str, ext: str = "", name: str = "", timeout: float = 240.0):
    """Upload local files, picked in one file chooser selection; waits until each is ok.

    --name needs a single PATH; --ext applies to each.
    """
    if not paths:
        raise UsageError("name at least one file")
    if name and len(paths) > 1:
        raise UsageError("--name needs a single PATH")
    metadata = {k: v for k, v in (("extension", ext), ("name", name)) if v}
    full_paths = [os.path.abspath(os.path.expanduser(p)) for p in paths]
    return _upload(
        ctx, "local-file", lambda up: up.stage_local_files(full_paths, [metadata or None] * len(paths)), timeout
    )


@verb("upload-remote", "upload", "upload_context('remote-files')")
def upload_remote(ctx, source: str, *files: str, path: str = "", ext: str = "", timeout: float = 240.0):
    """Upload FILES from remote file source SOURCE (Import Data > Choose Remote Files, tick, Add Selected); waits for each.

    SOURCE and FILES are the labels the browser shows, e.g. `upload-remote "Galaxy test data" 1.bed 2.bed`.
    --path opens folders first, e.g. `--path species/Taeniopygia_guttata` (a GTN snippet's `location`).
    """
    if not files:
        raise UsageError("name at least one file")
    metadata: list = [{"extension": ext} if ext else None] * len(files)
    return _upload(
        ctx, "remote-files", lambda up: up.stage_remote_files(source, list(files), metadata, path=path), timeout
    )


@verb("upload-library", "upload", "upload_context('data-library')")
def upload_library(ctx, library: str, dataset: str, timeout: float = 240.0):
    """Import DATASET from data library LIBRARY (Import Data > Import from Data Library); waits until it is ok."""
    return _upload(ctx, "data-library", lambda up: up.stage_data_library_dataset(library, dataset), timeout)


@verb("library-new", "upload", "libraries_index_create")
def library_new(ctx, name: str):
    """Create data library NAME (Libraries > New Library); admins only."""
    ctx.libraries_open()
    ctx.libraries_index_create(name)
    return f"library {name!r} created"


@verb("library-import-dir", "upload", "populate_library_folder_from_import_dir")
def library_import_dir(ctx, library: str, *files: str):
    """Add FILES from the server's library_import_dir to LIBRARY (Datasets > from Import Directory); admins only.

    The datasets get the admin's default permissions: with "Make new datasets private" on, users can't see them.
    """
    if not files:
        raise UsageError("name at least one file")
    ctx.populate_library_folder_from_import_dir(library, list(files))
    ctx.libraries_folder_wait_for_datasets(files)
    return f"added {' '.join(files)} to {library!r}; their import jobs may still be running"


@verb("library-add-to-history", "upload", "libraries_folder_add_to_history")
def library_add_to_history(ctx, library: str, *datasets: str, history: str = ""):
    """Tick DATASETS in LIBRARY and Add to History > as Datasets > Import, into HISTORY (default: the current one).

    Galaxy makes that history current. Follow with `history-wait` or `history-items`.
    """
    if not datasets:
        raise UsageError("name at least one dataset")
    ctx.libraries_open_with_name(library)
    ctx.libraries_folder_add_to_history(list(datasets), history_name=history or None)
    return f"added {' '.join(datasets)} from {library!r}"


# --- dataset ---------------------------------------------------------------


@verb("dataset-peek", "dataset", "history_panel_click_item_title")
def dataset_peek(ctx, hid: int):
    """Expand a history item and print its peek (bounded); for an error item, its error text.

    Waits for the item's job like `history-wait HID`, but an error state is an answer, not a failure.
    """
    try:
        _history_wait(ctx, hid, time.time() + 240)
        failed = False
    except RuntimeError:
        state = _hid_state(ctx, hid)
        if state not in TERMINAL_BAD_STATES:
            raise
        ctx.history_panel_wait_for_hid_state(hid, state)
        failed = True
    item = ctx.history_panel_item_component(hid=hid)
    if item.details.is_absent:
        ctx.history_panel_click_item_title(hid=hid, wait=True)
    if failed:
        return f"hid {hid} is {state}: " + _bounded(item.info.wait_for_text())
    return _bounded(item.peek.wait_for_text())


@verb("dataset-copy-link", "dataset", "history_panel_item_copy_link")
def dataset_copy_link(ctx, hid: int):
    """Expand dataset HID and click its Copy Link button; print the copied download URL."""
    ctx.home()
    ctx.history_panel_wait_for_hid_ok(hid)
    if ctx.history_panel_item_component(hid=hid).details.is_absent:
        ctx.history_panel_click_item_title(hid=hid, wait=True)
    return ctx.history_panel_item_copy_link(hid)


@verb("dataset-related", "dataset", "history_panel_item_show_related")
def dataset_related(ctx, hid: int):
    """Click item HID's Show Related Items; print the panel's filter and the hids it shows. Run again to clear it."""
    ctx.history_panel_wait_for_hid_ok(hid)
    if ctx.history_panel_item_component(hid=hid).details.is_absent:
        ctx.history_panel_click_item_title(hid=hid, wait=True)
    expected = "" if ctx.history_panel_filter_text() == f"related:{hid}" else f"related:{hid}"
    ctx.history_panel_item_show_related(hid)
    ctx._wait_on(lambda: ctx.history_panel_filter_text() == expected, f"the history filter to become {expected!r}")
    ctx.history_panel_item_component(hid=hid).wait_for_visible()
    hids = [item.get_attribute("data-hid") for item in ctx.locators(ctx.components.history_panel.contents)]
    return f"filter {expected!r}; shown hids {' '.join(hids)}"


@verb("datasets-list", "dataset", "navigate_to_datasets_list")
def datasets_list(ctx, search: str = ""):
    """Open the Datasets list (Activity Bar > Datasets); one line per row, `extension name (history)`, latest update first.

    --search TEXT filters it by name.
    """
    ctx.navigate_to_datasets_list()
    if search:
        ctx.datasets_list_search(search)
        ctx._wait_on(
            lambda: all(search.lower() in row["name"].lower() for row in ctx.datasets_list_rows()),
            f"the list filtered by {search!r}",
        )
    rows = ctx.datasets_list_rows()
    return "\n".join(f"{row['extension'] or '-':<10} {row['name']}  ({row['history']})" for row in rows) or "(none)"


@verb("datasets-purge-deleted", "dataset", "storage_dashboard_purge_deleted_datasets")
def datasets_purge_deleted(ctx):
    """Purge deleted datasets (Storage Dashboard > Free up disk space > Deleted datasets); prints the space cleared.

    Selects all on the review dialog's first page only.
    """
    ctx.storage_dashboard_purge_deleted_datasets()
    return ctx.components.storage_dashboard.cleanup.success.wait_for_text()


@verb("dataset-error", "dataset", "history_panel_item_show_error")
def dataset_error(ctx, hid: int, report: str = ""):
    """Open error item HID's error page from its bug icon; print the tool, job messages and stderr (bounded).

    --report MESSAGE also submits the page's Issue Report form and prints Galaxy's reply. Reports need
    the server's error_email_to; without it the reply says reporting is disabled.
    """
    ctx.history_panel_item_show_error(hid)
    page = ctx.components.dataset_error
    lines = [f"tool: {page.tool_id.wait_for_text()}"]
    for label, component in (
        ("job messages", page.job_messages),
        ("tool stderr", page.tool_stderr),
        ("job stderr", page.job_stderr),
    ):
        if not component.is_absent:
            lines.append(f"{label}: {_bounded(component.wait_for_text(), 800)}")
    if report:
        lines.append(f"report: {ctx.submit_email_report(report)}")
    return "\n".join(lines)


@verb("collection-peek", "dataset", "history_panel_expand_collection", positional=("element",))
def collection_peek(ctx, hid: int, element: str = ""):
    """Open collection HID; list its elements (`index state name`), or print ELEMENT's peek (bounded).

    ELEMENT is an element name, or an index from that list. Returns to the history afterwards.
    """
    ctx.history_panel_wait_for_hid_ok(hid)
    view = ctx.history_panel_expand_collection(hid)
    try:
        view.list_items.wait_for_visible()
        elements: list[tuple] = []

        def loaded():
            # A just-built collection's elements render as "placeholder" until the panel polls.
            elements[:] = [
                (
                    item.get_attribute("data-hid"),
                    item.get_attribute("data-state"),
                    item.locator(".content-title").inner_text(),
                )
                for item in ctx.locators(view.list_items)
            ]
            return all(state != "placeholder" for _, state, _ in elements)

        ctx._wait_on(loaded, f"hid {hid}'s elements to load", wait_type=ctx.wait_types.HISTORY_POLL)
        if not element:
            return "\n".join(f"{index:>4} {state or '?':<9} {name}" for index, state, name in elements)
        index = next((index for index, _, name in elements if name == element), None)
        if index is None and element in {index for index, _, _ in elements}:
            index = element
        if index is None:
            raise UsageError(f"no element {element!r} in hid {hid}: {[name for _, _, name in elements]}")
        view.element_title(index=index).wait_for_and_click()
        return _bounded(view.element_peek(index=index).wait_for_text())
    finally:
        view.back_to_history.wait_for_and_click()


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


@verb("dataset-logs", "dataset", "show_dataset_details")
def dataset_logs(ctx, hid: int):
    """Open item HID's Dataset Details and print its job's tool stdout and stderr (bounded)."""
    ctx.show_dataset_details(hid)
    job_details = ctx.components.job_details
    lines = []
    for label, code in (("stdout", job_details.tool_stdout), ("stderr", job_details.tool_stderr)):
        lines.append(f"{label}: " + ("(empty)" if code.is_absent else _bounded(code.wait_for_text())))
    return "\n".join(lines)


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
    if _in_editor(ctx):
        step = _active_step(ctx)
        tool_id = _editor_tool_ids(ctx).get(step) if step else None
        if not tool_id:
            raise UsageError("no tool step open; run `gxui workflow-step STEP`, or pass TOOL_ID")
        return {"tool_id": tool_id}
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
    `tool-fill` takes the path. Read from the API, not the page: it doesn't show what `tool-fill` set.
    """
    if not tool_id and _in_editor(ctx) and _open_step_has_no_tool(ctx):
        return "\n".join(f"{path}  {title!r} = {value!r}" for path, title, value in _inspector_fields(ctx))
    form = {"tool_id": tool_id} if tool_id else _open_form(ctx)
    parameters = ctx.tool_form_parameters(**form)
    if _in_editor(ctx) and not tool_id:
        # A workflow step's data inputs are terminals: `workflow-connect` sets them. Values come from
        # the tool's defaults; the step's own are what its inspector shows.
        shown = {path: value for path, _, value in _inspector_fields(ctx)}
        parameters = [
            p._replace(value=shown[p.path]) if p.path in shown else p for p in parameters if p.type not in DATA_TYPES
        ]
    elif _in_editor(ctx):
        parameters = [p for p in parameters if p.type not in DATA_TYPES]
    return "\n".join(_describe_line(p) for p in parameters)


@verb("tool-accepted-formats", "tool", "tool_form_accepted_formats")
def tool_accepted_formats(ctx, parameter: str):
    """List the datatypes data field PARAMETER (a `tool-describe` path) accepts, from its accepted formats toggle."""
    return "\n".join(ctx.tool_form_accepted_formats(parameter))


DATA_TYPES = ("data", "data_collection")


def _in_editor(ctx) -> bool:
    return urlparse(ctx.current_url).path.endswith("/workflows/edit")


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
    if _in_editor(ctx) and _open_step_has_no_tool(ctx):
        # An input step's own form: set fields by the paths `tool-describe` lists.
        known = {path for path, _, _ in _inspector_fields(ctx)}
        unknown = sorted(set(requested) - known)
        if unknown:
            raise UsageError(f"unknown paths {unknown}; see `gxui tool-describe`")
        for path, value in requested.items():
            ctx.tool_form_set_parameter(path, value)
            ctx.sleep_for(ctx.wait_types.UX_RENDER)
        return f"set {len(requested)} fields; save with `gxui workflow-save`"
    parameters = ctx.tool_form_parameters(**_open_form(ctx))
    types = {p.path: p.type for p in parameters}
    repeats = {p.path.rsplit("|", 1)[-1] for p in parameters if p.type == "repeat"}
    described = {k: _first_instance(k, repeats) for k in requested}
    unknown = sorted(k for k, path in described.items() if path not in types)
    if unknown:
        raise UsageError(f"unknown paths {unknown}; see `gxui tool-describe`")
    data = {k: v for k, v in requested.items() if types[described[k]] in DATA_TYPES}
    if data and _in_editor(ctx):
        raise UsageError(f"{sorted(data)} are step inputs in the editor; connect them with `gxui workflow-connect`")
    ctx.tool_form_fill({k: v for k, v in requested.items() if k not in data}, data)
    after = "save with `gxui workflow-save`" if _in_editor(ctx) else "submit with `gxui tool-run`"
    return f"filled {len(requested)} fields; review with `gxui screenshot`, {after}"


def _first_instance(path: str, repeats: set[str]) -> str:
    """`tool-describe` lists a repeat's first instance; `components_2|x` is filled like `components_0|x`."""
    parts = []
    for part in path.split("|"):
        name, _, index = part.rpartition("_")
        parts.append(f"{name}_0" if index.isdigit() and name in repeats else part)
    return "|".join(parts)


@verb("tool-run", "tool", "tool_form_execute")
def tool_run(ctx, reuse: bool = False):
    """Submit the open tool form; prints the new output hids. Follow with `history-wait HID`.

    --reuse turns on "Attempt to re-use jobs with identical parameters?" first.
    """
    if reuse:
        ctx.tool_form_set_use_cached_job()
    before = (ctx._latest_history_item() or {}).get("hid", 0)
    ctx.tool_form_execute()
    new_hids: list[int] = []

    def outputs_appeared(driver=None):
        nonlocal new_hids
        new_hids = [i["hid"] for i in ctx.history_contents(datasets_only=True) if i["hid"] > before]
        return True if new_hids else None

    ctx._wait_on(outputs_appeared, "tool outputs to appear in the history", wait_type=ctx.wait_types.DATABASE_OPERATION)
    return "submitted; output hids " + " ".join(str(h) for h in new_hids)


@verb("tool-version", "tool", "tool_form_select_version")
def tool_version(ctx, version: str):
    """Switch the open tool form to VERSION from its versions menu; waits for the form to reload."""
    ctx.tool_form_select_version(version)
    label = ctx.components.tool_form.tool_version

    def switched(driver=None):
        return True if version in label.wait_for_text() else None

    ctx._wait_on(switched, f"the form to switch to {version}", wait_type=ctx.wait_types.UX_RENDER)
    return f"form now {label.wait_for_text()}"


@verb("tool-favorite", "tool", "tool_form_toggle_favorite")
def tool_favorite(ctx, show: bool = False):
    """Toggle the open tool form's favorite star. --show then filters the tool panel to favorites."""
    ctx.tool_form_toggle_favorite()
    if not show:
        return "toggled favorite"
    ctx.tool_panel_show_favorites()
    return "toggled favorite; tool panel filtered to #favorites"


@verb("interactive-tools", "tool", "interactive_tools_panel_open")
def interactive_tools(ctx):
    """Open the Interactive Tools activity panel; one line per active tool, `name  status`."""
    ctx.interactive_tools_panel_open()
    rows = ctx.find_elements(ctx.components.interactive_tools_panel.active_tools)
    lines = ["  ".join(line.strip() for line in row.text.splitlines()) for row in rows]
    return "\n".join(lines) or "no active interactive tools"


@verb("interactive-tool-wait", "tool", "interactive_tool_wait_running", positional=("name",))
def interactive_tool_wait(ctx, name: str):
    """Wait until active interactive tool NAME shows Running in the Interactive Tools panel."""
    ctx.interactive_tools_panel_open()
    ctx.interactive_tool_wait_running(name)
    return f"{name} running"


@verb("interactive-tool-open", "tool", "interactive_tool_open", positional=("name",))
def interactive_tool_open(ctx, name: str):
    """Open active interactive tool NAME from the Interactive Tools panel; prints the shown URL."""
    ctx.interactive_tools_panel_open()
    return ctx.interactive_tool_open(name)


@verb("interactive-tool-stop", "tool", "interactive_tool_stop", positional=("name",))
def interactive_tool_stop(ctx, name: str):
    """Stop active interactive tool NAME with its stop button in the Interactive Tools panel; waits for it to go."""
    ctx.interactive_tools_panel_open()
    ctx.interactive_tool_stop(name)
    return f"{name} stopped"


# --- workflow --------------------------------------------------------------


@verb("workflow-run", "workflow", "workflow_run_with_name", positional=("name",))
def workflow_run(
    ctx,
    name: str = "",
    inputs: str = "",
    params: str = "",
    new_history: str = "",
    submit: bool = True,
    wait: bool = False,
    timeout: float = 240.0,
):
    """Open the run form for the named workflow (no NAME: the form already open), set its inputs, submit.

    INPUTS maps data input labels to hids, '{"input1": 1}', and must name every data input: the form
    preselects the newest matching dataset otherwise. PARAMS maps parameter input labels to values,
    '{"Number of lines": 5}'. --new-history NAME sends the results to a new history. --wait waits
    for the invocation like `invocation-wait`; TIMEOUT covers the whole verb.
    """
    deadline = time.time() + timeout
    if name:
        ctx.workflow_run_with_name(name)
        _wait_for_run_form(ctx)
    elif ctx.components.workflow_run.run_workflow.is_absent:
        raise UsageError("no run form is open; pass the workflow's NAME")
    workflow_id = parse_qs(urlparse(ctx.page.url).query)["id"][0]
    name = name or workflow_id
    data, values = json.loads(inputs or "{}"), json.loads(params or "{}")
    form_inputs = _run_form_inputs(ctx, workflow_id)
    missing = [label for label in [*data, *values] if label not in form_inputs]
    if missing:
        raise UsageError(f"no inputs {missing} on the run form; its inputs are labelled {list(form_inputs)}")
    unset = [label for label, kind in form_inputs.items() if kind in DATA_INPUTS and label not in data]
    if unset and submit:
        raise UsageError(
            f"--inputs must name every data input; {unset} not given (the form would run on whatever it "
            "preselected). Look with --no-submit, then pass their hids"
        )
    if data:
        ctx.workflow_run_specify_inputs({label: {"hid": hid} for label, hid in data.items()})
    for label, value in values.items():
        ctx.components.workflow_run.simplified_input(label=label).wait_for_and_clear_and_send_keys(str(value))
    if new_history:
        _send_to_new_history(ctx, new_history)
    if not submit:
        return f"run form open for {name!r}"
    before = _latest_invocation(ctx, workflow_id)
    invocation_id = ""
    for attempt in range(2):
        ctx.workflow_run_submit()
        for _ in range(12):  # newer Galaxy routes to the invocation; older shows it in place
            time.sleep(2)
            error = ctx.components.workflow_run.run_error
            if not error.is_absent and error.is_displayed:
                break
            latest = _latest_invocation(ctx, workflow_id)
            if latest and latest != before:
                invocation_id = latest
                break
        if invocation_id:
            break
        message = _run_error(ctx)
        if "(429)" not in message or attempt:
            raise RuntimeError(f"submitting {name!r} failed: {message or 'no invocation appeared'}")
        time.sleep(10)  # the server rate-limited the submission; one slower retry
    if wait:
        return f"submitted {name!r}\n" + _invocation_wait(ctx, invocation_id, deadline)
    return (
        f"submitted {name!r}: invocation {invocation_id}; `gxui invocation-wait {invocation_id}` waits for its outputs"
    )


DATA_INPUTS = ("data_input", "data_collection_input")


def _wait_for_run_form(ctx) -> None:
    """Wait for the run form; a load the server rate-limited (429) gets one slower reload."""
    run_workflow = ctx.components.workflow_run.run_workflow
    for attempt in range(2):
        ctx._wait_on(
            lambda: not run_workflow.is_absent or _run_form_error(ctx),
            "the run form",
            wait_type=ctx.wait_types.JOB_COMPLETION,
        )
        error = _run_form_error(ctx)
        if not error:
            run_workflow.wait_for_visible()
            return
        if "(429)" not in error or attempt:
            raise RuntimeError(f"the run form did not load: {error!r}")
        time.sleep(10)
        ctx.page.reload()


def _run_form_error(ctx) -> str:
    """Text of the run form's load error, such as "Workflow cannot be executed... (429)", or ''."""
    alerts = ctx.page.locator(".alert-danger").filter(has_text="cannot be executed")
    return " ".join(alerts.first.inner_text().split()) if alerts.count() else ""


def _send_to_new_history(ctx, history_name: str) -> None:
    """Workflow Run Settings > Send results to a new history, named HISTORY_NAME."""
    workflow_run = ctx.components.workflow_run
    if workflow_run.runtime_setting_target.is_absent:  # the settings button toggles the panel
        workflow_run.runtime_setting_button.wait_for_and_click()
    if workflow_run.new_history_name_input.is_absent:
        workflow_run.runtime_setting_target.wait_for_and_click()
    workflow_run.new_history_name_input.wait_for_and_clear_and_send_keys(history_name)


def _run_form_inputs(ctx, workflow_id: str) -> dict[str, str]:
    """The workflow's input labels as the run form shows them (an unlabelled input shows its step
    number), each with its step type."""
    workflow = ctx.api_get(f"workflows/{workflow_id}")
    steps = workflow.get("steps", {})
    return {
        step["label"] or str(int(index) + 1): steps.get(index, {}).get("type", "")
        for index, step in sorted(workflow["inputs"].items(), key=lambda kv: int(kv[0]))
    }


def _run_error(ctx) -> str:
    error = ctx.components.workflow_run.run_error
    return " ".join(error.wait_for_text().split()) if not error.is_absent else ""


def _latest_invocation(ctx, workflow_id: str) -> str | None:
    latest = ctx.api_get(f"invocations?workflow_id={workflow_id}&limit=1&sort_by=create_time&sort_desc=true")
    return latest[0]["id"] if latest else None


INVOCATION_DONE = ("scheduled", "completed", "failed", "cancelled")
JOB_DONE = ("ok", "error", "failed", "skipped", "deleted", "deleting", "paused")
# Without an id, invocation-wait refuses a newest invocation that finished longer ago than this:
# a submit still in flight would otherwise read as the previous run's result.
STALE_INVOCATION = 120


@verb("invocation-wait", "workflow", positional=("invocation_id",))
def invocation_wait(ctx, invocation_id: str = "", timeout: float = 240.0):
    """Wait until a workflow invocation is scheduled and its jobs are done; TIMEOUT covers the whole verb.

    No id: the invocation open on the page, else the newest one (refused if it finished a while
    ago - pass the id you were given). Prints the job states and each output's label, hid and state.
    Polls gently: public servers rate-limit bursts.
    """
    deadline = time.time() + timeout
    if invocation_id:
        return _invocation_wait(ctx, invocation_id, deadline)
    on_page = _INVOCATION_URL.search(urlparse(ctx.page.url).path)
    if on_page:
        return _invocation_wait(ctx, on_page.group(1), deadline)
    latest = ctx.api_get("invocations?limit=1&sort_by=create_time&sort_desc=true")
    if not latest:
        raise UsageError("no invocations yet")
    return _invocation_wait(ctx, latest[0]["id"], deadline, refuse_older_than=STALE_INVOCATION)


_INVOCATION_URL = re.compile(r"/workflows/invocations/([0-9a-f]+)")


def _invocation_wait(ctx, invocation_id: str, deadline: float, refuse_older_than: float | None = None) -> str:
    start = time.time()
    while True:
        invocation = ctx.api_get(f"invocations/{invocation_id}")
        jobs = ctx.api_get(f"invocations/{invocation_id}/jobs_summary").get("states", {})
        done = invocation["state"] in INVOCATION_DONE and all(state in JOB_DONE for state in jobs)
        if done and refuse_older_than is not None:
            age = _age_seconds(invocation["update_time"])
            if age > refuse_older_than:
                raise UsageError(
                    f"the newest invocation, {invocation_id}, was already {invocation['state']} {age / 60:.0f} min "
                    "ago; a submit still in flight has no invocation yet. Pass the id workflow-run printed "
                    f"(or `gxui invocation-wait {invocation_id}` for that one)"
                )
        if done or time.time() >= deadline:
            break
        time.sleep(min(5, max(deadline - time.time(), 0)))
    summary = ", ".join(f"{count} {state}" for state, count in sorted(jobs.items())) or "no jobs"
    lines = [f"invocation {invocation_id} {invocation['state']}; jobs: {summary}"]
    lines += _invocation_output_lines(ctx, invocation_id)
    if not done:
        raise TimeoutError(
            "\n".join(lines)
            + f"\nstill running after {time.time() - start:.0f}s; run `gxui invocation-wait {invocation_id}` again"
        )
    bad = {state: count for state, count in jobs.items() if state not in ("ok", "skipped")}
    if bad:
        raise RuntimeError("\n".join(lines))
    return "\n".join(lines)


def _invocation_output_lines(ctx, invocation_id: str) -> list[str]:
    """Every step's outputs, not only the marked workflow outputs, which tutorial workflows often lack.

    Two requests whatever the invocation's size: the invocation with its steps, and its history.
    """
    invocation = ctx.api_get(f"invocations/{invocation_id}?step_details=true")
    contents = {
        item["id"]: item
        for item in ctx.api_get(
            f"histories/{invocation['history_id']}/contents?v=dev&keys=id,hid,state,name,populated_state"
        )
    }
    labels = {
        ref["id"]: label
        for outputs in (invocation.get("outputs", {}), invocation.get("output_collections", {}))
        for label, ref in outputs.items()
    }
    produced: dict[str, str] = {}
    for step in invocation.get("steps", []):
        if not step.get("jobs"):  # input steps list their inputs as outputs
            continue
        title = step.get("workflow_step_label") or f"step {step['order_index'] + 1}"
        for outputs in (step.get("outputs", {}), step.get("output_collections", {})):
            for output_name, ref in outputs.items():
                produced.setdefault(ref["id"], f"{title} {output_name}")
    lines = []
    for item_id in [*labels, *(i for i in produced if i not in labels)]:
        item = contents.get(item_id, {})
        state = item.get("state") or item.get("populated_state") or "?"
        name = labels.get(item_id) or produced[item_id]
        lines.append(f"  hid {item.get('hid', '?')} {state} {item.get('name', '')!r} ({name})")
    return lines


def _age_seconds(galaxy_time: str) -> float:
    """Seconds since a Galaxy timestamp (ISO, UTC, usually without an offset)."""
    moment = datetime.fromisoformat(galaxy_time)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - moment).total_seconds()


@verb("invocation-cancel", "workflow", "components.invocations.cancel_button")
def invocation_cancel(ctx, invocation_id: str):
    """Cancel a workflow invocation from its page (Cancel, top right); waits until Galaxy says so."""
    ctx.get(f"workflows/invocations/{invocation_id}")
    state = ctx.api_get(f"invocations/{invocation_id}")["state"]
    if state in ("cancelled", "cancelling", "failed"):
        return f"invocation {invocation_id} is already {state}"
    ctx.components.invocations.cancel_button.wait_for_and_click()
    cancelled: list[str] = []

    def stopped():
        cancelled[:] = [ctx.api_get(f"invocations/{invocation_id}")["state"]]
        return cancelled[0] in ("cancelled", "cancelling")

    ctx._wait_on(stopped, "the invocation to be cancelled", wait_type=ctx.wait_types.DATABASE_OPERATION)
    return f"invocation {invocation_id} {cancelled[0]}"


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


# --- workflow editor -------------------------------------------------------
# Steps are named by label or by the step number `workflow-steps` prints; terminals as STEP#NAME.

_CONNECTION = re.compile(r"^connection-node-(\d+)-input-(.+)-node-(\d+)-output-(.+)$")


@verb("workflow-new", "workflow", "click_button_new_workflow")
def workflow_new(ctx, name: str, annotation: str = ""):
    """Create a workflow and save it; leaves it open in the editor."""
    _reset_editor_caches(ctx)
    ctx.workflow_index_open()
    ctx.click_button_new_workflow()
    ctx.components.workflow_editor.edit_name.wait_for_and_clear_and_send_keys(name)
    if annotation:
        ctx.workflow_editor_set_annotation(annotation)
    ctx.workflow_editor_click_save()
    _wait_saved(ctx)
    return f"created {name!r}; editing it at {ctx.page.url}"


@verb("workflow-edit", "workflow", "workflow_index_open_with_name")
def workflow_edit(ctx, name: str):
    """Open the named workflow in the editor; prints its steps."""
    # Ask for the step count before the editor's own burst of requests, which servers may rate limit.
    matches = [w for w in ctx.api_get(f"workflows?search={quote(name)}") if w["name"] == name]
    if not matches:
        raise UsageError(f"no workflow named {name!r}")
    steps = matches[0].get("number_of_steps", 0)
    _reset_editor_caches(ctx)
    ctx.workflow_index_open_with_name(name)
    for attempt in range(2):
        ctx.components.workflow_editor.canvas_body.wait_for_visible()
        ctx._wait_on(
            lambda: ctx.page.locator(".workflow-node").count() >= steps or _error_dialog(ctx),
            f"the workflow's {steps} steps to render",
            wait_type=ctx.wait_types.DATABASE_OPERATION,
        )
        ctx.sleep_for(ctx.wait_types.UX_RENDER)  # versions and tools load after the steps
        error = _error_dialog(ctx)
        if not error:
            break
        if "(429)" not in error or attempt:
            raise RuntimeError(f"the editor could not load {name!r}: {error!r}")
        time.sleep(5)  # the server rate-limited the editor's burst of requests; one slower retry
        ctx.page.reload()
    return workflow_steps(ctx)


def _error_dialog(ctx) -> str:
    """Text of an open error dialog such as "Loading workflow failed... (429)", or ''."""
    dialogs = ctx.page.locator("dialog[open]").filter(has_text="failed")
    return " ".join(dialogs.first.inner_text().split()) if dialogs.count() else ""


@verb("workflow-steps", "workflow")
def workflow_steps(ctx):
    """List the open workflow's steps: number, label, tool, input terminals and what feeds them, outputs."""
    connected: dict[tuple[str, str], str] = {}
    for edge in ctx.page.locator("g[id^='connection-node-']").all():
        match = _CONNECTION.match(edge.get_attribute("id") or "")
        if match:
            sink, input_name, source, output_name = match.groups()
            connected[(sink, input_name)] = f"{source}#{output_name}"
    tools = _editor_tool_ids(ctx)
    lines = []
    for node in ctx.page.locator(".workflow-node").all():
        step = (node.get_attribute("id") or "").rsplit("-", 1)[-1]
        inputs = [
            f"{name}<-{connected[(step, name)]}" if (step, name) in connected else name
            for name in _attributes(node, "[input-name]", "input-name")
        ]
        outputs = _attributes(node, "[output-name]", "output-name")
        active = " *" if "is-active" in (node.get_attribute("class") or "") else ""
        tool = f" [{tools[step]}]" if step in tools else ""
        lines.append(
            f"{step} {node.get_attribute('node-label')!r} ({node.get_attribute('name')}){tool}{active}"
            f"  in: {', '.join(inputs) or '-'}  out: {', '.join(outputs) or '-'}"
        )
    return "\n".join(lines) or "no steps; add some with workflow-add-input / workflow-add-tool"


def _attributes(node, selector: str, attribute: str) -> list[str]:
    return [a for a in (e.get_attribute(attribute) for e in node.locator(selector).all()) if a]


@verb("workflow-add-input", "workflow", "workflow_editor_add_input", positional=("kind",))
def workflow_add_input(ctx, kind: str = "data_input", label: str = ""):
    """Add an input step: KIND is data_input (default), data_collection_input, parameter_input, ...

    `workflow-add-input list` prints the kinds this Galaxy offers (integer, boolean, ... inputs).
    """
    if kind == "list":
        editor = ctx.components.workflow_editor
        if editor.inputs.activity_panel.is_absent:
            editor.inputs.activity_button.wait_for_and_click()
        editor.inputs.activity_panel.wait_for_visible()
        return ", ".join(_input_kinds(ctx))
    before = _step_numbers(ctx)
    try:
        ctx.workflow_editor_add_input(kind)
    except Exception:
        raise UsageError(f"no input kind {kind!r}; kinds: {', '.join(_input_kinds(ctx))}") from None
    return _added_step(ctx, before, label)


def _input_kinds(ctx) -> list[str]:
    kinds = (e.get_attribute("data-id") for e in ctx.page.locator(".workflow-input-button[data-id]").all())
    return list(dict.fromkeys(k for k in kinds if k))


@verb("workflow-add-tool", "workflow", "workflow_editor_add_tool_step")
def workflow_add_tool(ctx, tool_id: str, label: str = ""):
    """Add a tool step from the editor's tool panel by tool id (`tool-search` prints ids)."""
    before = _step_numbers(ctx)
    try:
        ctx.workflow_editor_add_tool_step(tool_id)
    except Exception:
        raise UsageError(
            f"no tool {tool_id!r} in the editor's tool panel; `gxui tool-search TEXT` prints ids"
        ) from None
    step = _new_step(ctx, before)
    _editor_added_tools(ctx)[step] = tool_id
    return _finish_added_step(ctx, step, label)


def _step_numbers(ctx) -> set[str]:
    return {(n.get_attribute("id") or "").rsplit("-", 1)[-1] for n in ctx.page.locator(".workflow-node").all()}


def _added_step(ctx, before: set[str], label: str) -> str:
    return _finish_added_step(ctx, _new_step(ctx, before), label)


def _new_step(ctx, before: set[str]) -> str:
    new: list[str] = []

    def appeared(driver=None):
        new[:] = sorted(_step_numbers(ctx) - before, key=int)
        return True if new else None

    ctx._wait_on(appeared, "the new step to appear", wait_type=ctx.wait_types.DATABASE_OPERATION)
    return new[-1]


def _finish_added_step(ctx, step: str, label: str) -> str:
    _untangle(ctx, step)
    if label:
        _set_step_label(ctx, step, label)
    else:
        _select_step(ctx, step)
    return f"added step {step} {_node(ctx, step).get_attribute('node-label')!r}, open in the inspector"


def _node(ctx, step: str):
    return ctx.page.locator(f"#wf-node-step-{step}")


def _untangle(ctx, step: str) -> None:
    """New steps land on top of each other; auto-layout when one covers another so all stay clickable."""
    box = _node(ctx, step).bounding_box()
    for other in ctx.page.locator(".workflow-node").all():
        if other.get_attribute("id") == f"wf-node-step-{step}":
            continue
        o = other.bounding_box()
        if (
            box
            and o
            and box["x"] < o["x"] + o["width"]
            and o["x"] < box["x"] + box["width"]
            and box["y"] < o["y"] + o["height"]
            and o["y"] < box["y"] + box["height"]
        ):
            ctx.components.workflow_editor.tool_bar.auto_layout.wait_for_and_click()
            ctx.sleep_for(ctx.wait_types.UX_RENDER)
            return


def _bring_into_view(ctx, *targets) -> None:
    """Pan the editor canvas until TARGETS (locators) sit in its open area.

    Steps can be off screen, or (after auto-layout) under the floating toolbar; a drag only lands
    on what is visible. The open area excludes the toolbar, the zoom controls and the minimap.
    """
    area = ctx.page.evaluate(_OPEN_AREA_JS)
    boxes = [b for b in (t.bounding_box() for t in targets) if b]
    if not area or not boxes:
        return
    left, top = min(b["x"] for b in boxes), min(b["y"] for b in boxes)
    right, bottom = max(b["x"] + b["width"] for b in boxes), max(b["y"] + b["height"] for b in boxes)
    if left >= area["left"] and right <= area["right"] and top >= area["top"] and bottom <= area["bottom"]:
        return
    dx = (area["left"] + area["right"]) / 2 - (left + right) / 2
    dy = (area["top"] + area["bottom"]) / 2 - (top + bottom) / 2
    start = ctx.page.evaluate(_EMPTY_POINT_JS, area)
    if not start:
        return
    ctx.page.mouse.move(start["x"], start["y"])
    ctx.page.mouse.down()
    ctx.page.mouse.move(start["x"] + dx, start["y"] + dy, steps=15)
    ctx.page.mouse.up()
    ctx.sleep_for(ctx.wait_types.UX_RENDER)


_OPEN_AREA_JS = """() => {
    const box = (s) => document.querySelector(s)?.getBoundingClientRect();
    const canvas = box("#workflow-canvas");
    if (!canvas) return null;
    const toolbar = box(".workflow-editor-toolbar");
    const area = {left: (toolbar ? toolbar.right : canvas.left) + 20, right: canvas.right - 20,
                  top: canvas.top + 20, bottom: canvas.bottom - 70};
    const minimap = box(".workflow-overview");
    if (minimap && minimap.left < area.right && minimap.top < area.bottom) area.right = minimap.left - 20;
    const inspector = box(".tool-inspector");  // the step inspector overlays the canvas's right side
    if (inspector && inspector.width && inspector.left < area.right) area.right = inspector.left - 20;
    return area;
}"""

_EMPTY_POINT_JS = """(area) => {
    const busy = ".workflow-node, .workflow-editor-toolbar, .workflow-overview, button, svg path, .workflow-editor-comment";
    for (let y = area.bottom - 10; y > area.top; y -= 40) {
        for (let x = area.right - 10; x > area.left; x -= 40) {
            const el = document.elementFromPoint(x, y);
            if (el && el.closest("#workflow-canvas") && !el.closest(busy)) return {x, y};
        }
    }
    return null;
}"""


def _resolve_step(ctx, step: str) -> str:
    """A step number, from a number or a label."""
    if step.isdigit():
        if not _node(ctx, step).count():
            raise UsageError(f"no step {step}; `gxui workflow-steps` lists them")
        return step
    matches = ctx.page.locator(f".workflow-node[node-label={json.dumps(step)}]")
    if matches.count() != 1:
        raise UsageError(f"{matches.count()} steps labelled {step!r}; use the number `gxui workflow-steps` prints")
    return (matches.first.get_attribute("id") or "").rsplit("-", 1)[-1]


def _select_step(ctx, step: str) -> None:
    node = _node(ctx, step)
    if "is-active" not in (node.get_attribute("class") or ""):
        _bring_into_view(ctx, node.locator(".node-title"))
        try:
            ctx.workflow_editor_ensure_tool_form_open(int(step))
        except Exception:
            _untangle(ctx, step)
            ctx.workflow_editor_ensure_tool_form_open(int(step))
    ctx._wait_on(
        lambda driver=None: "is-active" in (node.get_attribute("class") or "") or None,
        f"step {step} to open in the inspector",
    )
    ctx.sleep_for(ctx.wait_types.UX_RENDER)


def _set_step_label(ctx, step: str, label: str) -> None:
    _select_step(ctx, step)
    ctx.workflow_editor_set_node_label(label)
    ctx._wait_on(
        lambda driver=None: _node(ctx, step).get_attribute("node-label") == label or None,
        f"step {step} to show label {label!r}",
    )


@verb("workflow-step", "workflow", "workflow_editor_ensure_tool_form_open")
def workflow_step(ctx, step: str, label: str = "", annotation: str = ""):
    """Open STEP in the inspector, optionally setting its label and annotation.

    Then `tool-describe` / `tool-fill` work on its tool parameters (data inputs are connections).
    """
    number = _resolve_step(ctx, step)
    if label:
        _set_step_label(ctx, number, label)
    else:
        _select_step(ctx, number)
    if annotation:
        ctx.workflow_editor_set_node_annotation(annotation)
    return f"step {number} {_node(ctx, number).get_attribute('node-label')!r} open in the inspector"


def _terminal(ctx, spec: str, kind: str) -> tuple[str, str]:
    step, sep, name = spec.rpartition("#")
    if not sep or not step or not name:
        raise UsageError(f"{spec!r} is not STEP#{kind.upper()} (e.g. '1#output' or 'Reverse dataset#outfile')")
    number = _resolve_step(ctx, step)
    names = _attributes(_node(ctx, number), f"[{kind}-name]", f"{kind}-name")
    if name not in names:
        raise UsageError(f"step {number} has no {kind} {name!r}; its {kind}s: {', '.join(names) or 'none'}")
    return number, name


@verb("workflow-connect", "workflow", "workflow_editor_try_connect")
def workflow_connect(ctx, source: str, sink: str):
    """Drag a connection from SOURCE (STEP#OUTPUT) to SINK (STEP#INPUT); STEP is a number or label.

    If the editor refuses the drop, prints its reason.
    """
    source_step, output = _terminal(ctx, source, "output")
    sink_step, input_name = _terminal(ctx, sink, "input")
    _bring_into_view(
        ctx, _by_id(ctx, f"node-{source_step}-output-{output}"), _by_id(ctx, f"node-{sink_step}-input-{input_name}")
    )
    terminals = (int(source_step), output), (int(sink_step), input_name)
    reason = ctx.workflow_editor_try_connect(*terminals)
    if reason is not None:
        # Terminal types follow edits (a parameter's type, a new upstream connection) a moment later.
        ctx.sleep_for(ctx.wait_types.UX_RENDER)
        reason = ctx.workflow_editor_try_connect(*terminals)
    if reason is not None:
        raise RuntimeError(f"the editor refuses {source} -> {sink}: {reason or 'no reason given'}")
    edge = _by_id(ctx, f"connection-node-{sink_step}-input-{input_name}-node-{source_step}-output-{output}")
    try:
        edge.wait_for(state="attached", timeout=5000)
    except Exception:
        raise RuntimeError(f"no connection appeared for {source} -> {sink}; `gxui screenshot`") from None
    return f"connected {source_step}#{output} -> {sink_step}#{input_name}"


def _by_id(ctx, element_id: str):
    """Terminal ids embed input names, which may hold spaces or `|`; an attribute selector takes them."""
    return ctx.page.locator(f"[id={json.dumps(element_id)}]")


@verb("workflow-param-input", "workflow", "components.workflow_editor.connect_icon")
def workflow_param_input(ctx, step: str, path: str, off: bool = False):
    """Turn STEP's tool parameter PATH into an input terminal ("Add connection to module"); --off reverts.

    PATH as `tool-describe` prints it; then `workflow-connect` a parameter input to STEP#PATH.
    """
    number = _resolve_step(ctx, step)
    _select_step(ctx, number)
    terminal = _node(ctx, number).locator(f"[input-name={json.dumps(path)}]")
    if bool(terminal.count()) != off:
        return f"{number}#{path} is {'not ' if off else ''}an input already"
    toggle = ctx.components.workflow_editor.connect_icon(name=path)
    try:
        toggle.wait_for_and_click()
    except Exception:
        raise UsageError(f"step {number} has no connectable parameter {path!r}; see `gxui tool-describe`") from None
    terminal.wait_for(state="detached" if off else "attached")
    return f"{number}#{path} is {'no longer ' if off else ''}an input terminal"


@verb("workflow-disconnect", "workflow", "workflow_editor_destroy_connection")
def workflow_disconnect(ctx, sink: str):
    """Remove the connection into SINK (STEP#INPUT)."""
    step, input_name = _terminal(ctx, sink, "input")
    terminal = _by_id(ctx, f"node-{step}-input-{input_name}")
    _bring_into_view(ctx, terminal)
    delete_button = terminal.locator("xpath=following-sibling::button[contains(@class, 'delete-terminal-button')]")
    if not delete_button.count():
        raise UsageError(f"nothing is connected to {sink}")
    ctx.workflow_editor_destroy_connection((int(step), input_name))
    ctx.page.locator(f"[id^={json.dumps(f'connection-node-{step}-input-{input_name}-node-')}]").wait_for(
        state="detached"
    )
    return f"disconnected {step}#{input_name}"


@verb("workflow-remove-step", "workflow", "workflow_editor_remove_node")
def workflow_remove_step(ctx, step: str):
    """Delete STEP and its connections."""
    number = _resolve_step(ctx, step)
    ctx.workflow_editor_remove_node(int(number))
    return f"removed step {number}"


@verb("workflow-output", "workflow")
def workflow_output(
    ctx,
    step: str,
    output: str,
    label: str = "",
    rename: str = "",
    add_tags: str = "",
    remove_tags: str = "",
    datatype: str = "",
):
    """Configure STEP's OUTPUT in the inspector: workflow output label, rename, tags (comma-separated), datatype."""
    number, name = _terminal(ctx, f"{step}#{output}", "output")
    _select_step(ctx, number)
    editor = ctx.components.workflow_editor
    if editor.label_output(output=name).is_absent:  # the section header toggles; open it only once
        editor.configure_output(output=name).wait_for_and_click()
    if label:
        editor.label_output(output=name).wait_for_and_clear_and_send_keys(label)
    if rename:
        editor.rename_output.wait_for_and_clear_and_send_keys(rename)
    if datatype:
        ctx.workflow_editor_change_output_datatype(name, datatype)
    for tags, button, field in (
        (add_tags, editor.add_tags_button, editor.add_tags_input),
        (remove_tags, editor.remove_tags_button, editor.remove_tags_input),
    ):
        if tags:
            button.wait_for_and_click()
            for tag in (t.strip() for t in tags.split(",") if t.strip()):
                field.wait_for_and_send_keys(tag + Keys.ENTER)
            field.wait_for_and_send_keys(Keys.ESCAPE)
    ctx.sleep_for(ctx.wait_types.UX_RENDER)
    return f"configured {number}#{name}; save with workflow-save"


@verb("workflow-save", "workflow", "workflow_editor_click_save")
def workflow_save(ctx):
    """Save the open workflow; waits until the editor reports no unsaved changes."""
    if ctx.components.workflow_editor.save_button.has_class("g-disabled"):
        return "nothing to save: no unsaved changes"
    ctx.workflow_editor_click_save()
    _wait_saved(ctx)
    _reset_editor_caches(ctx)  # the editor reloads the saved workflow, renumbering its steps
    return f"saved; {ctx.page.url}"


def _wait_saved(ctx) -> None:
    save = ctx.components.workflow_editor.save_button
    ctx._wait_on(
        lambda driver=None: save.has_class("g-disabled") or None,
        "the save to finish",
        wait_type=ctx.wait_types.DATABASE_OPERATION,
    )


@verb("workflow-add-subworkflow", "workflow", "workflow_editor_add_subworkflow")
def workflow_add_subworkflow(ctx, name: str, label: str = ""):
    """Insert the saved workflow NAME as a subworkflow step."""
    before = _step_numbers(ctx)
    ctx.workflow_editor_add_subworkflow(name)
    return _added_step(ctx, before, label)


def _reset_editor_caches(ctx) -> None:
    """A loaded or saved editor numbers steps by their saved order; forget the previous numbering."""
    ctx._gxui_saved_tools = None
    ctx._gxui_editor_workflow = None


def _editor_added_tools(ctx) -> dict[str, str]:
    """Tool ids of steps gxui added this session; the page shows a step's tool name, not its id."""
    workflow_id = _editor_workflow_id(ctx)
    if getattr(ctx, "_gxui_editor_workflow", None) != workflow_id:
        ctx._gxui_editor_tools, ctx._gxui_editor_workflow = {}, workflow_id
    return ctx._gxui_editor_tools


def _editor_workflow_id(ctx) -> str:
    return parse_qs(urlparse(ctx.page.url).query).get("id", [""])[0]


def _editor_tool_ids(ctx) -> dict[str, str]:
    """Step number to tool id: the saved workflow's tool steps, then steps gxui added since."""
    workflow_id = _editor_workflow_id(ctx)
    cached = getattr(ctx, "_gxui_saved_tools", None)
    if workflow_id and (not cached or cached[0] != workflow_id):
        try:
            steps = ctx.api_get(f"workflows/{workflow_id}/download?style=editor").get("steps", {}).items()
            cached = (workflow_id, {str(k): step["content_id"] for k, step in steps if step.get("type") == "tool"})
            ctx._gxui_saved_tools = cached
        except Exception:
            cached = None  # a rate-limited server; tool ids are a convenience, try again next time
    return {**(cached[1] if cached and cached[0] == workflow_id else {}), **_editor_added_tools(ctx)}


def _open_step_has_no_tool(ctx) -> bool:
    """An input (or other non-tool) step is open: its inspector has no tool version badge."""
    if not _active_step(ctx):
        return False
    ctx.components.workflow_editor.node_inspector.wait_for_visible()
    return ctx.page.locator('.tool-inspector [data-description="galaxy tool version"]').count() == 0


def _inspector_fields(ctx) -> list[tuple[str, str, str]]:
    """(path, title, shown value) of each field in the open step's inspector form."""
    return [
        (f["path"], f["title"], f["value"])
        for f in ctx.page.evaluate(
            """() => [...document.querySelectorAll('.tool-inspector div.ui-form-element[id^="form-element-"]')]
                .filter((e) => e.offsetParent !== null)
                .map((e) => {
                    const select = e.querySelector(".multiselect__single, .multiselect__tags");
                    const toggle = e.querySelector("input[type=checkbox]");
                    const text = e.querySelector("input:not([type=hidden]):not([type=checkbox]), textarea");
                    return {
                        path: e.id.slice("form-element-".length),
                        title: ([".ui-form-title-text", ".ui-form-title"].map((q) => e.querySelector(q)).find(Boolean) || {})
                            .innerText?.trim() || "",
                        value: select ? select.innerText : toggle ? String(toggle.checked) : text ? text.value : "",
                    };
                })"""
        )
    ]


def _active_step(ctx) -> str | None:
    active = ctx.page.locator(".workflow-node.is-active")
    return (active.first.get_attribute("id") or "").rsplit("-", 1)[-1] if active.count() else None


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
    "press",
]


@verb("component", "generic", "components.<path>", layer="component", positional=("value",))
def component(ctx, path: str, action: str, value: str = "", timeout: float = 30.0):
    """Act on one navigation.yml component: click|check|uncheck|text|value|visible|absent|wait|send-keys|clear-send-keys|press.

    PATH uses the tour grammar, e.g. 'history_panel.item(hid=3).title'. Waits up to TIMEOUT seconds.
    check/uncheck also work on styled checkboxes whose input is invisible. send-keys types VALUE as
    text; press sends one key by name (Enter, Escape, Tab, Space, ArrowDown, ...).
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
        if action == "press":
            ctx.locator(target).press(value)
            return f"pressed {value}"
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
    walked: list[str] = []
    for part in [p for p in prefix.split(".") if p]:
        parent = ".".join(walked)
        if part in node.selectors or part in node.labels:
            raise UsageError(
                f"{part!r} is a selector under {parent or '<root>'}, not a component; "
                f"act on it with `gxui component {prefix} ACTION`"
            )
        if part not in node.sub_components:
            raise UsageError(f"no component {part!r} under {parent or '<root>'}; see `gxui components {parent}`")
        node = getattr(node, part)
        walked.append(part)
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
