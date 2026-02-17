"""CWL-enriched runtimeify setup.

Wraps the base ``setup_for_runtimeify`` callbacks to attach CWL-specific
fields (secondary files, EDAM format URIs) to ``DataInternalJson`` objects
before they are converted to ``CwlFileRuntimeJson`` dicts by the runtimeify
visitor.
"""

import os
from typing import (
    Optional,
    TYPE_CHECKING,
)

from galaxy.tool_util.cwl.util import SECONDARY_FILES_EXTRA_PREFIX
from galaxy.tools.runtime import setup_for_runtimeify

if TYPE_CHECKING:
    from galaxy.job_execution.compute_environment import ComputeEnvironment
    from galaxy.model import HistoryDatasetAssociation
    from galaxy.tools.runtime import (
        InpDataCollectionsDictT,
        InpDataDictT,
        MinimalToolApp,
    )


def setup_for_cwl_runtimeify(
    app: "MinimalToolApp",
    compute_environment: Optional["ComputeEnvironment"],
    input_datasets: "InpDataDictT",
    input_dataset_collections: Optional["InpDataCollectionsDictT"] = None,
):
    """CWL-enriched version of :func:`setup_for_runtimeify`.

    Wraps the base ``adapt_dataset`` callback to enrich ``DataInternalJson``
    with secondary files and CWL format URIs before returning.

    Returns the same ``(hda_references, adapt_dataset, adapt_collection)``
    tuple as the base function.
    """
    hda_references, base_adapt_dataset, adapt_collection = setup_for_runtimeify(
        app, compute_environment, input_datasets, input_dataset_collections
    )

    hdas_by_id = {d.id: d for d in input_datasets.values() if d is not None}

    def adapt_dataset(value):
        base_result = base_adapt_dataset(value)
        hda = hdas_by_id.get(value.id)
        if hda is None:
            return base_result

        # Enrich with secondary files
        secondary_files = discover_secondary_files(hda, compute_environment)
        if secondary_files:
            base_result.secondaryFiles = secondary_files

        # Enrich with CWL format URI (replace Galaxy extension with EDAM URI)
        if hasattr(hda, "cwl_formats") and hda.cwl_formats:
            base_result.format = str(hda.cwl_formats[0])

        return base_result

    return hda_references, adapt_dataset, adapt_collection


def discover_secondary_files(
    hda: "HistoryDatasetAssociation",
    compute_environment: Optional["ComputeEnvironment"] = None,
) -> list[dict]:
    """Discover secondary files for an HDA.

    Looks in ``{extra_files_path}/__secondary_files__/`` for files and
    directories associated with the dataset.

    Returns a list of dicts with ``class``, ``path``, and ``basename`` keys,
    compatible with CWL File/Directory secondary file entries.  Returns an
    empty list when no secondary files directory exists.
    """
    extra_files_path = hda.extra_files_path
    secondary_files_dir = os.path.join(extra_files_path, SECONDARY_FILES_EXTRA_PREFIX)

    if not os.path.exists(secondary_files_dir):
        return []

    secondary_files: list[dict] = []
    for name in sorted(os.listdir(secondary_files_dir)):
        sf_path = os.path.join(secondary_files_dir, name)
        real_path = os.path.realpath(sf_path)
        is_dir = os.path.isdir(real_path)

        # For remote execution, rewrite the path via compute_environment.
        # input_path_rewrite expects a dataset object, so we construct the
        # path manually from the extra_files rewrite base.
        if compute_environment:
            extra_rewrite = compute_environment.input_extra_files_rewrite(hda)
            rewritten = os.path.join(extra_rewrite, SECONDARY_FILES_EXTRA_PREFIX, name)
        else:
            rewritten = sf_path

        entry = {
            "class": "Directory" if is_dir else "File",
            "path": rewritten,
            "basename": name,
        }
        secondary_files.append(entry)

    return secondary_files
