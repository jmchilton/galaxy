"""Fixtures for populating model stores."""
from typing import Any, Dict
from uuid import uuid4

from galaxy.model.orm.now import now

TEST_SOURCE_URI = "https://raw.githubusercontent.com/galaxyproject/galaxy/dev/test-data/2.bed"
TEST_HASH_FUNCTION = "MD5"
TEST_HASH_VALUE = "moocowpretendthisisahas"
TEST_EXTENSION = "bed"


def one_hda_model_store_dict():
    dataset_hash = dict(
        model_class="DatasetHash",
        hash_function=TEST_HASH_FUNCTION,
        hash_value=TEST_HASH_VALUE,
        extra_files_path=None,
    )
    dataset_source: Dict[str, Any] = dict(
        model_class="DatasetSource",
        source_uri=TEST_SOURCE_URI,
        extra_files_path=None,
        transform=None,
        hashes=[],
    )
    metadata = {
        'dbkey': '?',
    }
    file_metadata = dict(
        hashes=[dataset_hash],
        sources=[dataset_source],
        created_from_basename="dataset.txt",
    )
    serialized_hda = dict(
        encoded_id="id_hda1",
        model_class="HistoryDatasetAssociation",
        create_time=now().__str__(),
        update_time=now().__str__(),
        name="my cool name",
        info="my cool info",
        blurb="a blurb goes here...",
        peek="A bit of the data...",
        extension=TEST_EXTENSION,
        metadata=metadata,
        designation=None,
        deleted=False,
        visible=True,
        dataset_uuid=str(uuid4()),
        annotation="my cool annotation",
        file_metadata=file_metadata,
    )

    return {
        'datasets': [
            serialized_hda,
        ]
    }


def deferred_hda_model_store_dict():
    dataset_hash = dict(
        model_class="DatasetHash",
        hash_function=TEST_HASH_FUNCTION,
        hash_value=TEST_HASH_VALUE,
        extra_files_path=None,
    )
    dataset_source: Dict[str, Any] = dict(
        model_class="DatasetSource",
        source_uri=TEST_SOURCE_URI,
        extra_files_path=None,
        transform=None,
        hashes=[],
    )
    metadata = {
        'dbkey': '?',
    }
    file_metadata = dict(
        hashes=[dataset_hash],
        sources=[dataset_source],
        created_from_basename="dataset.txt",
    )
    serialized_hda = dict(
        encoded_id="id_hda1",
        model_class="HistoryDatasetAssociation",
        create_time=now().__str__(),
        update_time=now().__str__(),
        name="my cool name",
        info="my cool info",
        blurb="a blurb goes here...",
        peek="A bit of the data...",
        extension=TEST_EXTENSION,
        metadata=metadata,
        designation=None,
        deleted=False,
        visible=True,
        dataset_uuid=str(uuid4()),
        annotation="my cool annotation",
        file_metadata=file_metadata,
        state='deferred',
    )

    return {
        'datasets': [
            serialized_hda,
        ]
    }
