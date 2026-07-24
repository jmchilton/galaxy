import os
from shutil import rmtree
from tempfile import mkdtemp

from galaxy.tool_util.loader import (
    load_tool,
    template_macro_params,
)
from galaxy.util import parse_xml

# Macro/token/yield tree-expansion behavior is covered declaratively by the
# golden-file suite in tool_parsing/macro_expansion/.  Only cases that assert on
# something other than the expanded tree (e.g. template_macro_params) remain here.


class TestToolDirectory:
    __test__ = False  # Prevent pytest from discovering this class (issue #12071)

    def __init__(self):
        self.temp_directory = mkdtemp()

    def __enter__(self):
        return self

    def __exit__(self, type, value, tb):
        rmtree(self.temp_directory)

    def write(self, contents, name="tool.xml"):
        open(os.path.join(self.temp_directory, name), "w").write(contents)

    def load(self, name="tool.xml", preprocess=True):
        path = os.path.join(self.temp_directory, name)
        if preprocess:
            return load_tool(path)
        else:
            return parse_xml(path)


def test_no_macros():
    """
    Test tool loaded in absence of a macros node.
    """
    with TestToolDirectory() as tool_dir:
        tool_dir.write("<tool/>")
        tool_dir.load(preprocess=True)


def test_loader_template():
    with TestToolDirectory() as tool_dir:
        tool_dir.write("""
<tool>
    <command interpreter="python">tool_wrapper.py
    #include source=$tool_params
    </command>
    <macros>
        <template name="tool_params">-a 1 -b 2</template>
    </macros>
</tool>
""")
        xml = tool_dir.load()
        params_dict = template_macro_params(xml.getroot())
        assert params_dict["tool_params"] == "-a 1 -b 2"
