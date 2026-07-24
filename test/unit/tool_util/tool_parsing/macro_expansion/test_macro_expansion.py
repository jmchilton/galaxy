"""Golden-file tests for Galaxy XML macro expansion.

Macros (``<macros>``/``<expand>``/``<token>``/``<import>``/``yield``) are an
XML-only, pre-parse transform -- ``YamlToolSource`` has no macro pass -- so the
natural contract is the *expanded XML tree itself*, not a ``ParsedTool`` path
assertion.  These are the data-driven form of the imperative macro cases in
``test/unit/tool_util/test_tool_loader.py``; the complex yield cases there
already compare ``xml_to_string(pretty=True)`` output verbatim, so this only
externalizes that idiom into checked-in goldens.

Each case is a directory under ``cases/`` containing:

* ``tool.xml``      -- the source to expand (required)
* ``*.xml`` imports -- any files ``<import>``-ed by ``tool.xml``
* ``expected.xml``  -- the golden expansion (required unless ``error`` present)
* ``error``         -- presence marks an expected failure; its stripped text,
                       when non-empty, must equal the raised exception message

Regenerate goldens after an intentional expander change with::

    GALAXY_TEST_REGEN_GOLDEN=1 pytest test/unit/tool_util/tool_parsing/macro_expansion/
"""

import os

import pytest

from galaxy.tool_util.loader import load_tool
from galaxy.util import xml_to_string

CASES_DIR = os.path.join(os.path.dirname(__file__), "cases")
XML_BASE_ATTR = "{http://www.w3.org/XML/1998/namespace}base"
REGEN = os.environ.get("GALAXY_TEST_REGEN_GOLDEN") == "1"


def _case_names():
    if not os.path.isdir(CASES_DIR):
        return []
    return sorted(name for name in os.listdir(CASES_DIR) if os.path.isfile(os.path.join(CASES_DIR, name, "tool.xml")))


def _expand(tool_path: str) -> str:
    """Expand macros and serialize to the portable golden form.

    ``<import>`` injects a machine-specific absolute ``xml:base`` onto imported
    nodes; strip it so goldens are stable and portable.
    """
    tree = load_tool(tool_path)
    root = tree.getroot()
    for el in root.iter():
        if XML_BASE_ATTR in el.attrib:
            del el.attrib[XML_BASE_ATTR]
    return xml_to_string(root, pretty=True)


@pytest.mark.parametrize("case", _case_names())
def test_macro_expansion(case):
    case_dir = os.path.join(CASES_DIR, case)
    tool_path = os.path.join(case_dir, "tool.xml")
    error_path = os.path.join(case_dir, "error")
    golden_path = os.path.join(case_dir, "expected.xml")

    if os.path.exists(error_path):
        with pytest.raises(Exception) as exc_info:
            _expand(tool_path)
        expected_message = open(error_path).read().strip()
        if expected_message:
            assert str(exc_info.value) == expected_message
        return

    actual = _expand(tool_path)
    if REGEN:
        with open(golden_path, "w") as f:
            f.write(actual if actual.endswith("\n") else actual + "\n")
        return

    assert os.path.exists(
        golden_path
    ), f"missing golden {golden_path!r}; run with GALAXY_TEST_REGEN_GOLDEN=1 to create it"
    expected = open(golden_path).read().rstrip("\n")
    assert actual.rstrip("\n") == expected
