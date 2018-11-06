#!/usr/bin/env python
from __future__ import absolute_import, print_function

import argparse
import os
import sys

from bioblend import galaxy

sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, 'test')))
sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, 'lib')))

from galaxy.tools.parser import get_tool_source

from base.populators import (  # noqa: I100,I202
    CwlPopulator,
    GiDatasetPopulator,
    GiWorkflowPopulator,
)

DESCRIPTION = """Simple CWL runner script."""


def main(argv=None):
    """Entry point for workflow driving."""
    arg_parser = argparse.ArgumentParser(description=DESCRIPTION)
    arg_parser.add_argument("--api_key", default="testmasterapikey")
    arg_parser.add_argument("--host", default="http://localhost:8080/")
    arg_parser.add_argument('tool', metavar='TOOL', help='tool or workflow')
    arg_parser.add_argument('job', metavar='JOB', help='job')

    args = arg_parser.parse_args(argv)

    gi = galaxy.GalaxyInstance(args.host, args.api_key)
    dataset_populator = GiDatasetPopulator(gi)
    workflow_populator = GiWorkflowPopulator(gi)
    cwl_populator = CwlPopulator(dataset_populator, workflow_populator)
    tool = os.path.abspath(args.tool)
    job = os.path.abspath(args.job)
    run = cwl_populator.run_cwl_job(tool, job)

    tool_source = get_tool_source(tool)
    # TODO: do something with collections at some point
    output_datasets, _ = tool_source.parse_outputs(None)
    for output_dataset in output_datasets.values():
        name = output_dataset.name
        print(run.get_output_as_object(name))


if __name__ == "__main__":
    main()
