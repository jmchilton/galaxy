
"""Test CWL conformance for version $version."""

from .test_workflows_cwl import BaseCwlWorklfowTestCase


class CwlConformanceTestCase(BaseCwlWorklfowTestCase):
    """Test case mapping to CWL conformance tests for version $version."""

    def test_conformance_v1_0_0(self):
        """General test of command line generation

        Generated from::

            job: v1.0/bwa-mem-job.json
            output:
              args:
              - bwa
              - mem
              - -t
              - '2'
              - -I
              - 1,2,3,4
              - -m
              - '3'
              - chr20.fa
              - example_human_Illumina.pe_1.fastq
              - example_human_Illumina.pe_2.fastq
            tool: v1.0/bwa-mem-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """General test of command line generation""")

    def test_conformance_v1_0_1(self):
        """Test nested prefixes with arrays

        Generated from::

            job: v1.0/bwa-mem-job.json
            output:
              args:
              - bwa
              - mem
              - chr20.fa
              - -XXX
              - -YYY
              - example_human_Illumina.pe_1.fastq
              - -YYY
              - example_human_Illumina.pe_2.fastq
            tool: v1.0/binding-test.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test nested prefixes with arrays""")

    def test_conformance_v1_0_2(self):
        """Test nested command line bindings

        Generated from::

            job: v1.0/tmap-job.json
            output:
              args:
              - tmap
              - mapall
              - stage1
              - map1
              - --min-seq-length
              - '20'
              - map2
              - --min-seq-length
              - '20'
              - stage2
              - map1
              - --max-seq-length
              - '20'
              - --min-seq-length
              - '10'
              - --seed-length
              - '16'
              - map2
              - --max-seed-hits
              - '-1'
              - --max-seq-length
              - '20'
              - --min-seq-length
              - '10'
            tool: v1.0/tmap-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test nested command line bindings""")

    def test_conformance_v1_0_3(self):
        """Test command line with optional input (missing)

        Generated from::

            job: v1.0/cat-job.json
            output:
              args:
              - cat
              - hello.txt
            tool: v1.0/cat1-testcli.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test command line with optional input (missing)""")

    def test_conformance_v1_0_4(self):
        """Test command line with optional input (provided)

        Generated from::

            job: v1.0/cat-n-job.json
            output:
              args:
              - cat
              - -n
              - hello.txt
            tool: v1.0/cat1-testcli.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test command line with optional input (provided)""")

    def test_conformance_v1_0_5(self):
        """Test InitialWorkDirRequirement ExpressionEngineRequirement.engineConfig feature

        Generated from::

            job: v1.0/cat-job.json
            output:
              foo:
                checksum: sha1$63da67422622fbf9251a046d7a34b7ea0fd4fead
                class: File
                location: foo.txt
                size: 22
            tool: v1.0/template-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test InitialWorkDirRequirement ExpressionEngineRequirement.engineConfig feature""")

    def test_conformance_v1_0_6(self):
        """Test command execution in Docker with stdout redirection

        Generated from::

            job: v1.0/cat-job.json
            output:
              output_file:
                checksum: sha1$47a013e660d408619d894b20806b1d5086aab03b
                class: File
                location: output.txt
                size: 13
            tool: v1.0/cat3-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test command execution in Docker with stdout redirection""")

    def test_conformance_v1_0_7(self):
        """Test command execution in Docker with simplified syntax stdout redirection

        Generated from::

            job: v1.0/cat-job.json
            output:
              output_file:
                checksum: sha1$47a013e660d408619d894b20806b1d5086aab03b
                class: File
                location: Any
                size: 13
            tool: v1.0/cat3-tool-shortcut.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test command execution in Docker with simplified syntax stdout redirection""")

    def test_conformance_v1_0_8(self):
        """Test command execution in Docker with stdout redirection

        Generated from::

            job: v1.0/cat-job.json
            output:
              output_file:
                checksum: sha1$47a013e660d408619d894b20806b1d5086aab03b
                class: File
                location: cat-out
                size: 13
            tool: v1.0/cat3-tool-mediumcut.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test command execution in Docker with stdout redirection""")

    def test_conformance_v1_0_9(self):
        """Test command line with stderr redirection

        Generated from::

            job: v1.0/empty.json
            output:
              output_file:
                checksum: sha1$f1d2d2f924e986ac86fdf7b36c94bcdf32beec15
                class: File
                location: error.txt
                size: 4
            tool: v1.0/stderr.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test command line with stderr redirection""")

    def test_conformance_v1_0_10(self):
        """Test command line with stderr redirection, brief syntax

        Generated from::

            job: v1.0/empty.json
            output:
              output_file:
                checksum: sha1$f1d2d2f924e986ac86fdf7b36c94bcdf32beec15
                class: File
                location: Any
                size: 4
            tool: v1.0/stderr-shortcut.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test command line with stderr redirection, brief syntax""")

    def test_conformance_v1_0_11(self):
        """Test command line with stderr redirection, named brief syntax

        Generated from::

            job: v1.0/empty.json
            output:
              output_file:
                checksum: sha1$f1d2d2f924e986ac86fdf7b36c94bcdf32beec15
                class: File
                location: std.err
                size: 4
            tool: v1.0/stderr-mediumcut.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test command line with stderr redirection, named brief syntax""")

    def test_conformance_v1_0_12(self):
        """Test command execution in Docker with stdin and stdout redirection

        Generated from::

            job: v1.0/cat-job.json
            output:
              output_txt:
                checksum: sha1$47a013e660d408619d894b20806b1d5086aab03b
                class: File
                location: output.txt
                size: 13
            tool: v1.0/cat4-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test command execution in Docker with stdin and stdout redirection""")

    def test_conformance_v1_0_13(self):
        """Test default usage of Any in expressions.

        Generated from::

            job: v1.0/empty.json
            output:
              output: 1
            tool: v1.0/null-expression1-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test default usage of Any in expressions.""")

    def test_conformance_v1_0_14(self):
        """Test explicitly passing null to Any type inputs with default values.

        Generated from::

            job: v1.0/null-expression1-job.json
            output:
              output: 1
            tool: v1.0/null-expression1-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test explicitly passing null to Any type inputs with default values.""")

    def test_conformance_v1_0_15(self):
        """Testing the string 'null' does not trip up an Any with a default value.

        Generated from::

            job: v1.0/null-expression2-job.json
            output:
              output: 2
            tool: v1.0/null-expression1-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Testing the string 'null' does not trip up an Any with a default value.""")

    def test_conformance_v1_0_16(self):
        """Testing the string 'null' does not trip up an Any without a default value.

        Generated from::

            job: v1.0/null-expression2-job.json
            output:
              output: 2
            tool: v1.0/null-expression2-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Testing the string 'null' does not trip up an Any without a default value.""")

    def test_conformance_v1_0_17(self):
        """Test command execution in with stdin and stdout redirection

        Generated from::

            job: v1.0/wc-job.json
            output:
              output:
                checksum: sha1$3596ea087bfdaf52380eae441077572ed289d657
                class: File
                location: output
                size: 3
            tool: v1.0/wc-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test command execution in with stdin and stdout redirection""")

    def test_conformance_v1_0_18(self):
        """Test ExpressionTool with Docker-based expression engine

        Generated from::

            job: v1.0/parseInt-job.json
            output:
              output: 42
            tool: v1.0/parseInt-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test ExpressionTool with Docker-based expression engine""")

    def test_conformance_v1_0_19(self):
        """Test outputEval to transform output

        Generated from::

            job: v1.0/wc-job.json
            output:
              output: 16
            tool: v1.0/wc2-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test outputEval to transform output""")

    def test_conformance_v1_0_20(self):
        """Test two step workflow with imported tools

        Generated from::

            job: v1.0/wc-job.json
            output:
              count_output: 16
            tool: v1.0/count-lines1-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test two step workflow with imported tools""")

    def test_conformance_v1_0_21(self):
        """Test two step workflow with inline tools

        Generated from::

            job: v1.0/wc-job.json
            output:
              count_output: 16
            tool: v1.0/count-lines2-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test two step workflow with inline tools""")

    def test_conformance_v1_0_22(self):
        """Test single step workflow with Scatter step

        Generated from::

            job: v1.0/count-lines3-job.json
            output:
              count_output:
              - 16
              - 1
            tool: v1.0/count-lines3-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test single step workflow with Scatter step""")

    def test_conformance_v1_0_23(self):
        """Test single step workflow with Scatter step and two data links connected to
same input, default merge behavior


        Generated from::

            job: v1.0/count-lines4-job.json
            output:
              count_output:
              - 16
              - 1
            tool: v1.0/count-lines4-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test single step workflow with Scatter step and two data links connected to
same input, default merge behavior
""")

    def test_conformance_v1_0_24(self):
        """Test single step workflow with Scatter step and two data links connected to
same input, nested merge behavior


        Generated from::

            job: v1.0/count-lines6-job.json
            output:
              count_output:
              - 32
              - 2
            tool: v1.0/count-lines6-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test single step workflow with Scatter step and two data links connected to
same input, nested merge behavior
""")

    def test_conformance_v1_0_25(self):
        """Test single step workflow with Scatter step and two data links connected to
same input, flattened merge behavior


        Generated from::

            job: v1.0/count-lines6-job.json
            output:
              count_output: 34
            tool: v1.0/count-lines7-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test single step workflow with Scatter step and two data links connected to
same input, flattened merge behavior
""")

    def test_conformance_v1_0_26(self):
        """Test workflow with default value for input parameter (missing)

        Generated from::

            job: v1.0/empty.json
            output:
              count_output: 1
            tool: v1.0/count-lines5-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow with default value for input parameter (missing)""")

    def test_conformance_v1_0_27(self):
        """Test workflow with default value for input parameter (provided)

        Generated from::

            job: v1.0/wc-job.json
            output:
              count_output: 16
            tool: v1.0/count-lines5-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow with default value for input parameter (provided)""")

    def test_conformance_v1_0_28(self):
        """Test EnvVarRequirement

        Generated from::

            job: v1.0/env-job.json
            output:
              out:
                checksum: sha1$b3ec4ed1749c207e52b3a6d08c59f31d83bff519
                class: File
                location: out
                size: 15
            tool: v1.0/env-tool1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test EnvVarRequirement""")

    def test_conformance_v1_0_29(self):
        """Test workflow scatter with single scatter parameter

        Generated from::

            job: v1.0/scatter-job1.json
            output:
              out:
              - foo one
              - foo two
              - foo three
              - foo four
            tool: v1.0/scatter-wf1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow scatter with single scatter parameter""")

    def test_conformance_v1_0_30(self):
        """Test workflow scatter with two scatter parameters and nested_crossproduct join method

        Generated from::

            job: v1.0/scatter-job2.json
            output:
              out:
              - - foo one three
                - foo one four
              - - foo two three
                - foo two four
            tool: v1.0/scatter-wf2.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and nested_crossproduct join method""")

    def test_conformance_v1_0_31(self):
        """Test workflow scatter with two scatter parameters and flat_crossproduct join method

        Generated from::

            job: v1.0/scatter-job2.json
            output:
              out:
              - foo one three
              - foo one four
              - foo two three
              - foo two four
            tool: v1.0/scatter-wf3.cwl#main
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and flat_crossproduct join method""")

    def test_conformance_v1_0_32(self):
        """Test workflow scatter with two scatter parameters and dotproduct join method

        Generated from::

            job: v1.0/scatter-job2.json
            output:
              out:
              - foo one three
              - foo two four
            tool: v1.0/scatter-wf4.cwl#main
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and dotproduct join method""")

    def test_conformance_v1_0_33(self):
        """Test workflow scatter with single empty list parameter

        Generated from::

            job: v1.0/scatter-empty-job1.json
            output:
              out: []
            tool: v1.0/scatter-wf1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow scatter with single empty list parameter""")

    def test_conformance_v1_0_34(self):
        """Test workflow scatter with two scatter parameters and nested_crossproduct join method with second list empty

        Generated from::

            job: v1.0/scatter-empty-job2.json
            output:
              out:
              - []
              - []
            tool: v1.0/scatter-wf2.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and nested_crossproduct join method with second list empty""")

    def test_conformance_v1_0_35(self):
        """Test workflow scatter with two scatter parameters and nested_crossproduct join method with first list empty

        Generated from::

            job: v1.0/scatter-empty-job3.json
            output:
              out: []
            tool: v1.0/scatter-wf3.cwl#main
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and nested_crossproduct join method with first list empty""")

    def test_conformance_v1_0_36(self):
        """Test workflow scatter with two scatter parameters, one of which is empty and flat_crossproduct join method

        Generated from::

            job: v1.0/scatter-empty-job2.json
            output:
              out: []
            tool: v1.0/scatter-wf3.cwl#main
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters, one of which is empty and flat_crossproduct join method""")

    def test_conformance_v1_0_37(self):
        """Test workflow scatter with two empty scatter parameters and dotproduct join method

        Generated from::

            job: v1.0/scatter-empty-job4.json
            output:
              out: []
            tool: v1.0/scatter-wf4.cwl#main
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow scatter with two empty scatter parameters and dotproduct join method""")

    def test_conformance_v1_0_38(self):
        """Test Any type input parameter

        Generated from::

            job: v1.0/env-job.json
            output:
              out: 'hello test env
            
                '
            tool: v1.0/echo-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test Any type input parameter""")

    def test_conformance_v1_0_39(self):
        """Test nested workflow

        Generated from::

            job: v1.0/wc-job.json
            output:
              count_output: 16
            tool: v1.0/count-lines8-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test nested workflow""")

    def test_conformance_v1_0_40(self):
        """Test requirement priority

        Generated from::

            job: v1.0/env-job.json
            output:
              out:
                checksum: sha1$b3ec4ed1749c207e52b3a6d08c59f31d83bff519
                class: File
                location: out
                size: 15
            tool: v1.0/env-wf1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test requirement priority""")

    def test_conformance_v1_0_41(self):
        """Test requirements override hints

        Generated from::

            job: v1.0/env-job.json
            output:
              out:
                checksum: sha1$cdc1e84968261d6a7575b5305945471f8be199b6
                class: File
                location: out
                size: 9
            tool: v1.0/env-wf2.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test requirements override hints""")

    def test_conformance_v1_0_42(self):
        """Test requirements on workflow steps

        Generated from::

            job: v1.0/env-job.json
            output:
              out:
                checksum: sha1$cdc1e84968261d6a7575b5305945471f8be199b6
                class: File
                location: out
                size: 9
            tool: v1.0/env-wf3.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test requirements on workflow steps""")

    def test_conformance_v1_0_43(self):
        """Test default value on step input parameter

        Generated from::

            job: v1.0/empty.json
            output:
              count_output: 16
            tool: v1.0/count-lines9-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test default value on step input parameter""")

    def test_conformance_v1_0_44(self):
        """Test use default value on step input parameter with empty source

        Generated from::

            job: v1.0/empty.json
            output:
              count_output: 16
            tool: v1.0/count-lines11-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test use default value on step input parameter with empty source""")

    def test_conformance_v1_0_45(self):
        """Test use default value on step input parameter with null source

        Generated from::

            job: v1.0/file1-null.json
            output:
              count_output: 16
            tool: v1.0/count-lines11-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test use default value on step input parameter with null source""")

    def test_conformance_v1_0_46(self):
        """Test default value on step input parameter overridden by provided source

        Generated from::

            job: v1.0/cat-job.json
            output:
              count_output: 1
            tool: v1.0/count-lines11-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test default value on step input parameter overridden by provided source""")

    def test_conformance_v1_0_47(self):
        """Test simple workflow

        Generated from::

            job: v1.0/revsort-job.json
            output:
              output:
                checksum: sha1$b9214658cc453331b62c2282b772a5c063dbd284
                class: File
                location: output.txt
                size: 1111
            tool: v1.0/revsort.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test simple workflow""")

    def test_conformance_v1_0_48(self):
        """Test unknown hints are ignored.

        Generated from::

            job: v1.0/cat-job.json
            output:
              output_file:
                checksum: sha1$47a013e660d408619d894b20806b1d5086aab03b
                class: File
                location: output.txt
                size: 13
            tool: v1.0/cat5-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test unknown hints are ignored.""")

    def test_conformance_v1_0_49(self):
        """Test InitialWorkDirRequirement linking input files and capturing secondaryFiles
on input and output.


        Generated from::

            job: v1.0/search-job.json
            output:
              indexedfile:
                checksum: sha1$327fc7aedf4f6b69a42a7c8b808dc5a7aff61376
                class: File
                location: input.txt
                secondaryFiles:
                - checksum: sha1$553f3a09003a9f69623f03bec13c0b078d706023
                  class: File
                  location: input.txt.idx1
                  size: 1500
                - checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                  class: File
                  location: input.idx2
                  size: 0
                - checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                  class: File
                  location: input.txt.idx3
                  size: 0
                - checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                  class: File
                  location: input.txt.idx4
                  size: 0
                - checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                  class: File
                  location: input.txt.idx5
                  size: 0
                - checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                  class: File
                  location: input.idx6.txt
                  size: 0
                - checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                  class: File
                  location: input.txt.idx7
                  size: 0
                - checksum: sha1$47a013e660d408619d894b20806b1d5086aab03b
                  class: File
                  location: hello.txt
                  size: 13
                - class: Directory
                  listing:
                  - basename: index
                    checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                    class: File
                    location: index
                    size: 0
                  location: input.txt_idx8
                size: 1111
              outfile:
                checksum: sha1$e2dc9daaef945ac15f01c238ed2f1660f60909a0
                class: File
                location: result.txt
                size: 142
            tool: v1.0/search.cwl#main
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test InitialWorkDirRequirement linking input files and capturing secondaryFiles
on input and output.
""")

    def test_conformance_v1_0_50(self):
        """Test InitialWorkDirRequirement with expression in filename.


        Generated from::

            job: v1.0/rename-job.json
            output:
              outfile:
                checksum: sha1$327fc7aedf4f6b69a42a7c8b808dc5a7aff61376
                class: File
                location: fish.txt
                size: 1111
            tool: v1.0/rename.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test InitialWorkDirRequirement with expression in filename.
""")

    def test_conformance_v1_0_51(self):
        """Test inline expressions


        Generated from::

            job: v1.0/wc-job.json
            output:
              output: 16
            tool: v1.0/wc4-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test inline expressions
""")

    def test_conformance_v1_0_52(self):
        """Test SchemaDefRequirement definition used in tool parameter


        Generated from::

            job: v1.0/schemadef-job.json
            output:
              output:
                checksum: sha1$f12e6cfe70f3253f70b0dbde17c692e7fb0f1e5e
                class: File
                location: output.txt
                size: 12
            tool: v1.0/schemadef-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test SchemaDefRequirement definition used in tool parameter
""")

    def test_conformance_v1_0_53(self):
        """Test SchemaDefRequirement definition used in workflow parameter


        Generated from::

            job: v1.0/schemadef-job.json
            output:
              output:
                checksum: sha1$f12e6cfe70f3253f70b0dbde17c692e7fb0f1e5e
                class: File
                location: output.txt
                size: 12
            tool: v1.0/schemadef-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test SchemaDefRequirement definition used in workflow parameter
""")

    def test_conformance_v1_0_54(self):
        """Test parameter evaluation, no support for JS expressions


        Generated from::

            job: v1.0/empty.json
            output:
              t1:
                bar:
                  b az: 2
                  b"az: null
                  b'az: true
                  baz: zab1
                  buz:
                  - a
                  - b
                  - c
              t10: true
              t11: true
              t12: null
              t13: -zab1
              t14: -zab1
              t15: -zab1
              t16: -zab1
              t17: zab1 zab1
              t18: zab1 zab1
              t19: zab1 zab1
              t2:
                b az: 2
                b"az: null
                b'az: true
                baz: zab1
                buz:
                - a
                - b
                - c
              t20: zab1 zab1
              t21: 2 2
              t22: true true
              t23: true true
              t24: null null
              t25: b
              t26: b b
              t27: null
              t28: 3
              t3:
                b az: 2
                b"az: null
                b'az: true
                baz: zab1
                buz:
                - a
                - b
                - c
              t4:
                b az: 2
                b"az: null
                b'az: true
                baz: zab1
                buz:
                - a
                - b
                - c
              t5: zab1
              t6: zab1
              t7: zab1
              t8: zab1
              t9: 2
            tool: v1.0/params.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test parameter evaluation, no support for JS expressions
""")

    def test_conformance_v1_0_55(self):
        """Test parameter evaluation, with support for JS expressions


        Generated from::

            job: v1.0/empty.json
            output:
              t1:
                bar:
                  b az: 2
                  b"az: null
                  b'az: true
                  baz: zab1
                  buz:
                  - a
                  - b
                  - c
              t10: true
              t11: true
              t12: null
              t13: -zab1
              t14: -zab1
              t15: -zab1
              t16: -zab1
              t17: zab1 zab1
              t18: zab1 zab1
              t19: zab1 zab1
              t2:
                b az: 2
                b"az: null
                b'az: true
                baz: zab1
                buz:
                - a
                - b
                - c
              t20: zab1 zab1
              t21: 2 2
              t22: true true
              t23: true true
              t24: null null
              t25: b
              t26: b b
              t27: null
              t28: 3
              t3:
                b az: 2
                b"az: null
                b'az: true
                baz: zab1
                buz:
                - a
                - b
                - c
              t4:
                b az: 2
                b"az: null
                b'az: true
                baz: zab1
                buz:
                - a
                - b
                - c
              t5: zab1
              t6: zab1
              t7: zab1
              t8: zab1
              t9: 2
            tool: v1.0/params2.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test parameter evaluation, with support for JS expressions
""")

    def test_conformance_v1_0_56(self):
        """Test metadata

        Generated from::

            job: v1.0/cat-job.json
            output: {}
            tool: v1.0/metadata.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test metadata""")

    def test_conformance_v1_0_57(self):
        """Test simple format checking.


        Generated from::

            job: v1.0/formattest-job.json
            output:
              output:
                checksum: sha1$97fe1b50b4582cebc7d853796ebd62e3e163aa3f
                class: File
                format: http://edamontology.org/format_2330
                location: output.txt
                size: 1111
            tool: v1.0/formattest.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test simple format checking.
""")

    def test_conformance_v1_0_58(self):
        """Test format checking against ontology using subclassOf.


        Generated from::

            job: v1.0/formattest2-job.json
            output:
              output:
                checksum: sha1$971d88faeda85a796752ecf752b7e2e34f1337ce
                class: File
                format: http://edamontology.org/format_1929
                location: output.txt
                size: 12010
            tool: v1.0/formattest2.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test format checking against ontology using subclassOf.
""")

    def test_conformance_v1_0_59(self):
        """Test format checking against ontology using equivalentClass.


        Generated from::

            job: v1.0/formattest2-job.json
            output:
              output:
                checksum: sha1$971d88faeda85a796752ecf752b7e2e34f1337ce
                class: File
                format: http://edamontology.org/format_1929
                location: output.txt
                size: 12010
            tool: v1.0/formattest3.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test format checking against ontology using equivalentClass.
""")

    def test_conformance_v1_0_60(self):
        """Test optional output file and optional secondaryFile on output.


        Generated from::

            job: v1.0/cat-job.json
            output:
              optional_file: null
              output_file:
                checksum: sha1$47a013e660d408619d894b20806b1d5086aab03b
                class: File
                location: output.txt
                size: 13
            tool: v1.0/optional-output.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test optional output file and optional secondaryFile on output.
""")

    def test_conformance_v1_0_61(self):
        """Test valueFrom on workflow step.

        Generated from::

            job: v1.0/step-valuefrom-wf.json
            output:
              count_output: 16
            tool: v1.0/step-valuefrom-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test valueFrom on workflow step.""")

    def test_conformance_v1_0_62(self):
        """Test valueFrom on workflow step with multiple sources

        Generated from::

            job: v1.0/step-valuefrom-job.json
            output:
              val: '3
            
                '
            tool: v1.0/step-valuefrom2-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test valueFrom on workflow step with multiple sources""")

    def test_conformance_v1_0_63(self):
        """Test valueFrom on workflow step referencing other inputs

        Generated from::

            job: v1.0/step-valuefrom-job.json
            output:
              val: '3
            
                '
            tool: v1.0/step-valuefrom3-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test valueFrom on workflow step referencing other inputs""")

    def test_conformance_v1_0_64(self):
        """Test record type output binding.

        Generated from::

            job: v1.0/record-output-job.json
            output:
              orec:
                obar:
                  checksum: sha1$aeb3d11bdf536511649129f4077d5cda6a324118
                  class: File
                  location: bar
                  size: 12010
                ofoo:
                  checksum: sha1$327fc7aedf4f6b69a42a7c8b808dc5a7aff61376
                  class: File
                  location: foo
                  size: 1111
            tool: v1.0/record-output.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test record type output binding.""")

    def test_conformance_v1_0_65(self):
        """Test support for reading cwl.output.json when running in a Docker container
and just 'path' is provided.


        Generated from::

            job: v1.0/empty.json
            output:
              foo:
                checksum: sha1$f1d2d2f924e986ac86fdf7b36c94bcdf32beec15
                class: File
                location: foo
                size: 4
            tool: v1.0/test-cwl-out.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test support for reading cwl.output.json when running in a Docker container
and just 'path' is provided.
""")

    def test_conformance_v1_0_66(self):
        """Test support for reading cwl.output.json when running in a Docker container
and just 'location' is provided.


        Generated from::

            job: v1.0/empty.json
            output:
              foo:
                checksum: sha1$f1d2d2f924e986ac86fdf7b36c94bcdf32beec15
                class: File
                location: foo
                size: 4
            tool: v1.0/test-cwl-out2.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test support for reading cwl.output.json when running in a Docker container
and just 'location' is provided.
""")

    def test_conformance_v1_0_67(self):
        """Test support for returning multiple glob patterns from expression

        Generated from::

            job: v1.0/abc.json
            output:
              files:
              - checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                class: File
                location: a
                size: 0
              - checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                class: File
                location: b
                size: 0
              - checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                class: File
                location: c
                size: 0
            tool: v1.0/glob-expr-list.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test support for returning multiple glob patterns from expression""")

    def test_conformance_v1_0_68(self):
        """Test workflow scatter with single scatter parameter and valueFrom on step input

        Generated from::

            job: v1.0/scatter-valuefrom-job1.json
            output:
              out:
              - foo one one
              - foo one two
              - foo one three
              - foo one four
            tool: v1.0/scatter-valuefrom-wf1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow scatter with single scatter parameter and valueFrom on step input""")

    def test_conformance_v1_0_69(self):
        """Test workflow scatter with two scatter parameters and nested_crossproduct join method and valueFrom on step input

        Generated from::

            job: v1.0/scatter-valuefrom-job2.json
            output:
              out:
              - - foo one one three
                - foo one one four
              - - foo one two three
                - foo one two four
            tool: v1.0/scatter-valuefrom-wf2.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and nested_crossproduct join method and valueFrom on step input""")

    def test_conformance_v1_0_70(self):
        """Test workflow scatter with two scatter parameters and flat_crossproduct join method and valueFrom on step input

        Generated from::

            job: v1.0/scatter-valuefrom-job2.json
            output:
              out:
              - foo one one three
              - foo one one four
              - foo one two three
              - foo one two four
            tool: v1.0/scatter-valuefrom-wf3.cwl#main
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and flat_crossproduct join method and valueFrom on step input""")

    def test_conformance_v1_0_71(self):
        """Test workflow scatter with two scatter parameters and dotproduct join method and valueFrom on step input

        Generated from::

            job: v1.0/scatter-valuefrom-job2.json
            output:
              out:
              - foo one one three
              - foo one two four
            tool: v1.0/scatter-valuefrom-wf4.cwl#main
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and dotproduct join method and valueFrom on step input""")

    def test_conformance_v1_0_72(self):
        """Test workflow scatter with single scatter parameter and valueFrom on step input

        Generated from::

            job: v1.0/scatter-valuefrom-job1.json
            output:
              out:
              - foo one one
              - foo two two
              - foo three three
              - foo four four
            tool: v1.0/scatter-valuefrom-wf5.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow scatter with single scatter parameter and valueFrom on step input""")

    def test_conformance_v1_0_73(self):
        """Test valueFrom eval on scattered input parameter

        Generated from::

            job: v1.0/scatter-valuefrom-job3.json
            output:
              out_message:
              - checksum: sha1$98030575f6fc40e5021be5a8803a6bef94aee11f
                class: File
                location: Any
                size: 16
              - checksum: sha1$edcacd50778d98ae113015406b3195c165059dd8
                class: File
                location: Any
                size: 16
            tool: v1.0/scatter-valuefrom-wf6.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test valueFrom eval on scattered input parameter""")

    def test_conformance_v1_0_74(self):
        """Test workflow two input files with same name.

        Generated from::

            job: v1.0/conflict-job.json
            output:
              fileout:
                checksum: sha1$a2d8d6e7b28295dc9977dc3bdb652ddd480995f0
                class: File
                location: out.txt
                size: 25
            tool: v1.0/conflict-wf.cwl#collision
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test workflow two input files with same name.""")

    def test_conformance_v1_0_75(self):
        """Test directory input with parameter reference

        Generated from::

            job: v1.0/dir-job.yml
            output:
              outlist:
                checksum: sha1$13cda8661796ae241da3a18668fb552161a72592
                class: File
                location: output.txt
                size: 20
            tool: v1.0/dir.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test directory input with parameter reference""")

    def test_conformance_v1_0_76(self):
        """Test directory input in Docker

        Generated from::

            job: v1.0/dir-job.yml
            output:
              outlist:
                checksum: sha1$13cda8661796ae241da3a18668fb552161a72592
                class: File
                location: output.txt
                size: 20
            tool: v1.0/dir2.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test directory input in Docker""")

    def test_conformance_v1_0_77(self):
        """Test directory output

        Generated from::

            job: v1.0/dir3-job.yml
            output:
              outdir:
                class: Directory
                listing:
                - checksum: sha1$47a013e660d408619d894b20806b1d5086aab03b
                  class: File
                  location: hello.txt
                  size: 13
                - checksum: sha1$dd0a4c4c49ba43004d6611771972b6cf969c1c01
                  class: File
                  location: goodbye.txt
                  size: 24
            tool: v1.0/dir3.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test directory output""")

    def test_conformance_v1_0_78(self):
        """Test directories in secondaryFiles

        Generated from::

            job: v1.0/dir4-job.yml
            output:
              outlist:
                checksum: sha1$13cda8661796ae241da3a18668fb552161a72592
                class: File
                location: output.txt
                size: 20
            tool: v1.0/dir4.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test directories in secondaryFiles""")

    def test_conformance_v1_0_79(self):
        """Test specifying secondaryFiles in subdirectories of the job input document.

        Generated from::

            job: v1.0/dir4-subdir-1-job.yml
            output:
              outlist:
                checksum: sha1$9d9bc8f5252d39274b5dfbac64216c6e888f5dfc
                class: File
                location: output.txt
                size: 14
            tool: v1.0/dir4.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test specifying secondaryFiles in subdirectories of the job input document.""")

    def test_conformance_v1_0_80(self):
        """Test specifying secondaryFiles in same subdirectory of the job input as the primary input file.

        Generated from::

            job: v1.0/dir4-subdir-2-job.yml
            output:
              outlist:
                checksum: sha1$9d9bc8f5252d39274b5dfbac64216c6e888f5dfc
                class: File
                location: output.txt
                size: 14
            tool: v1.0/dir4.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test specifying secondaryFiles in same subdirectory of the job input as the primary input file.""")

    def test_conformance_v1_0_81(self):
        """Test dynamic initial work dir

        Generated from::

            job: v1.0/dir-job.yml
            output:
              outlist:
                checksum: sha1$907a866a3e0b7f1fc5a2222531c5fb9063704438
                class: File
                location: output.txt
                size: 33
            tool: v1.0/dir5.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test dynamic initial work dir""")

    def test_conformance_v1_0_82(self):
        """Test writable staged files.

        Generated from::

            job: v1.0/stagefile-job.yml
            output:
              outfile:
                checksum: sha1$b769c7b2e316edd4b5eb2d24799b2c1f9d8c86e6
                class: File
                location: bob.txt
                size: 1111
            tool: v1.0/stagefile.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test writable staged files.""")

    def test_conformance_v1_0_83(self):
        """Test file literal as input

        Generated from::

            job: v1.0/file-literal.yml
            output:
              output_file:
                checksum: sha1$d0e04ff6c413c7d57f9a0ca0a33cd3ab52e2dd9c
                class: File
                location: output.txt
                size: 18
            tool: v1.0/cat3-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test file literal as input""")

    def test_conformance_v1_0_84(self):
        """Test expression in InitialWorkDir listing

        Generated from::

            job: examples/arguments-job.yml
            output:
              classfile:
                checksum: sha1$e68df795c0686e9aa1a1195536bd900f5f417b18
                class: File
                location: Hello.class
                size: 184
            tool: examples/linkfile.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test expression in InitialWorkDir listing""")

    def test_conformance_v1_0_85(self):
        """Test nameroot/nameext expression in arguments, stdout

        Generated from::

            job: v1.0/wc-job.json
            output:
              b:
                checksum: sha1$c4cfd130e7578714e3eef91c1d6d90e0e0b9db3e
                class: File
                location: whale.xtx
                size: 21
            tool: v1.0/nameroot.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test nameroot/nameext expression in arguments, stdout""")

    def test_conformance_v1_0_86(self):
        """Test directory input with inputBinding

        Generated from::

            job: v1.0/dir-job.yml
            output:
              outlist:
                checksum: sha1$13cda8661796ae241da3a18668fb552161a72592
                class: File
                location: output.txt
                size: 20
            tool: v1.0/dir6.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test directory input with inputBinding""")

    def test_conformance_v1_0_87(self):
        """Test command line generation of array-of-arrays

        Generated from::

            job: v1.0/nested-array-job.yml
            output:
              echo:
                checksum: sha1$3f786850e387550fdab836ed7e6dc881de23001b
                class: File
                location: echo.txt
                size: 2
            tool: v1.0/nested-array.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test command line generation of array-of-arrays""")

    def test_conformance_v1_0_88(self):
        """Test $HOME and $TMPDIR are set correctly

        Generated from::

            job: v1.0/empty.json
            output: {}
            tool: v1.0/envvar.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test $HOME and $TMPDIR are set correctly""")

    def test_conformance_v1_0_89(self):
        """Test $HOME and $TMPDIR are set correctly in Docker

        Generated from::

            job: v1.0/empty.json
            output: {}
            tool: v1.0/envvar2.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test $HOME and $TMPDIR are set correctly in Docker""")

    def test_conformance_v1_0_90(self):
        """Test that expressionLib requirement of individual tool step overrides expressionLib of workflow.

        Generated from::

            job: v1.0/empty.json
            output:
              out:
                checksum: sha1$7448d8798a4380162d4b56f9b452e2f6f9e24e7a
                class: File
                location: whatever.txt
                size: 2
            tool: v1.0/js-expr-req-wf.cwl#wf
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test that expressionLib requirement of individual tool step overrides expressionLib of workflow.""")

    def test_conformance_v1_0_91(self):
        """Test output of InitialWorkDir

        Generated from::

            job: v1.0/initialworkdirrequirement-docker-out-job.json
            output:
              OUTPUT:
                checksum: sha1$aeb3d11bdf536511649129f4077d5cda6a324118
                class: File
                location: ref.fasta
                secondaryFiles:
                - checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                  class: File
                  location: ref.fasta.fai
                  size: 0
                size: 12010
            tool: v1.0/initialworkdirrequirement-docker-out.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test output of InitialWorkDir""")

    def test_conformance_v1_0_92(self):
        """Test embedded subworkflow

        Generated from::

            job: v1.0/wc-job.json
            output:
              count_output: 16
            tool: v1.0/count-lines10-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test embedded subworkflow""")

    def test_conformance_v1_0_93(self):
        """Test secondaryFiles on array of files.

        Generated from::

            job: v1.0/docker-array-secondaryfiles-job.json
            output:
              bai_list:
                checksum: sha1$081fc0e57d6efa5f75eeb237aab1d04031132be6
                class: File
                location: fai.list
                size: 386
            tool: v1.0/docker-array-secondaryfiles.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test secondaryFiles on array of files.""")

    def test_conformance_v1_0_94(self):
        """Test directory literal output created by ExpressionTool

        Generated from::

            job: v1.0/dir7.yml
            output:
              dir:
                class: Directory
                listing:
                - checksum: sha1$327fc7aedf4f6b69a42a7c8b808dc5a7aff61376
                  class: File
                  location: whale.txt
                  size: 1111
                - checksum: sha1$47a013e660d408619d894b20806b1d5086aab03b
                  class: File
                  location: hello.txt
                  size: 13
                location: a_directory
            tool: v1.0/dir7.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test directory literal output created by ExpressionTool""")

    def test_conformance_v1_0_95(self):
        """Test file literal output created by ExpressionTool

        Generated from::

            job: v1.0/empty.json
            output:
              lit:
                checksum: sha1$fea23663b9c8ed71968f86415b5ec091bb111448
                class: File
                location: a_file
                size: 19
            tool: v1.0/file-literal-ex.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test file literal output created by ExpressionTool""")

    def test_conformance_v1_0_96(self):
        """Test dockerOutputDirectory

        Generated from::

            job: v1.0/empty.json
            output:
              thing:
                checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                class: File
                location: thing
                size: 0
            tool: v1.0/docker-output-dir.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test dockerOutputDirectory""")

    def test_conformance_v1_0_97(self):
        """Test hints with $import

        Generated from::

            job: v1.0/empty.json
            output:
              out:
                checksum: sha1$b3ec4ed1749c207e52b3a6d08c59f31d83bff519
                class: File
                location: out
                size: 15
            tool: v1.0/imported-hint.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test hints with $import""")

    def test_conformance_v1_0_98(self):
        """Test warning instead of error when default path is not found

        Generated from::

            job: v1.0/default_path_job.yml
            output: {}
            tool: v1.0/default_path.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test warning instead of error when default path is not found""")

    def test_conformance_v1_0_99(self):
        """Test InlineJavascriptRequirement with multiple expressions in the same tool

        Generated from::

            job: v1.0/empty.json
            output:
              args:
              - -A
              - '2'
              - -B
              - baz
              - -C
              - '10'
              - '9'
              - '8'
              - '7'
              - '6'
              - '5'
              - '4'
              - '3'
              - '2'
              - '1'
            tool: v1.0/inline-js.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test InlineJavascriptRequirement with multiple expressions in the same tool""")

    def test_conformance_v1_0_100(self):
        """Test if a writable input directory is recursivly copied and writable

        Generated from::

            job: v1.0/recursive-input-directory.yml
            output:
              output_dir:
                basename: work_dir
                class: Directory
                listing:
                - basename: a
                  checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                  class: File
                  location: work_dir/a
                  size: 0
                - basename: b
                  checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                  class: File
                  location: work_dir/b
                  size: 0
                - basename: c
                  class: Directory
                  listing:
                  - basename: d
                    checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                    class: File
                    location: work_dir/c/d
                    size: 0
                  location: work_dir/c
                - basename: e
                  checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                  class: File
                  location: work_dir/e
                  size: 0
                location: work_dir
              test_result:
                basename: output.txt
                checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                class: File
                location: output.txt
                size: 0
            tool: v1.0/recursive-input-directory.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test if a writable input directory is recursivly copied and writable""")

    def test_conformance_v1_0_101(self):
        """Test that missing parameters are null (not undefined) in expression

        Generated from::

            job: v1.0/empty.json
            output:
              out: 't
            
                '
            tool: v1.0/null-defined.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test that missing parameters are null (not undefined) in expression""")

    def test_conformance_v1_0_102(self):
        """Test that provided parameter is not null in expression

        Generated from::

            job: v1.0/cat-job.json
            output:
              out: 'f
            
                '
            tool: v1.0/null-defined.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test that provided parameter is not null in expression""")

    def test_conformance_v1_0_103(self):
        """Test compound workflow document

        Generated from::

            job: v1.0/revsort-job.json
            output:
              output:
                checksum: sha1$b9214658cc453331b62c2282b772a5c063dbd284
                class: File
                location: output.txt
                size: 1111
            tool: v1.0/revsort-packed.cwl#main
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test compound workflow document""")

    def test_conformance_v1_0_104(self):
        """Test that nameroot and nameext are generated from basename at execution time by the runner

        Generated from::

            job: v1.0/basename-fields-job.yml
            output:
              extFile:
                checksum: sha1$301a72c82a835e1737caf30f94d0eec210c4d9f1
                class: File
                location: Any
                path: Any
                size: 5
              rootFile:
                checksum: sha1$b4a583c391e234cf210e1d576f68f674c8ad7ecd
                class: File
                location: Any
                path: Any
                size: 10
            tool: v1.0/basename-fields-test.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test that nameroot and nameext are generated from basename at execution time by the runner""")

    def test_conformance_v1_0_105(self):
        """Test that file path in $(inputs) for initialworkdir is in $(outdir).

        Generated from::

            job: v1.0/wc-job.json
            output: {}
            tool: v1.0/initialwork-path.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test that file path in $(inputs) for initialworkdir is in $(outdir).""")

    def test_conformance_v1_0_106(self):
        """Test single step workflow with Scatter step and two data links connected to
same input, flattened merge behavior. Workflow inputs are set as list


        Generated from::

            job: v1.0/count-lines6-job.json
            output:
              count_output: 34
            tool: v1.0/count-lines12-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test single step workflow with Scatter step and two data links connected to
same input, flattened merge behavior. Workflow inputs are set as list
""")

    def test_conformance_v1_0_107(self):
        """Test step input with multiple sources with multiple types

        Generated from::

            job: v1.0/sum-job.json
            output:
              result: 12
            tool: v1.0/sum-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test step input with multiple sources with multiple types""")

    def test_conformance_v1_0_108(self):
        """Test that shell directives are not interpreted.

        Generated from::

            job: v1.0/empty.json
            output:
              stderr_file:
                checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                class: File
                location: Any
                size: 0
              stdout_file:
                checksum: sha1$1555252d52d4ec3262538a4426a83a99cfff4402
                class: File
                location: Any
                size: 9
            tool: v1.0/shellchar.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test that shell directives are not interpreted.""")

    def test_conformance_v1_0_109(self):
        """Test that shell directives are quoted.

        Generated from::

            job: v1.0/empty.json
            output:
              stderr_file:
                checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                class: File
                location: Any
                size: 0
              stdout_file:
                checksum: sha1$1555252d52d4ec3262538a4426a83a99cfff4402
                class: File
                location: Any
                size: 9
            tool: v1.0/shellchar2.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test that shell directives are quoted.""")

    def test_conformance_v1_0_110(self):
        """Test empty writable dir with InitialWorkDirRequirement

        Generated from::

            job: v1.0/empty.json
            output:
              out:
                basename: emptyWritableDir
                class: Directory
                listing:
                - basename: blurg
                  checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                  class: File
                  location: blurg
                  size: 0
                location: emptyWritableDir
            tool: v1.0/writable-dir.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test empty writable dir with InitialWorkDirRequirement""")

    def test_conformance_v1_0_111(self):
        """Test dynamic resource reqs referencing inputs

        Generated from::

            job: v1.0/dynresreq-job.json
            output:
              output:
                checksum: sha1$7448d8798a4380162d4b56f9b452e2f6f9e24e7a
                class: File
                location: cores.txt
                size: 2
            tool: v1.0/dynresreq.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test dynamic resource reqs referencing inputs""")

    def test_conformance_v1_0_112(self):
        """Test file literal as input without Docker

        Generated from::

            job: v1.0/file-literal.yml
            output:
              output_file:
                checksum: sha1$d0e04ff6c413c7d57f9a0ca0a33cd3ab52e2dd9c
                class: File
                location: output.txt
                size: 18
            tool: v1.0/cat3-nodocker.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test file literal as input without Docker""")

    def test_conformance_v1_0_113(self):
        """Test simple scatter over an embedded subworkflow

        Generated from::

            job: v1.0/count-lines3-job.json
            output:
              count_output:
              - 16
              - 1
            tool: v1.0/count-lines13-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test simple scatter over an embedded subworkflow""")

    def test_conformance_v1_0_114(self):
        """Test simple multiple input scatter over an embedded subworkflow

        Generated from::

            job: v1.0/count-lines4-job.json
            output:
              count_output:
              - 16
              - 1
            tool: v1.0/count-lines14-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test simple multiple input scatter over an embedded subworkflow""")

    def test_conformance_v1_0_115(self):
        """Test twice nested subworkflow

        Generated from::

            job: v1.0/wc-job.json
            output:
              count_output: 16
            tool: v1.0/count-lines15-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test twice nested subworkflow""")

    def test_conformance_v1_0_116(self):
        """Test subworkflow of mixed depth with tool first

        Generated from::

            job: v1.0/wc-job.json
            output:
              count_output: 16
            tool: v1.0/count-lines16-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test subworkflow of mixed depth with tool first""")

    def test_conformance_v1_0_117(self):
        """Test subworkflow of mixed depth with tool after

        Generated from::

            job: v1.0/wc-job.json
            output:
              count_output: 16
            tool: v1.0/count-lines17-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test subworkflow of mixed depth with tool after""")

    def test_conformance_v1_0_118(self):
        """Test record type inputs to and outputs from workflows.

        Generated from::

            job: v1.0/record-output-job.json
            output:
              orec:
                obar:
                  checksum: sha1$aeb3d11bdf536511649129f4077d5cda6a324118
                  class: File
                  location: bar
                  size: 12010
                ofoo:
                  checksum: sha1$327fc7aedf4f6b69a42a7c8b808dc5a7aff61376
                  class: File
                  location: foo
                  size: 1111
            tool: v1.0/record-output-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test record type inputs to and outputs from workflows.""")

    def test_conformance_v1_0_119(self):
        """Test integer workflow input and outputs

        Generated from::

            job: v1.0/io-int.json
            output:
              o: 10
            tool: v1.0/io-int-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test integer workflow input and outputs""")

    def test_conformance_v1_0_120(self):
        """Test optional integer workflow inputs (specified)

        Generated from::

            job: v1.0/io-int.json
            output:
              o: 10
            tool: v1.0/io-int-optional-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test optional integer workflow inputs (specified)""")

    def test_conformance_v1_0_121(self):
        """Test optional integer workflow inputs (unspecified)

        Generated from::

            job: v1.0/empty.json
            output:
              o: 4
            tool: v1.0/io-int-optional-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test optional integer workflow inputs (unspecified)""")

    def test_conformance_v1_0_122(self):
        """Test default integer workflow inputs (specified)

        Generated from::

            job: v1.0/io-int.json
            output:
              o: 10
            tool: v1.0/io-int-default-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test default integer workflow inputs (specified)""")

    def test_conformance_v1_0_123(self):
        """Test default integer workflow inputs (unspecified)

        Generated from::

            job: v1.0/empty.json
            output:
              o: 8
            tool: v1.0/io-int-default-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test default integer workflow inputs (unspecified)""")

    def test_conformance_v1_0_124(self):
        """Test default integer tool and workflow inputs (unspecified)

        Generated from::

            job: v1.0/empty.json
            output:
              o: 13
            tool: v1.0/io-int-default-tool-and-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test default integer tool and workflow inputs (unspecified)""")

    def test_conformance_v1_0_125(self):
        """Test File input with default unspecified to workflow

        Generated from::

            job: v1.0/empty.json
            output:
              o:
                basename: output
                checksum: sha1$327fc7aedf4f6b69a42a7c8b808dc5a7aff61376
                class: File
                location: Any
                size: 1111
            tool: v1.0/io-file-default-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test File input with default unspecified to workflow""")

    def test_conformance_v1_0_126(self):
        """Test File input with default specified to workflow

        Generated from::

            job: v1.0/default_path_job.yml
            output:
              o:
                basename: output
                checksum: sha1$47a013e660d408619d894b20806b1d5086aab03b
                class: File
                location: Any
                size: 13
            tool: v1.0/io-file-default-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test File input with default specified to workflow""")

    def test_conformance_v1_0_127(self):
        """Test input union type or File or File array to a tool with one file in array specified.

        Generated from::

            job: v1.0/job-input-array-one-empty-file.json
            output:
              output_file:
                basename: output.txt
                checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                class: File
                location: Any
                size: 0
            tool: v1.0/io-file-or-files.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test input union type or File or File array to a tool with one file in array specified.""")

    def test_conformance_v1_0_128(self):
        """Test input union type or File or File array to a tool with a few files in array specified.

        Generated from::

            job: v1.0/job-input-array-few-files.json
            output:
              output_file:
                basename: output.txt
                checksum: sha1$6d1723861ad5a1260f1c3c07c93076c5a215f646
                class: File
                location: Any
                size: 1114
            tool: v1.0/io-file-or-files.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test input union type or File or File array to a tool with a few files in array specified.""")

    def test_conformance_v1_0_129(self):
        """Test input union type or File or File array to a tool with one file specified.

        Generated from::

            job: v1.0/job-input-one-file.json
            output:
              output_file:
                basename: output.txt
                checksum: sha1$327fc7aedf4f6b69a42a7c8b808dc5a7aff61376
                class: File
                location: Any
                size: 1111
            tool: v1.0/io-file-or-files.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test input union type or File or File array to a tool with one file specified.""")

    def test_conformance_v1_0_130(self):
        """Test input union type or File or File array to a tool with null specified.

        Generated from::

            job: v1.0/job-input-null.json
            output:
              output_file:
                basename: output.txt
                checksum: sha1$503458abf7614be3fb26d85ff5d8f3e17aa0a552
                class: File
                location: Any
                size: 10
            tool: v1.0/io-file-or-files.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test input union type or File or File array to a tool with null specified.""")

    def test_conformance_v1_0_131(self):
        """Test Any parameter with integer input to a tool

        Generated from::

            job: v1.0/io-any-int.json
            output:
              t1: 7
            tool: v1.0/io-any-1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test Any parameter with integer input to a tool""")

    def test_conformance_v1_0_132(self):
        """Test Any parameter with string input to a tool

        Generated from::

            job: v1.0/io-any-string.json
            output:
              t1: '7'
            tool: v1.0/io-any-1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test Any parameter with string input to a tool""")

    def test_conformance_v1_0_133(self):
        """Test Any parameter with file input to a tool

        Generated from::

            job: v1.0/io-any-file.json
            output:
              t1: File
            tool: v1.0/io-any-1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test Any parameter with file input to a tool""")

    def test_conformance_v1_0_134(self):
        """Test Any parameter with array input to a tool

        Generated from::

            job: v1.0/io-any-array.json
            output:
              t1:
              - 1
              - moocow
            tool: v1.0/io-any-1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test Any parameter with array input to a tool""")

    def test_conformance_v1_0_135(self):
        """Test Any parameter with record input to a tool

        Generated from::

            job: v1.0/io-any-record.json
            output:
              t1:
                cow: 5
                moo: 1
            tool: v1.0/io-any-1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test Any parameter with record input to a tool""")

    def test_conformance_v1_0_136(self):
        """Test Any parameter with integer input to a workflow

        Generated from::

            job: v1.0/io-any-int.json
            output:
              t1: 7
            tool: v1.0/io-any-wf-1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test Any parameter with integer input to a workflow""")

    def test_conformance_v1_0_137(self):
        """Test Any parameter with string input to a workflow

        Generated from::

            job: v1.0/io-any-string.json
            output:
              t1: '7'
            tool: v1.0/io-any-wf-1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test Any parameter with string input to a workflow""")

    def test_conformance_v1_0_138(self):
        """Test Any parameter with file input to a workflow

        Generated from::

            job: v1.0/io-any-file.json
            output:
              t1: File
            tool: v1.0/io-any-wf-1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test Any parameter with file input to a workflow""")

    def test_conformance_v1_0_139(self):
        """Test Any parameter with array input to a workflow

        Generated from::

            job: v1.0/io-any-array.json
            output:
              t1:
              - 1
              - moocow
            tool: v1.0/io-any-wf-1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test Any parameter with array input to a workflow""")

    def test_conformance_v1_0_140(self):
        """Test Any parameter with record input to a tool

        Generated from::

            job: v1.0/io-any-record.json
            output:
              t1:
                cow: 5
                moo: 1
            tool: v1.0/io-any-wf-1.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test Any parameter with record input to a tool""")

    def test_conformance_v1_0_141(self):
        """Test union type input to workflow with default unspecified

        Generated from::

            job: v1.0/empty.json
            output:
              o: the default value
            tool: v1.0/io-union-input-default-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test union type input to workflow with default unspecified""")

    def test_conformance_v1_0_142(self):
        """Test union type input to workflow with default specified as file

        Generated from::

            job: v1.0/io-any-file.json
            output:
              o: File
            tool: v1.0/io-union-input-default-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test union type input to workflow with default specified as file""")

    def test_conformance_v1_0_143(self):
        """Test valueFrom on workflow step from literal (string).

        Generated from::

            job: v1.0/empty.json
            output:
              val: 'moocow
            
                '
            tool: v1.0/step-valuefrom4-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test valueFrom on workflow step from literal (string).""")

    def test_conformance_v1_0_144(self):
        """Test valueFrom on workflow step using basename.

        Generated from::

            job: v1.0/wc-job.json
            output:
              val1: 'whale.txt
            
                '
              val2: 'step1_out
            
                '
            tool: v1.0/step-valuefrom5-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test valueFrom on workflow step using basename.""")

    def test_conformance_v1_0_145(self):
        """Test output arrays in a tool (with ints).

        Generated from::

            job: v1.0/output-arrays-int-job.json
            output:
              o:
              - 0
              - 1
              - 2
            tool: v1.0/output-arrays-int.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test output arrays in a tool (with ints).""")

    def test_conformance_v1_0_146(self):
        """Test output arrays in a workflow (with ints).

        Generated from::

            job: v1.0/output-arrays-int-job.json
            output:
              o: 12
            tool: v1.0/output-arrays-int-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test output arrays in a workflow (with ints).""")

    def test_conformance_v1_0_147(self):
        """Test output arrays in a workflow (with Files).

        Generated from::

            job: v1.0/output-arrays-file-job.json
            output:
              o:
              - basename: moo
                checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                class: File
                location: Any
                size: 0
              - basename: cow
                checksum: sha1$da39a3ee5e6b4b0d3255bfef95601890afd80709
                class: File
                location: Any
                size: 0
            tool: v1.0/output-arrays-file-wf.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test output arrays in a workflow (with Files).""")

    def test_conformance_v1_0_148(self):
        """Test Docker ENTRYPOINT usage

        Generated from::

            job: v1.0/empty.json
            output:
              cow:
                basename: cow
                checksum: sha1$7a788f56fa49ae0ba5ebde780efe4d6a89b5db47
                class: File
                location: Any
                size: 4
            tool: v1.0/docker-run-cmd.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test Docker ENTRYPOINT usage""")

    def test_conformance_v1_0_149(self):
        """Test use of size in expressions for an empty file

        Generated from::

            job: v1.0/job-input-array-one-empty-file.json
            output:
              output_file:
                basename: output.txt
                checksum: sha1$dad5a8472b87f6c5ef87d8fc6ef1458defc57250
                class: File
                location: Any
                size: 11
            tool: v1.0/size-expression-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test use of size in expressions for an empty file""")

    def test_conformance_v1_0_150(self):
        """Test use of size in expressions for a few files

        Generated from::

            job: v1.0/job-input-array-few-files.json
            output:
              output_file:
                basename: output.txt
                checksum: sha1$9def39730e8012bd09bf8387648982728501737d
                class: File
                location: Any
                size: 31
            tool: v1.0/size-expression-tool.cwl
        """
        self.cwl_populator.run_conformance_test("""v1.0""", """Test use of size in expressions for a few files""")

