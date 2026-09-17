import json
from pathlib import Path

import numpy
import pytest

from galaxy.datatypes.metadata import MetadataTempFile
from galaxy.datatypes.registry import example_datatype_registry_for_sample
from galaxy.metadata.model_facade import (
    MetadataDatasetStore,
    MetadataModelExportStore,
)
from galaxy.objectstore.unittest_utils import Config as ObjectStoreConfig


def test_metadata_dataset_store_supports_datatype_metadata(tmp_path):
    dataset_path = tmp_path / "dataset.fasta"
    dataset_path.write_text(">seq1\nGCTGCATG\n")
    store_path = tmp_path / "store"
    store_path.mkdir()
    attributes = [
        {
            "id": 1,
            "model_class": "HistoryDatasetAssociation",
            "extension": "fasta",
            "metadata": {"data_lines": 0, "dbkey": "?", "sequences": 0},
            "dataset": {
                "id": 2,
                "external_filename": str(dataset_path),
                "_extra_files_path": None,
                "file_size": None,
                "total_size": None,
                "state": "ok",
            },
        }
    ]
    (store_path / "datasets_attrs.txt").write_text(json.dumps(attributes))

    store = MetadataDatasetStore.from_directory(store_path, example_datatype_registry_for_sample())
    dataset = store.find(1)
    assert dataset

    dataset.datatype.set_meta(dataset)

    assert dataset.metadata.data_lines == 2
    assert dataset.metadata.sequences == 1
    assert json.loads(dataset.metadata.to_JSON_dict()) == {"data_lines": 2, "dbkey": "?", "sequences": 1}


def test_metadata_dataset_store_initializes_metadata_after_sniffing(tmp_path):
    dataset_path = tmp_path / "dataset.fasta"
    dataset_path.write_text(">seq1\nGCTGCATG\n")
    store_path = tmp_path / "store"
    store_path.mkdir()
    (store_path / "datasets_attrs.txt").write_text("[]")
    registry = example_datatype_registry_for_sample()
    store = MetadataDatasetStore.from_directory(store_path, registry)

    dataset = store.create(
        registry,
        extension="_sniff_",
        designation="one",
        visible=True,
        dbkey="?",
        name="one",
    )
    dataset.link_to(str(dataset_path))
    dataset.set_meta()

    assert dataset.extension == "fasta"
    assert dataset.metadata.data_lines == 2
    assert dataset.metadata.sequences == 1


def test_metadata_dataset_store_rejects_non_hda(tmp_path):
    (tmp_path / "datasets_attrs.txt").write_text(
        json.dumps([{"id": 1, "model_class": "LibraryDatasetDatasetAssociation"}])
    )

    with pytest.raises(ValueError, match="HistoryDatasetAssociation"):
        MetadataDatasetStore.from_directory(tmp_path, example_datatype_registry_for_sample())


def test_model_facade_exports_mutated_dataset_and_job(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    attributes = {
        "id": 1,
        "model_class": "HistoryDatasetAssociation",
        "extension": "fasta",
        "metadata": {"data_lines": 0, "dbkey": "?", "sequences": 0},
        "state": "new",
        "dataset": {
            "id": 2,
            "external_filename": None,
            "_extra_files_path": None,
            "file_size": None,
            "total_size": None,
            "state": "new",
        },
    }
    (source / "datasets_attrs.txt").write_text(json.dumps([attributes]))
    (source / "jobs_attrs.txt").write_text(json.dumps([{"id": 1, "state": "new"}]))
    (source / "collections_attrs.txt").write_text("[]")

    export_store = MetadataModelExportStore(source, destination, example_datatype_registry_for_sample())
    dataset = export_store.datasets.find(1)
    export_store.add_dataset(dataset)
    dataset.state = "ok"
    dataset.metadata.sequences = 3
    assert export_store.job is not None
    export_store.job.state = "ok"
    export_store.job.set_streams("stdout", "stderr")
    export_store._finalize()

    exported_dataset = json.loads((destination / "datasets_attrs.txt").read_text())[0]
    exported_job = json.loads((destination / "jobs_attrs.txt").read_text())[0]
    assert exported_dataset["state"] == "ok"
    assert exported_dataset["dataset"]["state"] == "ok"
    assert exported_dataset["metadata"]["sequences"] == 3
    assert exported_job["state"] == "ok"
    assert exported_job["tool_stdout"] == "stdout"


def test_model_facade_stages_metadata_files_for_host_import(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    attributes = {
        "id": 1,
        "model_class": "HistoryDatasetAssociation",
        "extension": "bam",
        "metadata": {"dbkey": "?"},
        "dataset": {"id": 2, "state": "ok"},
    }
    input_attributes = {
        "id": 3,
        "model_class": "HistoryDatasetAssociation",
        "extension": "bam",
        "metadata": {"dbkey": "?"},
        "dataset": {"id": 4, "state": "ok"},
    }
    (source / "datasets_attrs.txt").write_text(json.dumps([input_attributes, attributes]))
    (source / "export_attrs.txt").write_text('{"galaxy_export_version": "2"}')
    (source / "history_attrs.txt").write_text('{"name": "input snapshot"}')
    (source / "metadata_files").mkdir()
    (source / "metadata_files" / "input-only.dat").write_text("unregistered metadata")
    (source / "collections_attrs.txt").write_text("[]")
    (source / "jobs_attrs.txt").write_text("[]")

    metadata_file = MetadataTempFile(metadata_tmp_files_dir=str(tmp_path))
    with open(metadata_file.get_file_name(), "w") as handle:
        handle.write("index contents")

    export_store = MetadataModelExportStore(source, destination, example_datatype_registry_for_sample())
    dataset = export_store.datasets.find(1)
    export_store.add_dataset(dataset)
    dataset.metadata.bam_index = metadata_file
    input_dataset = export_store.datasets.find(3)
    assert input_dataset is not None
    input_metadata_file = MetadataTempFile(metadata_tmp_files_dir=str(tmp_path))
    Path(input_metadata_file.get_file_name()).write_text("input index")
    input_dataset.metadata.bam_index = input_metadata_file
    export_store.push_metadata_files()
    export_store._finalize()

    exported_datasets = json.loads((destination / "datasets_attrs.txt").read_text())
    assert [dataset["id"] for dataset in exported_datasets] == [1]
    assert input_dataset.metadata.bam_index is input_metadata_file
    assert not (destination / "history_attrs.txt").exists()
    assert not (destination / "metadata_files" / "input-only.dat").exists()
    assert (destination / "export_attrs.txt").read_bytes() == (source / "export_attrs.txt").read_bytes()
    assert len(list((destination / "metadata_files").iterdir())) == 1
    exported_metadata = exported_datasets[0]["metadata"]
    serialized_file = exported_metadata["bam_index"]
    assert serialized_file["model_class"] == "MetadataFile"
    assert serialized_file["name"] == "bam_index"
    assert (destination / serialized_file["file_name"]).read_text() == "index contents"


def test_model_facade_preserves_existing_metadata_file_identity(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    existing_file = tmp_path / "existing-index.dat"
    existing_file.write_text("existing index")
    metadata_file_uuid = "0e733c13-bdee-4fb0-8d4a-217902850c00"
    attributes = {
        "id": 1,
        "model_class": "HistoryDatasetAssociation",
        "extension": "bam",
        "metadata": {
            "dbkey": "?",
            "bam_index": {
                "id": 3,
                "model_class": "MetadataFile",
                "name": "bam_index",
                "uuid": metadata_file_uuid,
            },
        },
        "dataset": {"id": 2, "uuid": "3a103b03-d34c-4a3c-89b7-701d7004ecaa", "state": "ok"},
    }
    (source / "datasets_attrs.txt").write_text(json.dumps([attributes]))
    (source / "collections_attrs.txt").write_text("[]")
    (source / "jobs_attrs.txt").write_text("[]")

    with ObjectStoreConfig(store_by="uuid") as (_, object_store):
        export_store = MetadataModelExportStore(
            source,
            destination,
            example_datatype_registry_for_sample(),
            object_store=object_store,
        )
        export_store.add_dataset(export_store.datasets.find(1))
        metadata_file = export_store.datasets.find(1).metadata.bam_index
        object_store.update_from_file(
            metadata_file,
            file_name=str(existing_file),
            extra_dir="_metadata_files",
            extra_dir_at_root=True,
            alt_name=f"metadata_{metadata_file_uuid}.dat",
            create=True,
        )
        assert metadata_file.uuid == metadata_file_uuid
        assert metadata_file.name == "bam_index"
        assert Path(metadata_file.get_file_name()).read_text() == "existing index"
        export_store.push_metadata_files()
        export_store._finalize()

    serialized_file = json.loads((destination / "datasets_attrs.txt").read_text())[0]["metadata"]["bam_index"]
    assert serialized_file["uuid"] == metadata_file_uuid
    assert (destination / serialized_file["file_name"]).read_text() == "existing index"


def test_model_facade_exports_mutated_dataset_collection(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    dataset_attributes = {
        "id": 1,
        "model_class": "HistoryDatasetAssociation",
        "extension": "txt",
        "metadata": {"dbkey": "?"},
        "dataset": {"id": 2, "state": "ok"},
    }
    collection_attributes = {
        "id": 3,
        "model_class": "HistoryDatasetCollectionAssociation",
        "display_name": "output",
        "collection": {
            "id": 4,
            "model_class": "DatasetCollection",
            "type": "list",
            "populated_state": "new",
            "populated_state_message": None,
            "elements": [
                {
                    "model_class": "DatasetCollectionElement",
                    "element_index": 0,
                    "element_identifier": "one",
                    "hda": {"id": 1, "model_class": "HistoryDatasetAssociation"},
                }
            ],
        },
    }
    (source / "datasets_attrs.txt").write_text(json.dumps([dataset_attributes]))
    (source / "collections_attrs.txt").write_text(json.dumps([collection_attributes]))
    (source / "jobs_attrs.txt").write_text("[]")

    export_store = MetadataModelExportStore(source, destination, example_datatype_registry_for_sample())
    hdca = export_store.dataset_collections.find(3)
    assert hdca.dataset_instances == [export_store.datasets.find(1)]

    export_store.add_dataset_collection(hdca)
    hdca.collection.mark_as_populated()
    export_store._finalize()

    exported_collection = json.loads((destination / "collections_attrs.txt").read_text())[0]["collection"]
    assert exported_collection["populated_state"] == "ok"
    assert exported_collection["element_count"] == 1
    assert [dataset["id"] for dataset in json.loads((destination / "datasets_attrs.txt").read_text())] == [1]


def test_model_facade_exports_mutated_bare_dataset_collection(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    dataset_attributes = {
        "id": 1,
        "model_class": "HistoryDatasetAssociation",
        "extension": "txt",
        "metadata": {"dbkey": "?"},
        "dataset": {"id": 2, "state": "ok"},
    }
    collection_attributes = {
        "id": 3,
        "model_class": "DatasetCollection",
        "type": "list",
        "populated_state": "new",
        "populated_state_message": None,
        "elements": [
            {
                "model_class": "DatasetCollectionElement",
                "element_index": 0,
                "element_identifier": "one",
                "hda": {"id": 1, "model_class": "HistoryDatasetAssociation"},
            }
        ],
    }
    (source / "datasets_attrs.txt").write_text(json.dumps([dataset_attributes]))
    (source / "collections_attrs.txt").write_text(json.dumps([collection_attributes]))
    (source / "jobs_attrs.txt").write_text("[]")

    export_store = MetadataModelExportStore(source, destination, example_datatype_registry_for_sample())
    collection = export_store.dataset_collections.find(3)
    assert collection.collection is collection
    assert collection.dataset_instances == [export_store.datasets.find(1)]

    export_store.add_dataset_collection(collection)
    collection.mark_as_populated()
    export_store._finalize()

    exported_collection = json.loads((destination / "collections_attrs.txt").read_text())[0]
    assert exported_collection["model_class"] == "DatasetCollection"
    assert "collection" not in exported_collection
    assert exported_collection["populated_state"] == "ok"
    assert exported_collection["element_count"] == 1
    assert [dataset["id"] for dataset in json.loads((destination / "datasets_attrs.txt").read_text())] == [1]


@pytest.mark.parametrize("association_state", ["failed_metadata", "setting_metadata"])
def test_model_facade_roundtrips_association_metadata_state(tmp_path, association_state):
    source = tmp_path / "source"
    source.mkdir()
    attributes = {
        "id": 1,
        "model_class": "HistoryDatasetAssociation",
        "extension": "txt",
        "metadata": {"dbkey": "?"},
        "state": association_state,
        "dataset": {"id": 2, "state": "ok"},
    }
    (source / "datasets_attrs.txt").write_text(json.dumps([attributes]))
    (source / "collections_attrs.txt").write_text("[]")
    (source / "jobs_attrs.txt").write_text("[]")
    store = MetadataModelExportStore(source, tmp_path / "destination", example_datatype_registry_for_sample())
    dataset = store.datasets.find(1)
    assert dataset.state == association_state
    dataset.state = "ok"
    dataset.state = association_state
    store.add_dataset(dataset)
    store._finalize()
    exported = json.loads((tmp_path / "destination" / "datasets_attrs.txt").read_text())[0]
    assert exported["state"] == association_state
    assert exported["dataset"]["state"] == "ok"


@pytest.mark.parametrize("original_dbkey", ["hg19", ["hg19"], None, []])
def test_model_facade_updates_genome_build(tmp_path, original_dbkey):
    source = tmp_path / "source"
    source.mkdir()
    attributes = {
        "id": 1,
        "model_class": "HistoryDatasetAssociation",
        "extension": "fasta",
        "metadata": {"dbkey": original_dbkey},
        "dataset": {"id": 2, "state": "ok"},
    }
    (source / "datasets_attrs.txt").write_text(json.dumps([attributes]))
    (source / "collections_attrs.txt").write_text("[]")
    (source / "jobs_attrs.txt").write_text("[]")
    store = MetadataModelExportStore(source, tmp_path / "destination", example_datatype_registry_for_sample())
    dataset = store.datasets.find(1)
    dataset.dbkey = "hg38"
    assert dataset.dbkey == "hg38"
    assert json.loads(dataset.metadata.to_JSON_dict())["dbkey"] == ["hg38"]
    store.add_dataset(dataset)
    store._finalize()
    exported = json.loads((tmp_path / "destination" / "datasets_attrs.txt").read_text())[0]
    assert exported["metadata"]["dbkey"] == ["hg38"]


def test_model_facade_serializes_numpy_metadata(tmp_path):
    from galaxy.datatypes.binary import Anndata

    source = tmp_path / "source"
    source.mkdir()
    attributes = {
        "id": 1,
        "model_class": "HistoryDatasetAssociation",
        "extension": "h5ad",
        "metadata": {},
        "dataset": {"id": 2, "state": "ok"},
    }
    (source / "datasets_attrs.txt").write_text(json.dumps([attributes]))
    (source / "collections_attrs.txt").write_text("[]")
    (source / "jobs_attrs.txt").write_text("[]")
    registry = example_datatype_registry_for_sample()
    registry.datatypes_by_extension["h5ad"] = Anndata()
    store = MetadataModelExportStore(source, tmp_path / "destination", registry)
    dataset = store.datasets.find(1)
    dataset.metadata.shape = (numpy.int64(50), numpy.int64(100))
    assert json.loads(dataset.metadata.to_JSON_dict())["shape"] == [50, 100]
    store.add_dataset(dataset)
    store._finalize()
    exported = json.loads((tmp_path / "destination" / "datasets_attrs.txt").read_text())[0]
    assert exported["metadata"]["shape"] == [50, 100]
