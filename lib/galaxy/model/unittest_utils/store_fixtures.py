"""Fixtures for populating model stores."""
from typing import Any, Dict
from uuid import uuid4

from galaxy.model.orm.now import now

TEST_SOURCE_URI = "https://raw.githubusercontent.com/galaxyproject/galaxy/dev/test-data/2.bed"
TEST_HASH_FUNCTION = "MD5"
TEST_HASH_VALUE = "moocowpretendthisisahas"
TEST_EXTENSION = "bed"
TEST_LIBRARY_NAME = 'My cool library'
TEST_LIBRARY_DESCRIPTION = 'My cool library - a description'
TEST_LIBRARY_SYNOPSIS = 'My cool library - a synopsis'
TEST_ROOT_FOLDER_NAME = 'The root folder'
TEST_ROOT_FOLDER_DESCRIPTION = 'The root folder description'
TEST_LDDA_ID = "id_ldda1"
TEST_LIBRARY_ID = "id_library1"
TEST_LIBRARY_DATASET_NAME = 'my cool library dataset'
TEST_LIBRARY_DATASET_INFO = 'important info about the library dataset'


def one_ld_library_model_store_dict():
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
    serialized_ldda = dict(
        encoded_id=TEST_LDDA_ID,
        model_class="LibraryDatasetDatasetAssociation",
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

    ld = {
        'name': TEST_LIBRARY_DATASET_NAME,
        'info': TEST_LIBRARY_DATASET_INFO,
        'order_id': 0,
        'ldda': {
            'model_class': "LibraryDatasetDatasetAssocation",
            'encoded_id': TEST_LDDA_ID,
        },
    }

    root_folder: Dict[str, Any] = {
        'name': TEST_ROOT_FOLDER_NAME,
        'description': TEST_ROOT_FOLDER_DESCRIPTION,
        'genome_build': None,
        'deleted': False,
        'folders': [],
        'datasets': [ld],
    }
    serialized_library = {
        'encoded_id': TEST_LIBRARY_ID,
        'name': TEST_LIBRARY_NAME,
        'description': TEST_LIBRARY_DESCRIPTION,
        'synopsis': TEST_LIBRARY_SYNOPSIS,
        'root_folder': root_folder,
    }
    return {
        'libraries': [
            serialized_library,
        ],
        'datasets': [
            serialized_ldda,
        ]
    }


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
