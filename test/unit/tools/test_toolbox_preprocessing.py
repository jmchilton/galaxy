"""
"""

import os
import tempfile
import shutil
from galaxy.tools.toolbox import managed_conf
from galaxy.tools.toolbox import parser


def with_managed_tool_conf(func):
    def call():
        test_directory = tempfile.mkdtemp()
        test_conf = os.path.join(test_directory, "tool_conf.json")
        try:
            func(managed_conf.ManagedConf(test_conf))
        finally:
            shutil.rmtree(test_directory)
    call.__name__ = func.__name__
    return call


@with_managed_tool_conf
def test_no_preprocessing(managed_tool_conf):
    managed_tool_conf.update({"items": [
        {"type": "tool", "file": "a/b.xml"}
    ]})
    parser = toolbox_parser(managed_tool_conf)
    items = parser.parse_items()
    assert len(items) == 1
    assert items[0].get("file") == "a/b.xml"


@with_managed_tool_conf
def test_disabled(managed_tool_conf):
    managed_tool_conf.handle_actions([
        {
            "action": "create_group",
            "id": "a/",
        }, {
            "action": "add_item",
            "item": {"type": "group", "id": "a/"},
        }, {
            "action": "add_item",
            "item": {"type": "tool", "file": "a/v1/b.xml"},
            "target": {"group": "a/"},
        }
    ])
    parser = toolbox_parser(managed_tool_conf)
    items = parser.parse_items()
    assert len(items) == 1
    managed_tool_conf.handle_actions([
        {
            "action": "disable",
            "target": {"group": "a/"},
        }
    ])
    parser = toolbox_parser(managed_tool_conf)
    items = parser.parse_items()
    assert len(items) == 0


@with_managed_tool_conf
def test_groupped_items(managed_tool_conf):
    managed_tool_conf.update({
        "groups": [
            {
                "id": "a/",
                "items": [
                    {"type": "tool", "file": "a/v1/b.xml"},
                    {"type": "tool", "file": "a/v2/b.xml"},
                    {"type": "tool", "file": "a/v3/b.xml"},
                ],
            },
        ],
        "items": [
            {"type": "tool", "file": "before.xml"},
            {"type": "group", "id": "a/"},
            {"type": "tool", "file": "after.xml"},
        ]
    })
    _verify_before_three_version_after_toolbox(managed_tool_conf)


@with_managed_tool_conf
def test_groupping_actions(managed_tool_conf):
    actions = [
        {
            "action": "add_item",
            "item": {"type": "tool", "file": "before.xml"},
        }, {
            "action": "create_group",
            "id": "a/",
        }, {
            "action": "add_item",
            "item": {"type": "group", "id": "a/"},
        }, {
            "action": "add_item",
            "item": {"type": "tool", "file": "a/v1/b.xml"},
            "target": {"group": "a/"},
        }, {
            "action": "add_item",
            "item": {"type": "tool", "file": "a/v2/b.xml"},
            "target": {"group": "a/"},
        }, {
            "action": "add_item",
            "item": {"type": "tool", "file": "a/v3/b.xml"},
            "target": {"group": "a/"},
        }, {
            "action": "add_item",
            "item": {"type": "tool", "file": "after.xml"},
        }
    ]
    managed_tool_conf.handle_actions(actions)
    _verify_before_three_version_after_toolbox(managed_tool_conf)


@with_managed_tool_conf
def test_section_actions(managed_tool_conf):
    actions = [
        {
            "action": "create_section",
            "id": "section1",
            "name": "Section 1 Title",
        }, {
            "action": "create_group",
            "id": "a/",
        }, {
            "action": "add_item",
            "item": {"type": "group", "id": "a/"},
            "target": {"section": "section1"},
        }, {
            "action": "add_item",
            "item": {"type": "tool", "file": "a/v1/b.xml"},
            "target": {"group": "a/"},
        }, {
            "action": "add_item",
            "item": {"type": "tool", "file": "a/v2/b.xml"},
            "target": {"group": "a/"},
        }, {
            "action": "add_item",
            "item": {"type": "tool", "file": "a/v3/b.xml"},
            "target": {"group": "a/"},
        }
    ]
    managed_tool_conf.handle_actions(actions)
    parser = toolbox_parser(managed_tool_conf)
    items = parser.parse_items()
    assert len(items) == 1, items
    section_item = items[0]
    assert section_item.type == 'section'
    assert len(section_item.items) == 3


def _verify_before_three_version_after_toolbox(managed_tool_conf):
    parser = toolbox_parser(managed_tool_conf)
    items = parser.parse_items()
    assert len(items) == 5, items
    assert items[0].get("file") == "before.xml"
    assert items[1].get("file") == "a/v1/b.xml"
    assert items[2].get("file") == "a/v2/b.xml"
    assert items[3].get("file") == "a/v3/b.xml"
    assert items[4].get("file") == "after.xml"


def toolbox_parser(managed_conf):
    return parser.get_toolbox_parser(managed_conf.path)
