import os

import yaml


def conformance_tests_gen(directory, filename="conformance_tests.yaml"):
    """Yield conformance test entries, recursively following $import directives.

    Each yielded dict gets a 'directory' key set to the resolved directory
    of the file it was loaded from.
    """
    conformance_tests_path = os.path.join(directory, filename)
    with open(conformance_tests_path) as f:
        conformance_tests = yaml.safe_load(f)

    for conformance_test in conformance_tests:
        if "$import" in conformance_test:
            import_dir, import_filename = os.path.split(conformance_test["$import"])
            yield from conformance_tests_gen(os.path.join(directory, import_dir), import_filename)
        else:
            conformance_test["directory"] = directory
            yield conformance_test
