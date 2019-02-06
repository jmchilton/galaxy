#!/usr/bin/env python
"""
Export a history to an archive file using attribute files.

usage: %prog history_attrs dataset_attrs job_attrs out_file
    -G, --gzip: gzip archive file
"""
from __future__ import print_function

import optparse
import os
import shutil
import sys
import tarfile
from json import dump, load

from galaxy.util import FILENAME_VALID_CHARS


def get_dataset_filename(name, ext, hid):
    """
    Builds a filename for a dataset using its name an extension.
    """
    base = ''.join(c in FILENAME_VALID_CHARS and c or '_' for c in name)
    return base + "_%s.%s" % (hid, ext)


def read_attributes_from_file(file):
    """ Read attributes from file and return JSON. """
    with open(file, 'r') as f:
        return load(f)


def store_to_archive_and_rewrite(dataset_attrs, history_archive, arcname, dir_name, key):
    if '_file_name' not in dataset_attrs:
        return

    dataset_file_name = dataset_attrs.pop('_file_name')  # Full file name.
    arcname = os.path.join(dir_name, arcname)
    history_archive.add(dataset_file_name, arcname=arcname)
    dataset_attrs['file_name'] = arcname

    # Include additional files for example, files/images included in HTML output.
    extra_files_path = dataset_attrs.pop('_extra_files_path', None)
    if extra_files_path:
        try:
            file_list = os.listdir(extra_files_path)
        except OSError:
            file_list = []

        if len(file_list):
            dataset_extra_files_path = '%s/extra_files_path_%s' % (dir_name, key)
            for fname in file_list:
                history_archive.add(os.path.join(extra_files_path, fname),
                                    arcname=(os.path.join(dataset_extra_files_path, fname)))
            dataset_attrs['extra_files_path'] = dataset_extra_files_path
        else:
            dataset_attrs['extra_files_path'] = ''


def create_archive(export_directory, out_file, gzip=False):
    """Create archive from the given attribute/metadata files and save it to out_file."""
    history_attrs_file = os.path.join(export_directory, 'history_attrs.txt')
    datasets_attrs_file = os.path.join(export_directory, 'datasets_attrs.txt')
    jobs_attrs_file = os.path.join(export_directory, 'jobs_attrs.txt')
    collections_attrs_file = os.path.join(export_directory, 'collections_attrs.txt')
    export_attrs_file = os.path.join(export_directory, 'export_attrs.txt')
    icjs_attrs_file = os.path.join(export_directory, 'implicit_collection_jobs_attrs.txt')

    tarfile_mode = "w"
    if gzip:
        tarfile_mode += ":gz"
    try:

        history_archive = tarfile.open(out_file, tarfile_mode)

        datasets_attrs = read_attributes_from_file(datasets_attrs_file)

        # Add datasets to archive and update dataset attributes.
        # TODO: security check to ensure that files added are in Galaxy dataset directory?
        for dataset_attrs in datasets_attrs:
            if not dataset_attrs.get("_file_name"):
                continue

            dataset_hid = dataset_attrs['hid']
            dataset_archive_name = get_dataset_filename(dataset_attrs['name'], dataset_attrs['extension'], dataset_hid)
            store_to_archive_and_rewrite(dataset_attrs, history_archive, dataset_archive_name, 'datasets', dataset_hid)

        # Rewrite dataset attributes file.
        with open(datasets_attrs_file, 'w') as datasets_attrs_out:
            dump(datasets_attrs, datasets_attrs_out)

        # Finish archive.
        if os.path.exists(datasets_attrs_file + ".provenance"):
            history_archive.add(datasets_attrs_file + ".provenance", arcname="datasets_attrs.txt.provenance")

        optional_files = [history_attrs_file, datasets_attrs_file, jobs_attrs_file, collections_attrs_file, export_attrs_file, icjs_attrs_file]
        for attrs_file in optional_files:
            if attrs_file and os.path.exists(attrs_file):
                history_archive.add(attrs_file, arcname=os.path.basename(attrs_file))

        history_archive.close()
        # Status.
        print('Created history archive.')
        return 0
    except Exception as e:
        print('Error creating history archive: %s' % str(e), file=sys.stderr)
        return 1


def main(argv=None):
    # Parse command line.
    parser = optparse.OptionParser()
    parser.add_option('-G', '--gzip', dest='gzip', action="store_true", help='Compress archive using gzip.')
    parser.add_option('--galaxy-version', dest='galaxy_version', help='Galaxy version that initiated the command.', default=None)
    (options, args) = parser.parse_args(argv)
    galaxy_version = options.galaxy_version
    if galaxy_version is None:
        galaxy_version = "19.01" if len(args) == 4 else "19.05"

    gzip = bool(options.gzip)
    if galaxy_version == "19.01":
        # This job was created pre 18.0X with old argument style.
        out_file = args[3]
        temp_directory = os.path.dirname(args[0])
    else:
        assert len(args) >= 2
        # We have a 19.0X directory argument instead of individual arguments.
        temp_directory = args[0]
        out_file = args[1]

    if galaxy_version == "19.01":
        history_attrs = os.path.join(temp_directory, 'history_attrs.txt')
        dataset_attrs = os.path.join(temp_directory, 'datasets_attrs.txt')
        job_attrs = os.path.join(temp_directory, 'jobs_attrs.txt')

        shutil.move(args[0], history_attrs)
        shutil.move(args[1], dataset_attrs)
        provenance_path = args[1] + ".provenance"
        if os.path.exists(provenance_path):
            shutil.move(provenance_path, dataset_attrs + ".provenance")
        shutil.move(args[2], job_attrs)

    # Create archive.
    return create_archive(temp_directory, out_file, gzip=gzip)


if __name__ == "__main__":
    main()
