"""The security review's reading of a dataset's members, against Galaxy's dataset model and datatypes."""

import pytest

from galaxy import model
from galaxy.datatypes.registry import example_datatype_registry_for_sample
from galaxy.model.metadata import FileParameter
from galaxy.tool_util.security.nodes import (
    Data,
    DATA_TEXT,
    galaxy_metadata,
    Metadata,
)
from galaxy.tool_util.security.values import CLEAN
from galaxy.tools.wrappers import (
    DatasetFilenameWrapper,
    DatasetListWrapper,
)

# The members of a dataset and of its wrappers that the review reads as values Galaxy sets: types, ids, paths,
# sizes, states, and methods that change the dataset or return none of its text.
GALAXY_SET = frozenset(
    (
        "add_item_annotation add_validation_error attach_implicitly_converted_dataset can_convert_to change_datatype"
        " clear_associated_files content_type conversion_messages convert_dataset"
        " copied_from_history_dataset_association_id copied_from_library_dataset_dataset_association_id"
        " copy_attributes copy_from copy_item_annotation copy_tags_from copy_tags_to create_time dataset_id"
        " datatype delete_item_annotation deleted dict_collection_visible_keys dict_element_visible_keys ext"
        " extend_validation_errors extended_metadata_id extension extra_files_path extra_files_path_exists"
        " get_converter_types get_file_name get_metadata_file_paths_and_extensions get_mime get_object_store_id"
        " get_quota_source_label get_size get_total_size has_data has_deferred_data has_metadata_files hid"
        " hidden_beneath_collection_instance_id history_content_type history_id id init_meta is_ok is_pending link_to"
        " mark_deleted mark_undeleted mark_unhidden metadata_deferred metadata_file_types missing_meta"
        " object_store_id ok_to_edit_metadata parent_id permitted_actions purge_usage_from_quota purged quota_amount"
        " quota_source_label seconds_since_created seconds_since_updated set_created_from_basename"
        " set_dbkey set_file_name set_meta set_metadata_requires_flush set_metadata_success_state set_peek set_size"
        " set_skipped set_total_size state states table touch_collection_update_time type_id undeletable"
        " unpause_dependent_jobs update update_time validated_state validated_states version visible"
        # DatasetFilenameWrapper and DatasetListWrapper.
        " MetadataWrapper all_metadata_files datatypes_registry false_path file_ext file_name get_display_text"
        " has_single_item is_collection is_deferred is_of_type job_working_directory paths_as_file"
        " _DatasetFilenameWrapper__io_type _path_or_uri append clear count extend index insert remove reverse sort"
    ).split()
)
# Members the review reads by a rule of their own: identifiers, tags, metadata, the model, other datasets.
OWN_READING = frozenset(
    (
        "element_identifier _element_identifier name_and_ext get_staging_path serialize groups metadata unsanitized"
        " dataset single_item get_datasets_for_group pop _dataset_elements_cache _dataset_wrapper"
    ).split()
)


def _hda() -> model.HistoryDatasetAssociation:
    return model.HistoryDatasetAssociation(name="reads", extension="txt")


def _wrapper() -> DatasetFilenameWrapper:
    return DatasetFilenameWrapper(_hda())


def _members() -> set[str]:
    """The names a template can read of a dataset input: of the model, through the wrapper, and of the
    wrappers themselves, with their instance attributes; not Python's own `__x__` names."""
    names = {name for name in dir(model.HistoryDatasetAssociation) if not name.startswith("_")}
    for wrapper in (_wrapper(), DatasetListWrapper(None, [_hda()])):
        names.update(name for name in dir(wrapper) if not (name.startswith("__") and name.endswith("__")))
    return names - set(dir(object()))


def test_text_members_are_members_of_a_dataset():
    assert DATA_TEXT - _members() == set()


def test_every_member_of_a_dataset_is_classified():
    assert _members() - DATA_TEXT - GALAXY_SET - OWN_READING == set()
    assert DATA_TEXT & GALAXY_SET == DATA_TEXT & OWN_READING == GALAXY_SET & OWN_READING == set()


def test_members_are_read_as_classified():
    data = Data("input", multiple=True)
    assert {name for name in GALAXY_SET if data.attr(name) is not CLEAN} == set()
    assert {name for name in DATA_TEXT if not (value := data.attr(name)) or not value.tainted} == set()
    assert {name for name in OWN_READING if data.attr(name) in (None, CLEAN)} == set()


@pytest.mark.parametrize("name", ["forward", "reverse", "replace", "tmp", "param_columns", "tabix_index"])
def test_a_name_a_dataset_does_not_have_fails(name):
    assert not hasattr(_wrapper(), name)
    assert Data("input").attr(name) is CLEAN


@pytest.mark.parametrize("name", ["name", "info", "creating_job", "history"])
def test_text_members_are_read_as_text(name):
    assert hasattr(_wrapper(), name)
    value = Data("input").attr(name)
    assert value is not None and value.tainted


def test_file_metadata_is_read_as_galaxy_paths():
    registry = example_datatype_registry_for_sample()
    files = {
        name
        for datatype in registry.datatypes_by_extension.values()
        for name, spec in datatype.metadata_spec.items()
        if isinstance(spec.param, FileParameter)
    }
    assert {"offsets", "tabix_index", "bam_csi_index"} <= files
    data = Data("input")
    assert {
        name for name in files if not galaxy_metadata(name) or Metadata("input", data).attr(name) is not CLEAN
    } == set()
