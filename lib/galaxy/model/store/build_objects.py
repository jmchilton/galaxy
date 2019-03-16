import argparse
import logging
import os
import sys

import yaml

import galaxy.model
from galaxy.datatypes.registry import example_datatype_registry_for_sample
from galaxy.model import store
from galaxy.model.store.discover import persist_target_to_export_store
from galaxy.objectstore import build_object_store_from_config
from galaxy.util.bunch import Bunch

DESCRIPTION = """Build import ready model objects."""

logging.basicConfig()
log = logging.getLogger(__name__)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    args = _arg_parser().parse_args(argv)
    object_store_config = Bunch(
        object_store_store_by="uuid",
        object_store_config_file=args.object_store_config,
        object_store_check_old_style=False,
        jobs_directory=None,
        new_file_path=None,
        umask=os.umask(0o77),
        gid=os.getgid(),
    )
    object_store = build_object_store_from_config(object_store_config)
    galaxy.model.Dataset.object_store = object_store
    galaxy.model.set_datatypes_registry(example_datatype_registry_for_sample())
    from galaxy.model import mapping
    mapping.init("/tmp", "sqlite:///:memory:", create_tables=True, object_store=object_store)

    with open(args.objects, "r") as f:
        targets = yaml.load(f)
        if not isinstance(targets, list):
            targets = [targets]

    export_path = args.export
    export_type = args.export_type

    if export_type is None:
        export_type = "directory" if not export_path.endswith(".tgz") else "bag_archive"

    export_types = {
        "directory": store.DirectoryModelExportStore,
        "tar": store.TarModelExportStore,
        "bag_directory": store.BagDirectoryModelExportStore,
        "bag_archive": store.BagArchiveModelExportStore,
    }
    store_class = export_types[export_type]
    export_kwds = {
        "serialize_dataset_objects": True,
    }

    with store_class(export_path, **export_kwds) as export_store:
        for target in targets:
            persist_target_to_export_store(target, export_store, object_store, ".")


def _arg_parser():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('objects', metavar='OBJECT_CONFIG', help='config file describing files to build objects for')
    parser.add_argument('--object-store-config', help="object store configuration file")
    parser.add_argument('-e', '--export', default="export", help='export path')
    parser.add_argument('--export-type', default=None, help='export type (if needed)')
    return parser


if __name__ == "__main__":
    main()
