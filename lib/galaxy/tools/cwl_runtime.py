"""CWL runtime utilities.

- Runtimeify setup: wraps base ``setup_for_runtimeify`` callbacks to attach
  CWL-specific fields (secondary files, EDAM format URIs) to
  ``DataInternalJson`` objects.
- ``raw_to_galaxy()``: creates deferred HDAs/HDCAs from CWL File/Collection
  dicts (used by workflow runner and CWL parameter defaults).
"""

import json
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
from galaxy.tool_util_models.parameters import (
    CwlArrayParameterModel,
    CwlBooleanParameterModel,
    CwlDirectoryParameterModel,
    CwlFileParameterModel,
    CwlFloatParameterModel,
    CwlIntegerParameterModel,
    CwlRecordParameterModel,
    CwlStringParameterModel,
)
from galaxy.tools.runtime import setup_for_runtimeify
from galaxy.util.hash_util import HASH_NAMES

if TYPE_CHECKING:
    from galaxy.job_execution.compute_environment import ComputeEnvironment
    from galaxy.model import (
        History,
        HistoryItem,
        InpDataDictT,
    )
    from galaxy.structured_app import (
        MinimalApp,
        MinimalToolApp,
    )
    from galaxy.tools.runtime import InpDataCollectionsDictT


def _parse_scalar(content: str, item_type_param) -> Any:
    """Parse a string value from an HDA file into the appropriate CWL scalar type."""
    if isinstance(item_type_param, CwlIntegerParameterModel):
        return int(content)
    elif isinstance(item_type_param, CwlFloatParameterModel):
        return float(content)
    elif isinstance(item_type_param, CwlBooleanParameterModel):
        return content.lower() in ("true", "1")
    elif isinstance(item_type_param, CwlStringParameterModel):
        # Content stored via ObjectUploadTarget is JSON-encoded (expression.json),
        # so strings are wrapped in quotes with escape sequences. Unwrap if valid.
        try:
            decoded = json.loads(content)
            if isinstance(decoded, str):
                return decoded
        except (json.JSONDecodeError, ValueError):
            pass
        return content
    else:
        # For other types (Any, Union, etc.), try JSON parse, fall back to string
        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return content


def setup_for_cwl_runtimeify(
    app: "MinimalToolApp",
    compute_environment: Optional["ComputeEnvironment"],
    input_datasets: "InpDataDictT",
    input_dataset_collections: Optional["InpDataCollectionsDictT"] = None,
    extra_hda_id_mappings: Optional[dict[int, "HistoryDatasetAssociation"]] = None,
):
    """CWL-enriched version of :func:`setup_for_runtimeify`.

    Wraps the base ``adapt_dataset`` callback to enrich ``DataInternalJson``
    with secondary files and CWL format URIs before returning.

    Returns ``(hda_references, adapt_dataset, adapt_collection, adapt_cwl_collection)``.
    """
    hda_references, base_adapt_dataset, adapt_collection = setup_for_runtimeify(
        app,
        compute_environment,
        input_datasets,
        input_dataset_collections,
        extra_hda_id_mappings=extra_hda_id_mappings,
    )

    hdas_by_id = {
        d.id: d for d in input_datasets.values() if d is not None and isinstance(d, HistoryDatasetAssociation)
    }
    # Include extra mappings for deferred->materialized datasets
    if extra_hda_id_mappings:
        for original_id, hda in extra_hda_id_mappings.items():
            if original_id not in hdas_by_id:
                hdas_by_id[original_id] = hda
    hdcas_by_id: dict[int, HistoryDatasetCollectionAssociation] = {}
    if input_dataset_collections:
        for value in input_dataset_collections.values():
            if isinstance(value, HistoryDatasetCollectionAssociation):
                hdcas_by_id[value.id] = value

    def adapt_dataset(value):
        base_result = base_adapt_dataset(value)
        hda = hdas_by_id.get(value.id)
        if hda is None:
            return base_result

        # For directory-type HDAs, cwltool needs the extra_files directory
        # (where actual contents are stored), not the primary .dat file.
        if hda.extension == "directory":
            base_result.path = hda.dataset.extra_files_path

        # Enrich with secondary files
        secondary_files = discover_secondary_files(hda, compute_environment)
        if secondary_files:
            base_result.secondaryFiles = secondary_files

        # Enrich with CWL format URI (replace Galaxy extension with EDAM URI)
        if hasattr(hda, "cwl_formats") and hda.cwl_formats:
            base_result.format = str(hda.cwl_formats[0])

        return base_result

    def _hda_to_cwl_file(hda):
        """Build CWL File/Directory dict directly from an HDA."""
        from galaxy.tool_util.cwl.util import set_basename_and_derived_properties as set_props

        size = hda.dataset.get_size() if hda.dataset else 0
        path = compute_environment.input_path_rewrite(hda) if compute_environment else hda.get_file_name()
        properties: dict[str, Any] = {
            "class": "File",
            "location": f"step_input://collection_element_{hda.id}",
            "format": hda.extension,
            "path": path,
            "size": int(size),
        }
        set_props(properties, hda.dataset.created_from_basename or hda.name)
        # Enrich with secondary files
        secondary_files = discover_secondary_files(hda, compute_environment)
        if secondary_files:
            properties["secondaryFiles"] = secondary_files
        # Enrich with CWL format URI
        if hasattr(hda, "cwl_formats") and hda.cwl_formats:
            properties["format"] = str(hda.cwl_formats[0])
        return properties

    def _adapt_element_hda(hda, item_type_param):
        """Adapt an HDA from a collection element to CWL native value."""
        if isinstance(item_type_param, (CwlFileParameterModel, CwlDirectoryParameterModel)):
            result = _hda_to_cwl_file(hda)
            if isinstance(item_type_param, CwlDirectoryParameterModel):
                result["class"] = "Directory"
            return result
        else:
            # Scalar value — read from HDA file content
            file_name = hda.get_file_name()
            with open(file_name) as f:
                content = f.read().strip()
            return _parse_scalar(content, item_type_param)

    def adapt_cwl_collection(ref, parameter):
        """Expand an HDCA reference to native CWL list or dict."""
        hdca = hdcas_by_id.get(ref.id)
        if hdca is None:
            raise ValueError(f"HDCA {ref.id} not found for CWL collection expansion")
        collection = hdca.collection
        elements = sorted(collection.elements, key=lambda e: e.element_index or 0)

        if isinstance(parameter, CwlArrayParameterModel):
            return [_adapt_element_hda(e.element_object, parameter.item_type) for e in elements]
        elif isinstance(parameter, CwlRecordParameterModel):
            fields_by_name = {f.name: f for f in parameter.fields}
            result = {}
            for e in elements:
                identifier = e.element_identifier
                if identifier is None:
                    continue
                field_param = fields_by_name.get(identifier)
                if field_param is not None:
                    result[identifier] = _adapt_element_hda(e.element_object, field_param)
            return result
        else:
            raise ValueError(f"Unexpected parameter type for CWL collection expansion: {type(parameter)}")

    return hda_references, adapt_dataset, adapt_collection, adapt_cwl_collection


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
        # For deferred datasets that were materialized, secondary files may
        # not have been copied to the extra_files_path. Try to discover them
        # next to the source URI (the original CWL File location).
        return _discover_secondary_files_from_source(hda, compute_environment)

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


def _discover_secondary_files_from_source(
    hda: "HistoryDatasetAssociation",
    compute_environment: Optional["ComputeEnvironment"] = None,
) -> list[dict]:
    """Discover secondary files from the HDA's dataset source URI.

    For deferred datasets created via ``raw_to_galaxy()`` from CWL defaults,
    the secondary files were never copied into the extra_files_path. This
    fallback resolves them from the original ``file://`` source URI and
    provides direct paths to the files on disk.
    """
    dataset = hda.dataset
    if not dataset or not dataset.sources:
        return []

    source_uri = None
    for source in dataset.sources:
        if source.source_uri:
            source_uri = source.source_uri
            break
    if not source_uri:
        return []

    # Resolve to filesystem path
    if source_uri.startswith("file://"):
        source_path = source_uri[len("file://") :]
    else:
        source_path = source_uri

    if not os.path.exists(source_path):
        return []

    # Look for secondary files next to the source file
    source_dir = os.path.dirname(source_path)
    source_basename = os.path.basename(source_path)
    secondary_files: list[dict] = []

    for name in sorted(os.listdir(source_dir)):
        # Secondary files match patterns like "{basename}.ext" where ext is
        # appended to the primary basename. Common patterns: .2, .bai, .idx
        if name != source_basename and name.startswith(source_basename):
            sf_source = os.path.join(source_dir, name)
            sf_suffix = name[len(source_basename) :]
            sf_basename = (dataset.created_from_basename or hda.name) + sf_suffix
            is_dir = os.path.isdir(sf_source)

            entry = {
                "class": "Directory" if is_dir else "File",
                "path": sf_source,
                "basename": sf_basename,
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

        # Always set created_from_basename for CWL datasets so that the
        # basename is preserved after deferred materialization.
        dataset.created_from_basename = as_dict_value.get("created_from_basename") or name

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
