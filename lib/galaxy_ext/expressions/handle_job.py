"""
Execute an external process to evaluate expressions for Galaxy jobs.

Galaxy should be importable on sys.path .
"""

import json
import logging
import os
import sys

# insert *this* galaxy before all others on sys.path
sys.path.insert( 1, os.path.abspath( os.path.join( os.path.dirname( __file__ ), os.pardir, os.pardir ) ) )

# ensure supported version
assert sys.version_info[:2] >= ( 2, 6 ) and sys.version_info[:2] <= ( 2, 7 ), 'Python version must be 2.6 or 2.7, this is: %s' % sys.version

logging.basicConfig()
log = logging.getLogger( __name__ )

from galaxy.tools.expressions import evaluate

try:
    from schema_salad import ref_resolver
except ImportError:
    ref_resolver = None


def run(environment_path=None):
    if ref_resolver is None:
        raise Exception("Python library schema_salad must available to evaluate expressions.")

    if environment_path is None:
        environment_path = os.environ.get("GALAXY_EXPRESSION_INPUTS")
    with open(environment_path, "r") as f:
        raw_inputs = json.load(f)

    outputs = raw_inputs["outputs"]
    inputs = raw_inputs.copy()
    del inputs["outputs"]

    result = evaluate(None, inputs)

    output_environment = raw_inputs.copy()
    del output_environment["outputs"]
    # Is this how cwltool uses context?
    output_environment["context"] = result
    for output in outputs:
        path = output["path"]
        from_expression = "/context/" + output["from_expression"]
        output_value = ref_resolver.resolve_json_pointer(
            output_environment, from_expression
        )
        with open(path, "w") as f:
            json.dump( output_value, f )
