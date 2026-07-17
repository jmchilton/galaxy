"""Declarative YAML-driven tests for Galaxy tool parsing.

ToolSource (XML/YAML) -> ParsedTool -> path-based YAML assertions, driven by
the reusable ``gxformat2.testing`` harness.

Expectation files live in the sibling ``expectations/`` directory.  Each is a
map of ``test_id -> {fixture, operation, [expect_error], assertions[]}`` where
``operation`` is always ``parse``.  Fixtures are functional-tools basenames
resolved by ``functional_test_tool_source`` (``<name>_y`` -> ``.yml``, else
``.xml``) -- the same convention the TypeScript golden dumper uses.
"""

import os

from gxformat2.testing import DeclarativeTestSuite

from galaxy.tool_util.model_factory import parse_tool
from galaxy.tool_util.parser.factory import get_tool_source
from galaxy.tool_util.unittest_utils import functional_test_tool_source

EXPECTATIONS_DIR = os.path.join(os.path.dirname(__file__), "expectations")


def _load_fixture(name: str):
    if os.path.isabs(name) and os.path.exists(name):
        return get_tool_source(name)
    return functional_test_tool_source(name)


def _parse_op(tool_source):
    return parse_tool(tool_source)


OPERATIONS = {"parse": _parse_op}

suite = DeclarativeTestSuite(
    operations=OPERATIONS,
    load_fixture=_load_fixture,
    expectations_dir=EXPECTATIONS_DIR,
)


@suite.pytest_params()
def test_declarative_parsing(test_id, case):
    suite.run(test_id, case)
