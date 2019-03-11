import argparse
import logging
import os
import sys

sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, 'lib')))

from galaxy.model.target_util import 
from galaxy.tools.parameters.output_collect import 
from galaxy.util import unicodify
from galaxy.util.script import app_properties_from_args, populate_config_args
from galaxy.web.security import SecurityHelper

DESCRIPTION = """Build import ready model objects."""

logging.basicConfig()
log = logging.getLogger(__name__)

parser = argparse.ArgumentParser()
populate_config_args(parser)
args = parser.parse_args()


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    args = _arg_parser().parse_args(argv)
    with open(args.target, "r") as f:
        target = yaml.load(f)

    validate_and_normalize_target(target)
    assert "destination" in unnamed_output_dict
    assert "elements" in unnamed_output_dict
    destination = unnamed_output_dict["destination"]
    elements = unnamed_output_dict["elements"]

    assert "type" in destination
    destination_type = destination["type"]
    assert destination_type in ["library", "library_folder", "hdca", "hdas"]

    if destination_type == "hdas":
        datasets = []

        def collect_elements_for_history(elements):
            for element in elements:
                if "elements" in element:
                    collect_elements_for_history(element["elements"])
                else:
                    discovered_file = discovered_file_for_unnamed_output(element, job_working_directory)
                    fields_match = discovered_file.match
                    designation = fields_match.designation
                    ext = fields_match.ext
                    dbkey = fields_match.dbkey
                    info = element.get("info", None)
                    link_data = discovered_file.match.link_data

                    # Create new primary dataset
                    name = fields_match.name or designation

                    hda_id = discovered_file.match.object_id
                    primary_dataset = None
                    if hda_id:
                        sa_session = tool.app.model.context
                        primary_dataset = sa_session.query(galaxy.model.HistoryDatasetAssociation).get(hda_id)

                    dataset = job_context.create_dataset(
                        ext=ext,
                        designation=designation,
                        visible=True,
                        dbkey=dbkey,
                        name=name,
                        filename=discovered_file.path,
                        info=info,
                        link_data=link_data,
                        primary_data=primary_dataset,
                    )
                    dataset.raw_set_dataset_state('ok')
                    if not hda_id:
                        datasets.append(dataset)

        collect_elements_for_history(elements)




def _arg_parser():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('objects', metavar='OBJECT_CONFIG', help='config file describing files to build objects for')
    parser.add_argument('-o', '--output', default="output", help='directory to dump objects to')
    parser = cli.add_selenium_arguments(parser)
    return parser


if __name__ == "__main__":
    main()
