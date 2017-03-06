
"""Test CWL conformance for version $version."""

from .test_workflows_cwl import BaseCwlWorklfowTestCase

class CwlConformanceTestCase(BaseCwlWorklfowTestCase):
    """Test case mapping to CWL conformance tests for version $version."""

    def test_conformance_v1_0_0(self):
        """General test of command line generation"""
        self.run_conformance_test("""v1.0""", """General test of command line generation""")

    def test_conformance_v1_0_1(self):
        """Test nested prefixes with arrays"""
        self.run_conformance_test("""v1.0""", """Test nested prefixes with arrays""")

    def test_conformance_v1_0_2(self):
        """Test nested command line bindings"""
        self.run_conformance_test("""v1.0""", """Test nested command line bindings""")

    def test_conformance_v1_0_3(self):
        """Test command line with optional input (missing)"""
        self.run_conformance_test("""v1.0""", """Test command line with optional input (missing)""")

    def test_conformance_v1_0_4(self):
        """Test command line with optional input (provided)"""
        self.run_conformance_test("""v1.0""", """Test command line with optional input (provided)""")

    def test_conformance_v1_0_5(self):
        """Test InitialWorkDirRequirement ExpressionEngineRequirement.engineConfig feature"""
        self.run_conformance_test("""v1.0""", """Test InitialWorkDirRequirement ExpressionEngineRequirement.engineConfig feature""")

    def test_conformance_v1_0_6(self):
        """Test command execution in Docker with stdout redirection"""
        self.run_conformance_test("""v1.0""", """Test command execution in Docker with stdout redirection""")

    def test_conformance_v1_0_7(self):
        """Test command execution in Docker with simplified syntax stdout redirection"""
        self.run_conformance_test("""v1.0""", """Test command execution in Docker with simplified syntax stdout redirection""")

    def test_conformance_v1_0_8(self):
        """Test command execution in Docker with stdout redirection"""
        self.run_conformance_test("""v1.0""", """Test command execution in Docker with stdout redirection""")

    def test_conformance_v1_0_9(self):
        """Test command line with stderr redirection"""
        self.run_conformance_test("""v1.0""", """Test command line with stderr redirection""")

    def test_conformance_v1_0_10(self):
        """Test command line with stderr redirection, brief syntax"""
        self.run_conformance_test("""v1.0""", """Test command line with stderr redirection, brief syntax""")

    def test_conformance_v1_0_11(self):
        """Test command line with stderr redirection, named brief syntax"""
        self.run_conformance_test("""v1.0""", """Test command line with stderr redirection, named brief syntax""")

    def test_conformance_v1_0_12(self):
        """Test command execution in Docker with stdin and stdout redirection"""
        self.run_conformance_test("""v1.0""", """Test command execution in Docker with stdin and stdout redirection""")

    def test_conformance_v1_0_13(self):
        """Test default usage of Any in expressions."""
        self.run_conformance_test("""v1.0""", """Test default usage of Any in expressions.""")

    def test_conformance_v1_0_14(self):
        """Test explicitly passing null to Any type inputs with default values."""
        self.run_conformance_test("""v1.0""", """Test explicitly passing null to Any type inputs with default values.""")

    def test_conformance_v1_0_15(self):
        """Testing the string 'null' does not trip up an Any with a default value."""
        self.run_conformance_test("""v1.0""", """Testing the string 'null' does not trip up an Any with a default value.""")

    def test_conformance_v1_0_16(self):
        """Testing the string 'null' does not trip up an Any without a default value."""
        self.run_conformance_test("""v1.0""", """Testing the string 'null' does not trip up an Any without a default value.""")

    def test_conformance_v1_0_17(self):
        """Test command execution in with stdin and stdout redirection"""
        self.run_conformance_test("""v1.0""", """Test command execution in with stdin and stdout redirection""")

    def test_conformance_v1_0_18(self):
        """Test ExpressionTool with Docker-based expression engine"""
        self.run_conformance_test("""v1.0""", """Test ExpressionTool with Docker-based expression engine""")

    def test_conformance_v1_0_19(self):
        """Test outputEval to transform output"""
        self.run_conformance_test("""v1.0""", """Test outputEval to transform output""")

    def test_conformance_v1_0_20(self):
        """Test two step workflow with imported tools"""
        self.run_conformance_test("""v1.0""", """Test two step workflow with imported tools""")

    def test_conformance_v1_0_21(self):
        """Test two step workflow with inline tools"""
        self.run_conformance_test("""v1.0""", """Test two step workflow with inline tools""")

    def test_conformance_v1_0_22(self):
        """Test single step workflow with Scatter step"""
        self.run_conformance_test("""v1.0""", """Test single step workflow with Scatter step""")

    def test_conformance_v1_0_23(self):
        """Test single step workflow with Scatter step and two data links connected to
same input, default merge behavior
"""
        self.run_conformance_test("""v1.0""", """Test single step workflow with Scatter step and two data links connected to
same input, default merge behavior
""")

    def test_conformance_v1_0_24(self):
        """Test single step workflow with Scatter step and two data links connected to
same input, nested merge behavior
"""
        self.run_conformance_test("""v1.0""", """Test single step workflow with Scatter step and two data links connected to
same input, nested merge behavior
""")

    def test_conformance_v1_0_25(self):
        """Test single step workflow with Scatter step and two data links connected to
same input, flattened merge behavior
"""
        self.run_conformance_test("""v1.0""", """Test single step workflow with Scatter step and two data links connected to
same input, flattened merge behavior
""")

    def test_conformance_v1_0_26(self):
        """Test workflow with default value for input parameter (missing)"""
        self.run_conformance_test("""v1.0""", """Test workflow with default value for input parameter (missing)""")

    def test_conformance_v1_0_27(self):
        """Test workflow with default value for input parameter (provided)"""
        self.run_conformance_test("""v1.0""", """Test workflow with default value for input parameter (provided)""")

    def test_conformance_v1_0_28(self):
        """Test EnvVarRequirement"""
        self.run_conformance_test("""v1.0""", """Test EnvVarRequirement""")

    def test_conformance_v1_0_29(self):
        """Test workflow scatter with single scatter parameter"""
        self.run_conformance_test("""v1.0""", """Test workflow scatter with single scatter parameter""")

    def test_conformance_v1_0_30(self):
        """Test workflow scatter with two scatter parameters and nested_crossproduct join method"""
        self.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and nested_crossproduct join method""")

    def test_conformance_v1_0_31(self):
        """Test workflow scatter with two scatter parameters and flat_crossproduct join method"""
        self.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and flat_crossproduct join method""")

    def test_conformance_v1_0_32(self):
        """Test workflow scatter with two scatter parameters and dotproduct join method"""
        self.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and dotproduct join method""")

    def test_conformance_v1_0_33(self):
        """Test workflow scatter with single empty list parameter"""
        self.run_conformance_test("""v1.0""", """Test workflow scatter with single empty list parameter""")

    def test_conformance_v1_0_34(self):
        """Test workflow scatter with two scatter parameters and nested_crossproduct join method with second list empty"""
        self.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and nested_crossproduct join method with second list empty""")

    def test_conformance_v1_0_35(self):
        """Test workflow scatter with two scatter parameters and nested_crossproduct join method with first list empty"""
        self.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and nested_crossproduct join method with first list empty""")

    def test_conformance_v1_0_36(self):
        """Test workflow scatter with two scatter parameters, one of which is empty and flat_crossproduct join method"""
        self.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters, one of which is empty and flat_crossproduct join method""")

    def test_conformance_v1_0_37(self):
        """Test workflow scatter with two empty scatter parameters and dotproduct join method"""
        self.run_conformance_test("""v1.0""", """Test workflow scatter with two empty scatter parameters and dotproduct join method""")

    def test_conformance_v1_0_38(self):
        """Test Any type input parameter"""
        self.run_conformance_test("""v1.0""", """Test Any type input parameter""")

    def test_conformance_v1_0_39(self):
        """Test nested workflow"""
        self.run_conformance_test("""v1.0""", """Test nested workflow""")

    def test_conformance_v1_0_40(self):
        """Test requirement priority"""
        self.run_conformance_test("""v1.0""", """Test requirement priority""")

    def test_conformance_v1_0_41(self):
        """Test requirements override hints"""
        self.run_conformance_test("""v1.0""", """Test requirements override hints""")

    def test_conformance_v1_0_42(self):
        """Test requirements on workflow steps"""
        self.run_conformance_test("""v1.0""", """Test requirements on workflow steps""")

    def test_conformance_v1_0_43(self):
        """Test default value on step input parameter"""
        self.run_conformance_test("""v1.0""", """Test default value on step input parameter""")

    def test_conformance_v1_0_44(self):
        """Test use default value on step input parameter with empty source"""
        self.run_conformance_test("""v1.0""", """Test use default value on step input parameter with empty source""")

    def test_conformance_v1_0_45(self):
        """Test use default value on step input parameter with null source"""
        self.run_conformance_test("""v1.0""", """Test use default value on step input parameter with null source""")

    def test_conformance_v1_0_46(self):
        """Test default value on step input parameter overridden by provided source"""
        self.run_conformance_test("""v1.0""", """Test default value on step input parameter overridden by provided source""")

    def test_conformance_v1_0_47(self):
        """Test simple workflow"""
        self.run_conformance_test("""v1.0""", """Test simple workflow""")

    def test_conformance_v1_0_48(self):
        """Test unknown hints are ignored."""
        self.run_conformance_test("""v1.0""", """Test unknown hints are ignored.""")

    def test_conformance_v1_0_49(self):
        """Test InitialWorkDirRequirement linking input files and capturing secondaryFiles
on input and output.
"""
        self.run_conformance_test("""v1.0""", """Test InitialWorkDirRequirement linking input files and capturing secondaryFiles
on input and output.
""")

    def test_conformance_v1_0_50(self):
        """Test InitialWorkDirRequirement with expression in filename.
"""
        self.run_conformance_test("""v1.0""", """Test InitialWorkDirRequirement with expression in filename.
""")

    def test_conformance_v1_0_51(self):
        """Test inline expressions
"""
        self.run_conformance_test("""v1.0""", """Test inline expressions
""")

    def test_conformance_v1_0_52(self):
        """Test SchemaDefRequirement definition used in tool parameter
"""
        self.run_conformance_test("""v1.0""", """Test SchemaDefRequirement definition used in tool parameter
""")

    def test_conformance_v1_0_53(self):
        """Test SchemaDefRequirement definition used in workflow parameter
"""
        self.run_conformance_test("""v1.0""", """Test SchemaDefRequirement definition used in workflow parameter
""")

    def test_conformance_v1_0_54(self):
        """Test parameter evaluation, no support for JS expressions
"""
        self.run_conformance_test("""v1.0""", """Test parameter evaluation, no support for JS expressions
""")

    def test_conformance_v1_0_55(self):
        """Test parameter evaluation, with support for JS expressions
"""
        self.run_conformance_test("""v1.0""", """Test parameter evaluation, with support for JS expressions
""")

    def test_conformance_v1_0_56(self):
        """Test metadata"""
        self.run_conformance_test("""v1.0""", """Test metadata""")

    def test_conformance_v1_0_57(self):
        """Test simple format checking.
"""
        self.run_conformance_test("""v1.0""", """Test simple format checking.
""")

    def test_conformance_v1_0_58(self):
        """Test format checking against ontology using subclassOf.
"""
        self.run_conformance_test("""v1.0""", """Test format checking against ontology using subclassOf.
""")

    def test_conformance_v1_0_59(self):
        """Test format checking against ontology using equivalentClass.
"""
        self.run_conformance_test("""v1.0""", """Test format checking against ontology using equivalentClass.
""")

    def test_conformance_v1_0_60(self):
        """Test optional output file and optional secondaryFile on output.
"""
        self.run_conformance_test("""v1.0""", """Test optional output file and optional secondaryFile on output.
""")

    def test_conformance_v1_0_61(self):
        """Test valueFrom on workflow step."""
        self.run_conformance_test("""v1.0""", """Test valueFrom on workflow step.""")

    def test_conformance_v1_0_62(self):
        """Test valueFrom on workflow step with multiple sources"""
        self.run_conformance_test("""v1.0""", """Test valueFrom on workflow step with multiple sources""")

    def test_conformance_v1_0_63(self):
        """Test valueFrom on workflow step referencing other inputs"""
        self.run_conformance_test("""v1.0""", """Test valueFrom on workflow step referencing other inputs""")

    def test_conformance_v1_0_64(self):
        """Test record type output binding."""
        self.run_conformance_test("""v1.0""", """Test record type output binding.""")

    def test_conformance_v1_0_65(self):
        """Test support for reading cwl.output.json when running in a Docker container
and just 'path' is provided.
"""
        self.run_conformance_test("""v1.0""", """Test support for reading cwl.output.json when running in a Docker container
and just 'path' is provided.
""")

    def test_conformance_v1_0_66(self):
        """Test support for reading cwl.output.json when running in a Docker container
and just 'location' is provided.
"""
        self.run_conformance_test("""v1.0""", """Test support for reading cwl.output.json when running in a Docker container
and just 'location' is provided.
""")

    def test_conformance_v1_0_67(self):
        """Test support for returning multiple glob patterns from expression"""
        self.run_conformance_test("""v1.0""", """Test support for returning multiple glob patterns from expression""")

    def test_conformance_v1_0_68(self):
        """Test workflow scatter with single scatter parameter and valueFrom on step input"""
        self.run_conformance_test("""v1.0""", """Test workflow scatter with single scatter parameter and valueFrom on step input""")

    def test_conformance_v1_0_69(self):
        """Test workflow scatter with two scatter parameters and nested_crossproduct join method and valueFrom on step input"""
        self.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and nested_crossproduct join method and valueFrom on step input""")

    def test_conformance_v1_0_70(self):
        """Test workflow scatter with two scatter parameters and flat_crossproduct join method and valueFrom on step input"""
        self.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and flat_crossproduct join method and valueFrom on step input""")

    def test_conformance_v1_0_71(self):
        """Test workflow scatter with two scatter parameters and dotproduct join method and valueFrom on step input"""
        self.run_conformance_test("""v1.0""", """Test workflow scatter with two scatter parameters and dotproduct join method and valueFrom on step input""")

    def test_conformance_v1_0_72(self):
        """Test workflow scatter with single scatter parameter and valueFrom on step input"""
        self.run_conformance_test("""v1.0""", """Test workflow scatter with single scatter parameter and valueFrom on step input""")

    def test_conformance_v1_0_73(self):
        """Test workflow two input files with same name."""
        self.run_conformance_test("""v1.0""", """Test workflow two input files with same name.""")

    def test_conformance_v1_0_74(self):
        """Test directory input with parameter reference"""
        self.run_conformance_test("""v1.0""", """Test directory input with parameter reference""")

    def test_conformance_v1_0_75(self):
        """Test directory input in Docker"""
        self.run_conformance_test("""v1.0""", """Test directory input in Docker""")

    def test_conformance_v1_0_76(self):
        """Test directory input in Docker"""
        self.run_conformance_test("""v1.0""", """Test directory input in Docker""")

    def test_conformance_v1_0_77(self):
        """Test directories in secondaryFiles"""
        self.run_conformance_test("""v1.0""", """Test directories in secondaryFiles""")

    def test_conformance_v1_0_78(self):
        """Test dynamic initial work dir"""
        self.run_conformance_test("""v1.0""", """Test dynamic initial work dir""")

    def test_conformance_v1_0_79(self):
        """Test writable staged files."""
        self.run_conformance_test("""v1.0""", """Test writable staged files.""")

    def test_conformance_v1_0_80(self):
        """Test file literal as input"""
        self.run_conformance_test("""v1.0""", """Test file literal as input""")

    def test_conformance_v1_0_81(self):
        """Test expression in InitialWorkDir listing"""
        self.run_conformance_test("""v1.0""", """Test expression in InitialWorkDir listing""")

    def test_conformance_v1_0_82(self):
        """Test nameroot/nameext expression in arguments, stdout"""
        self.run_conformance_test("""v1.0""", """Test nameroot/nameext expression in arguments, stdout""")

    def test_conformance_v1_0_83(self):
        """Test directory input with inputBinding"""
        self.run_conformance_test("""v1.0""", """Test directory input with inputBinding""")

    def test_conformance_v1_0_84(self):
        """Test command line generation of array-of-arrays"""
        self.run_conformance_test("""v1.0""", """Test command line generation of array-of-arrays""")

    def test_conformance_v1_0_85(self):
        """Test $HOME and $TMPDIR are set correctly"""
        self.run_conformance_test("""v1.0""", """Test $HOME and $TMPDIR are set correctly""")

    def test_conformance_v1_0_86(self):
        """Test $HOME and $TMPDIR are set correctly in Docker"""
        self.run_conformance_test("""v1.0""", """Test $HOME and $TMPDIR are set correctly in Docker""")

    def test_conformance_v1_0_87(self):
        """Test that expressionLib requirement of individual tool step overrides expressionLib of workflow."""
        self.run_conformance_test("""v1.0""", """Test that expressionLib requirement of individual tool step overrides expressionLib of workflow.""")

    def test_conformance_v1_0_88(self):
        """Test output of InitialWorkDir"""
        self.run_conformance_test("""v1.0""", """Test output of InitialWorkDir""")

    def test_conformance_v1_0_89(self):
        """Test embedded subworkflow"""
        self.run_conformance_test("""v1.0""", """Test embedded subworkflow""")

    def test_conformance_v1_0_90(self):
        """Test secondaryFiles on array of files."""
        self.run_conformance_test("""v1.0""", """Test secondaryFiles on array of files.""")

    def test_conformance_v1_0_91(self):
        """Test directory literal output created by ExpressionTool"""
        self.run_conformance_test("""v1.0""", """Test directory literal output created by ExpressionTool""")

    def test_conformance_v1_0_92(self):
        """Test file literal output created by ExpressionTool"""
        self.run_conformance_test("""v1.0""", """Test file literal output created by ExpressionTool""")

    def test_conformance_v1_0_93(self):
        """Test dockerOutputDirectory"""
        self.run_conformance_test("""v1.0""", """Test dockerOutputDirectory""")

    def test_conformance_v1_0_94(self):
        """Test hints with $import"""
        self.run_conformance_test("""v1.0""", """Test hints with $import""")

    def test_conformance_v1_0_95(self):
        """Test warning instead of error when default path is not found"""
        self.run_conformance_test("""v1.0""", """Test warning instead of error when default path is not found""")

    def test_conformance_v1_0_96(self):
        """Test InlineJavascriptRequirement with multiple expressions in the same tool"""
        self.run_conformance_test("""v1.0""", """Test InlineJavascriptRequirement with multiple expressions in the same tool""")

    def test_conformance_v1_0_97(self):
        """Test if a writable input directory is recursivly copied and writable"""
        self.run_conformance_test("""v1.0""", """Test if a writable input directory is recursivly copied and writable""")

    def test_conformance_v1_0_98(self):
        """Test that missing parameters are null (not undefined) in expression"""
        self.run_conformance_test("""v1.0""", """Test that missing parameters are null (not undefined) in expression""")

    def test_conformance_v1_0_99(self):
        """Test that provided parameter is not null in expression"""
        self.run_conformance_test("""v1.0""", """Test that provided parameter is not null in expression""")

    def test_conformance_v1_0_100(self):
        """Test compound workflow document"""
        self.run_conformance_test("""v1.0""", """Test compound workflow document""")

    def test_conformance_v1_0_101(self):
        """Test that nameroot and nameext are generated from basename at execution time by the runner"""
        self.run_conformance_test("""v1.0""", """Test that nameroot and nameext are generated from basename at execution time by the runner""")

    def test_conformance_v1_0_102(self):
        """Test that file path in $(inputs) for initialworkdir is in $(outdir)."""
        self.run_conformance_test("""v1.0""", """Test that file path in $(inputs) for initialworkdir is in $(outdir).""")

    def test_conformance_v1_0_103(self):
        """Test single step workflow with Scatter step and two data links connected to
same input, flattened merge behavior. Workflow inputs are set as list
"""
        self.run_conformance_test("""v1.0""", """Test single step workflow with Scatter step and two data links connected to
same input, flattened merge behavior. Workflow inputs are set as list
""")

    def test_conformance_v1_0_104(self):
        """Test step input with multiple sources with multiple types"""
        self.run_conformance_test("""v1.0""", """Test step input with multiple sources with multiple types""")

    def test_conformance_v1_0_105(self):
        """Test that shell directives are not interpreted."""
        self.run_conformance_test("""v1.0""", """Test that shell directives are not interpreted.""")

    def test_conformance_v1_0_106(self):
        """Test that shell directives are quoted."""
        self.run_conformance_test("""v1.0""", """Test that shell directives are quoted.""")

    def test_conformance_v1_0_107(self):
        """Test empty writable dir with InitialWorkDirRequirement"""
        self.run_conformance_test("""v1.0""", """Test empty writable dir with InitialWorkDirRequirement""")

    def test_conformance_v1_0_108(self):
        """Test simple scatter over an embedded subworkflow"""
        self.run_conformance_test("""v1.0""", """Test simple scatter over an embedded subworkflow""")

    def test_conformance_v1_0_109(self):
        """Test simple multiple input scatter over an embedded subworkflow"""
        self.run_conformance_test("""v1.0""", """Test simple multiple input scatter over an embedded subworkflow""")

    def test_conformance_v1_0_110(self):
        """Test record type inputs to and outputs from workflows."""
        self.run_conformance_test("""v1.0""", """Test record type inputs to and outputs from workflows.""")

    def test_conformance_v1_0_111(self):
        """Test integer workflow input and outputs"""
        self.run_conformance_test("""v1.0""", """Test integer workflow input and outputs""")

    def test_conformance_v1_0_112(self):
        """Test optional integer workflow inputs (specified)"""
        self.run_conformance_test("""v1.0""", """Test optional integer workflow inputs (specified)""")

    def test_conformance_v1_0_113(self):
        """Test optional integer workflow inputs (unspecified)"""
        self.run_conformance_test("""v1.0""", """Test optional integer workflow inputs (unspecified)""")

    def test_conformance_v1_0_114(self):
        """Test default integer workflow inputs (specified)"""
        self.run_conformance_test("""v1.0""", """Test default integer workflow inputs (specified)""")

    def test_conformance_v1_0_115(self):
        """Test default integer workflow inputs (unspecified)"""
        self.run_conformance_test("""v1.0""", """Test default integer workflow inputs (unspecified)""")

    def test_conformance_v1_0_116(self):
        """Test File input with default unspecified to workflow"""
        self.run_conformance_test("""v1.0""", """Test File input with default unspecified to workflow""")

    def test_conformance_v1_0_117(self):
        """Test File input with default specified to workflow"""
        self.run_conformance_test("""v1.0""", """Test File input with default specified to workflow""")

    def test_conformance_v1_0_118(self):
        """Test Any parameter with integer input to a tool"""
        self.run_conformance_test("""v1.0""", """Test Any parameter with integer input to a tool""")

    def test_conformance_v1_0_119(self):
        """Test Any parameter with string input to a tool"""
        self.run_conformance_test("""v1.0""", """Test Any parameter with string input to a tool""")

    def test_conformance_v1_0_120(self):
        """Test Any parameter with file input to a tool"""
        self.run_conformance_test("""v1.0""", """Test Any parameter with file input to a tool""")

    def test_conformance_v1_0_121(self):
        """Test Any parameter with array input to a tool"""
        self.run_conformance_test("""v1.0""", """Test Any parameter with array input to a tool""")

    def test_conformance_v1_0_122(self):
        """Test Any parameter with record input to a tool"""
        self.run_conformance_test("""v1.0""", """Test Any parameter with record input to a tool""")

    def test_conformance_v1_0_123(self):
        """Test Any parameter with integer input to a workflow"""
        self.run_conformance_test("""v1.0""", """Test Any parameter with integer input to a workflow""")

    def test_conformance_v1_0_124(self):
        """Test Any parameter with string input to a workflow"""
        self.run_conformance_test("""v1.0""", """Test Any parameter with string input to a workflow""")

    def test_conformance_v1_0_125(self):
        """Test Any parameter with file input to a workflow"""
        self.run_conformance_test("""v1.0""", """Test Any parameter with file input to a workflow""")

    def test_conformance_v1_0_126(self):
        """Test Any parameter with array input to a workflow"""
        self.run_conformance_test("""v1.0""", """Test Any parameter with array input to a workflow""")

    def test_conformance_v1_0_127(self):
        """Test Any parameter with record input to a tool"""
        self.run_conformance_test("""v1.0""", """Test Any parameter with record input to a tool""")

    def test_conformance_v1_0_128(self):
        """Test union type input to workflow with default unspecified"""
        self.run_conformance_test("""v1.0""", """Test union type input to workflow with default unspecified""")

    def test_conformance_v1_0_129(self):
        """Test union type input to workflow with default specified as file"""
        self.run_conformance_test("""v1.0""", """Test union type input to workflow with default specified as file""")

