import pytest

from galaxy.app_unittest_utils import tools_support
from galaxy.util.unittest import TestCase

OUTPUT_REFERENCES_TOOL = """<tool id="test_tool" name="Test Tool" version="1.0" profile="$profile">
    <command>echo a &gt; $$out</command>
    <inputs>
        <param name="input" type="data" multiple="true" format="data" />
        <param name="fasta_input" type="data" format="fasta">
            <conversion name="fasta_input_table" type="tabular" />
        </param>
        <param name="coll" type="data_collection" collection_type="paired" />
        <conditional name="cond">
            <param name="select" type="select"><option value="a">a</option></param>
            <when value="a"><param name="input1" type="data" format="data" /></when>
        </conditional>
        <repeat name="files" title="Files">
            <conditional name="file_cond">
                <param name="select" type="select"><option value="a">a</option></param>
                <when value="a"><param name="file" type="data" format="data" /></when>
            </conditional>
        </repeat>
    </inputs>
    <outputs>
        $outputs
    </outputs>
</tool>
"""

YAML_OUTPUT_REFERENCES_TOOL = """id: test_tool
name: Test Tool
class: GalaxyTool
version: 1.0
profile: "26.0"
shell_command: echo a > out.txt
inputs:
- name: input
  type: data
  multiple: true
- name: cond
  type: conditional
  test_parameter:
    type: boolean
    name: use
  when:
    true:
      - name: input1
        type: data
outputs:
  out_legacy:
    from_work_dir: out.txt
    format: txt
    format_source: input1
  out_numbered:
    from_work_dir: out.txt
    format: txt
    format_source: input2
"""


class TestOutputReferences(TestCase, tools_support.UsesTools):
    def setUp(self):
        self.setup_app()

    def tearDown(self):
        self.tear_down_app()

    def _load(self, outputs: str, profile: str = "26.0"):
        contents = OUTPUT_REFERENCES_TOOL.replace("$outputs", outputs)
        self._init_tool(contents, profile=profile)
        return self.tool.outputs

    def test_declared_references_kept(self):
        outputs = self._load("""
            <data name="out_multiple" format="txt" format_source="input" metadata_source="input" />
            <data name="out_selector" format="txt" format_source="coll['forward']" />
            <data name="out_qualified" format="txt" format_source="cond|input1" />
            """)
        assert outputs["out_multiple"].format_source == "input"
        assert outputs["out_multiple"].metadata_source == "input"
        assert outputs["out_selector"].format_source == "coll['forward']"
        assert outputs["out_qualified"].format_source == "cond|input1"

    def test_internal_keys_dropped(self):
        outputs = self._load("""
            <data name="out_numbered" format="txt" format_source="input2" metadata_source="input2" />
            <data name="out_conversion" format="txt" format_source="fasta_input_table" />
            <data name="out_element" format="txt" format_source="coll2" />
            <data name="out_selector" format="txt" format_source="input['forward']" />
            <data name="out_collection_metadata" format="txt" metadata_source="coll" />
            """)
        assert outputs["out_numbered"].format_source is None
        assert outputs["out_numbered"].metadata_source is None
        assert outputs["out_conversion"].format_source is None
        assert outputs["out_element"].format_source is None
        assert outputs["out_selector"].format_source is None
        assert outputs["out_collection_metadata"].metadata_source is None

    def test_legacy_alias_uses_qualified_key(self):
        # input1 is also the key job creation adds for the first dataset of the multiple input.
        outputs = self._load("""
            <data name="out_legacy" format="txt" format_source="input1" metadata_source="input1" />
            <data name="out_repeat" format="txt" format_source="files_2|file" />
            """)
        assert outputs["out_legacy"].format_source == "cond|input1"
        assert outputs["out_legacy"].metadata_source == "cond|input1"
        assert outputs["out_repeat"].format_source == "files_2|file_cond|file"

    def test_collection_references(self):
        self._load("""
            <collection name="out_collection" type="paired" format_source="input1">
                <data name="forward" format="txt" />
                <data name="reverse" format="txt" format_source="coll2" />
            </collection>
            """)
        collection = self.tool.output_collections["out_collection"]
        assert collection.format_source == "cond|input1"
        assert collection.outputs["forward"].format_source == "cond|input1"
        assert collection.outputs["reverse"].format_source is None

    def test_unresolvable_reference_fails_load_from_profile_26_2(self):
        with pytest.raises(Exception, match="format_source='input2' does not match any declared input"):
            self._load('<data name="out" format="txt" format_source="input2" />', profile="26.2")

    def test_yaml_tool_references_resolved(self):
        self._init_tool(YAML_OUTPUT_REFERENCES_TOOL, filename="tool.yml")
        assert self.tool.outputs["out_legacy"].format_source == "cond|input1"
        assert self.tool.outputs["out_numbered"].format_source is None

    def test_legacy_alias_fails_load_from_profile_26_2(self):
        with pytest.raises(Exception, match=r"format_source='input1' is unqualified, use 'cond\|input1'"):
            self._load('<data name="out" format="txt" format_source="input1" />', profile="26.2")
        with pytest.raises(Exception, match=r"metadata_source='input1' is unqualified, use 'cond\|input1'"):
            self._load('<data name="out" format="txt" metadata_source="input1" />', profile="26.2")
        with pytest.raises(
            Exception, match=r"format_source='files_2\|file' is unqualified, use 'files_2\|file_cond\|file'"
        ):
            self._load('<data name="out" format="txt" format_source="files_2|file" />', profile="26.2")

    def test_qualified_references_load_from_profile_26_2(self):
        outputs = self._load(
            """
            <data name="out_qualified" format="txt" format_source="cond|input1" metadata_source="cond|input1" />
            <data name="out_repeat" format="txt" format_source="files_2|file_cond|file" />
            """,
            profile="26.2",
        )
        assert outputs["out_qualified"].format_source == "cond|input1"
        assert outputs["out_repeat"].format_source == "files_2|file_cond|file"
