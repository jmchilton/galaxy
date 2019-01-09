#!/usr/bin/env python
"""
Export a history to an archive file using attribute files.

usage: %prog history_attrs dataset_attrs job_attrs out_file
    -G, --gzip: gzip archive file
"""
from __future__ import print_function

import optparse
import os
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
    dataset_file_name = dataset_attrs['file_name']  # Full file name.
    arcname = os.path.join(dir_name, arcname)
    history_archive.add(dataset_file_name, arcname=arcname)
    dataset_attrs['file_name'] = arcname

    # Include additional files for example, files/images included in HTML output.
    extra_files_path = dataset_attrs['extra_files_path']
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


def create_archive(history_attrs_file, datasets_attrs_file, jobs_attrs_file, collections_attrs_file, out_file, gzip=False):
    """Create archive from the given attribute/metadata files and save it to out_file."""
    tarfile_mode = "w"
    if gzip:
        tarfile_mode += ":gz"
    try:

        history_archive = tarfile.open(out_file, tarfile_mode)

        datasets_attrs = read_attributes_from_file(datasets_attrs_file)

        # Add datasets to archive and update dataset attributes.
        # TODO: security check to ensure that files added are in Galaxy dataset directory?
        for dataset_attrs in datasets_attrs:
            if dataset_attrs['exported']:
                dataset_hid = dataset_attrs['hid']
                dataset_archive_name = get_dataset_filename(dataset_attrs['name'], dataset_attrs['extension'], dataset_hid)
                store_to_archive_and_rewrite(dataset_attrs, history_archive, dataset_archive_name, 'datasets', dataset_hid)

        # Rewrite dataset attributes file.
        with open(datasets_attrs_file, 'w') as datasets_attrs_out:
            dump(datasets_attrs, datasets_attrs_out)

        if collections_attrs_file:
            collections_attrs = read_attributes_from_file(collections_attrs_file)

            # Add collections datasets to archive and update dataset attributes.
            for collection_attrs in collections_attrs:
                for collection_element in collection_attrs['elements']:
                    if 'hda' in collection_element:
                        collection_dataset_attrs = collection_element['hda']

                        encoded_id = collection_dataset_attrs['encoded_id']
                        dataset_archive_name = get_dataset_filename(collection_dataset_attrs['name'], collection_dataset_attrs['extension'], encoded_id)
                        store_to_archive_and_rewrite(collection_dataset_attrs, history_archive, dataset_archive_name, 'collections_datasets', encoded_id)

                    # TODO: handle recursive datasets...

            # Rewrite collection attributes file.
            with open(collections_attrs_file, 'w') as collections_datasets_attrs_out:
                dump(collections_attrs, collections_datasets_attrs_out)

        # Finish archive.
        history_archive.add(history_attrs_file, arcname="history_attrs.txt")
        history_archive.add(datasets_attrs_file, arcname="datasets_attrs.txt")
        if os.path.exists(datasets_attrs_file + ".provenance"):
            history_archive.add(datasets_attrs_file + ".provenance", arcname="datasets_attrs.txt.provenance")
        if collections_attrs_file and os.path.exists(collections_attrs_file):
            history_archive.add(collections_attrs_file, arcname="collections_attrs.txt")
        history_archive.add(jobs_attrs_file, arcname="jobs_attrs.txt")
        history_archive.close()

        # Status.
        print('Created history archive.')
    except Exception as e:
        print('Error creating history archive: %s' % str(e), file=sys.stderr)


def main():
    # Parse command line.
    parser = optparse.OptionParser()
    parser.add_option('-G', '--gzip', dest='gzip', action="store_true", help='Compress archive using gzip.')
    (options, args) = parser.parse_args()
    gzip = bool(options.gzip)
    if len(args) == 2:
        # We have a 19.0X directory argument instead of individual arguments.
        temp_directory, out_file = args
        history_attrs = os.path.join(temp_directory, 'history_attrs.txt')
        dataset_attrs = os.path.join(temp_directory, 'datasets_attrs.txt')
        job_attrs = os.path.join(temp_directory, 'jobs_attrs.txt')
        collection_attrs = os.path.join(temp_directory, 'collections_attrs.txt')
    else:
        # This job was created pre 18.0X with old argument style.
        history_attrs, dataset_attrs, job_attrs, out_file = args
        collection_attrs = None

    # Create archive.
    create_archive(history_attrs, dataset_attrs, job_attrs, collection_attrs, out_file, gzip)


if __name__ == "__main__":
    main()
