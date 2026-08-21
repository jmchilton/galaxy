"""Model-free helpers used while collecting job outputs."""

import logging
import os
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING

from galaxy.objectstore import (
    ObjectStore,
    persist_extra_files,
)
from galaxy.util import (
    shrink_and_unicodify,
    unicodify,
)

if TYPE_CHECKING:
    from galaxy.model import DatasetInstance

log = logging.getLogger(__name__)


def read_exit_code_from(exit_code_file, id_tag):
    """Read exit code reported for a Galaxy job."""
    try:
        # This should be an 8-bit exit code, but read ahead anyway:
        exit_code_str = open(exit_code_file).read(32)
    except Exception:
        # By default, the exit code is 0, which typically indicates success.
        exit_code_str = "0"

    try:
        # Decode the exit code. If it's bogus, then just use 0.
        exit_code = int(exit_code_str)
    except ValueError:
        galaxy_id_tag = id_tag
        log.warning(f"({galaxy_id_tag}) Exit code '{exit_code_str}' invalid. Using 0.")
        exit_code = 0

    return exit_code


def default_exit_code_file(files_dir, id_tag):
    return os.path.join(files_dir, f"galaxy_{id_tag}.ec")


def collect_extra_files(
    object_store: ObjectStore,
    dataset: "DatasetInstance",
    job_working_directory: str,
    outputs_to_working_directory: bool = False,
):
    # TODO: should this use compute_environment to determine the extra files path ?
    assert dataset.dataset
    real_file_name = file_name = dataset.dataset.extra_files_path_name_from(object_store)
    if outputs_to_working_directory:
        # OutputsToWorkingDirectoryPathRewriter always rewrites extra files to uuid path,
        # so we have to collect from that path even if the real extra files path is dataset_N_files
        file_name = f"dataset_{dataset.dataset.uuid}_files"
    output_location = "outputs"
    temp_file_path = os.path.join(job_working_directory, output_location, file_name)
    if not os.path.exists(temp_file_path):
        # Fall back to working dir, remove in 23.2
        output_location = "working"
        temp_file_path = os.path.join(job_working_directory, output_location, file_name)
    if not os.path.exists(temp_file_path):
        # no outputs to working directory, but may still need to push form cache to backend
        temp_file_path = dataset.extra_files_path
    try:
        # This skips creation of directories - object store automatically creates them.
        # However, empty directories will not be created in the object store at all.
        persist_extra_files(
            object_store=object_store,
            src_extra_files_path=temp_file_path,
            primary_data=dataset,
            extra_files_path_name=real_file_name,
        )
    except Exception as e:
        log.debug("Error in collect_associated_files: %s", unicodify(e))

    # Handle composite datatypes of auto_primary_file type
    if dataset.datatype.composite_type == "auto_primary_file" and not dataset.has_data():
        try:
            with NamedTemporaryFile(mode="w") as temp_fh:
                temp_fh.write(dataset.datatype.generate_primary_file(dataset))
                temp_fh.flush()
                object_store.update_from_file(dataset.dataset, file_name=temp_fh.name, create=True)
                dataset.set_size()
        except Exception as e:
            log.warning(
                "Unable to generate primary composite file automatically for %s: %s", dataset.dataset.id, unicodify(e)
            )


def collect_shrinked_content_from_path(path):
    try:
        with open(path, "rb") as fh:
            return shrink_and_unicodify(fh.read().strip())
    except FileNotFoundError:
        return None
