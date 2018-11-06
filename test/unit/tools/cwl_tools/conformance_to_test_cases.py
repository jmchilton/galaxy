import os
import string
import sys

import yaml

THIS_DIRECTORY = os.path.dirname(os.path.normpath(__file__))
API_TEST_DIRECTORY = os.path.join(THIS_DIRECTORY, "..", "..", "..", "api")

TEST_FILE_TEMPLATE = string.Template('''
"""Test CWL conformance for version $version."""

from .test_workflows_cwl import BaseCwlWorklfowTestCase


class CwlConformanceTestCase(BaseCwlWorklfowTestCase):
    """Test case mapping to CWL conformance tests for version $version."""
$tests
''')

TEST_TEMPLATE = string.Template('''
    def test_conformance_${version_simple}_${label}(self):
        """${doc}

        Generated from::

${cwl_test_def}
        """
        self.cwl_populator.run_conformance_test("""${version}""", """${doc}""")
''')


def main():
    version = "v1.0"
    if len(sys.argv) > 1:
        version = sys.argv[1]
    version_simple = version.replace(".", "_")
    conformance_tests_path = os.path.join(THIS_DIRECTORY, version, "conformance_tests.yaml")
    with open(conformance_tests_path, "r") as f:
        conformance_tests = yaml.load(f)

    tests = ""
    for i, conformance_test in enumerate(conformance_tests):
        test_with_doc = conformance_test.copy()
        del test_with_doc["doc"]
        cwl_test_def = yaml.dump(test_with_doc, default_flow_style=False)
        cwl_test_def = "\n".join(["            %s" % l for l in cwl_test_def.splitlines()])
        label = conformance_test.get("label", str(i))
        tests = tests + TEST_TEMPLATE.safe_substitute({
            'version_simple': version_simple,
            'version': version,
            'doc': conformance_test['doc'],
            'cwl_test_def': cwl_test_def,
            'label': label,
        })

    test_file_contents = TEST_FILE_TEMPLATE.safe_substitute({
        'version_simple': version_simple,
        'tests': tests
    })

    with open(os.path.join(API_TEST_DIRECTORY, "test_cwl_conformance_%s.py" % version_simple), "w") as f:
        f.write(test_file_contents)


if __name__ == "__main__":
    main()
