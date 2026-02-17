"""CWL runtime utilities.

- Runtimeify setup: wraps base ``setup_for_runtimeify`` callbacks to attach
  CWL-specific fields (secondary files, EDAM format URIs) to
  ``DataInternalJson`` objects.
- ``raw_to_galaxy()``: creates deferred HDAs/HDCAs from CWL File/Collection
  dicts (used by workflow runner and CWL parameter defaults).
"""

import os
import urllib.parse
from typing import (
    Any,
    Optional,
    TYPE_CHECKING,
)

from galaxy.model import (
    Dataset,
    DatasetCollection,
    DatasetHash,
    DatasetSource,
    HistoryDatasetAssociation,
    HistoryDatasetCollectionAssociation,
)
from galaxy.model.dataset_collections import builder
from galaxy.tool_util.cwl.util import SECONDARY_FILES_EXTRA_PREFIX
from galaxy.tools.runtime import setup_for_runtimeify
from galaxy.util.hash_util import HASH_NAMES

if TYPE_CHECKING:
    from galaxy.job_execution.compute_environment import ComputeEnvironment
    from galaxy.model import (
        History,
        HistoryItem,
    )
    from galaxy.structured_app import MinimalApp
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


def raw_to_galaxy(
    app: "MinimalApp", history: "History", as_dict_value: dict[str, Any], commit: bool = True
) -> "HistoryItem":
    """Create a deferred HDA or HDCA from a CWL File/Collection dict.

    Used by the workflow runner for valueFrom expression results and by CWL
    parameter defaults.
    """
    object_class = as_dict_value["class"]
    if object_class == "File":
        # TODO: relative_to = "/"
        location = as_dict_value.get("location") or as_dict_value.get("path")
        assert location
        assert os.path.exists(location[len("file://")])
        name = (
            as_dict_value.get("identifier")
            or as_dict_value.get("basename")
            or os.path.basename(urllib.parse.urlparse(location).path)
        )
        extension = as_dict_value.get("format") or "data"
        dataset = Dataset()
        source = DatasetSource()
        source.source_uri = location
        # TODO: validate this...
        source.requested_transform = as_dict_value.get("transform")
        dataset.sources.append(source)

        for hash_name in HASH_NAMES:
            # TODO: Convert md5 -> MD5 during tool parsing.
            if hash_name in as_dict_value:
                hash_object = DatasetHash()
                hash_object.hash_function = hash_name
                hash_object.hash_value = as_dict_value[hash_name]
                dataset.hashes.append(hash_object)

        if "created_from_basename" in as_dict_value:
            dataset.created_from_basename = as_dict_value["created_from_basename"]

        dataset.state = Dataset.states.DEFERRED
        primary_data = HistoryDatasetAssociation(
            name=name,
            extension=extension,
            metadata_deferred=True,
            designation=None,
            visible=True,
            dbkey="?",
            dataset=dataset,
            flush=False,
            sa_session=app.model.session,
        )
        primary_data.state = Dataset.states.DEFERRED
        permissions = app.security_agent.history_get_default_permissions(history)
        app.security_agent.set_all_dataset_permissions(primary_data.dataset, permissions, new=True, flush=False)
        app.model.session.add(primary_data)
        history.stage_addition(primary_data)
        history.add_pending_items()
        if commit:
            app.model.session.commit()
        return primary_data
    else:
        name = as_dict_value.get("name")
        collection_type = as_dict_value.get("collection_type")
        collection = DatasetCollection(
            collection_type=collection_type,
        )
        hdca = HistoryDatasetCollectionAssociation(
            name=name,
            collection=collection,
        )
        app.model.session.add(hdca)

        def write_elements_to_collection(has_elements, collection_builder):
            element_dicts = has_elements.get("elements")
            for element_dict in element_dicts:
                element_class = element_dict["class"]
                identifier = element_dict["identifier"]
                if element_class == "File":
                    # Don't commit for inner elements
                    hda = raw_to_galaxy(app, history, element_dict, commit=False)
                    collection_builder.add_dataset(identifier, hda)
                else:
                    subcollection_builder = collection_builder.get_level(identifier)
                    write_elements_to_collection(element_dict, subcollection_builder)

        collection_builder = builder.BoundCollectionBuilder(collection)
        write_elements_to_collection(as_dict_value, collection_builder)
        collection_builder.populate()
        history.stage_addition(hdca)
        history.add_pending_items()
        if commit:
            app.model.session.commit()
        return hdca
