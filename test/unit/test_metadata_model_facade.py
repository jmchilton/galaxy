import json

from galaxy.datatypes.registry import example_datatype_registry_for_sample
from galaxy.metadata.model_facade import (
    MetadataDatasetStore,
    MetadataModelExportStore,
)


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


def test_metadata_dataset_store_rejects_non_hda(tmp_path):
    (tmp_path / "datasets_attrs.txt").write_text(
        json.dumps([{"id": 1, "model_class": "LibraryDatasetDatasetAssociation"}])
    )

    try:
        MetadataDatasetStore.from_directory(tmp_path, example_datatype_registry_for_sample())
    except ValueError as exc:
        assert "HistoryDatasetAssociation" in str(exc)
    else:
        raise AssertionError("Expected unsupported model class to be rejected")


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
    dataset.state = "ok"
    dataset.metadata.sequences = 3
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

    hdca.collection.mark_as_populated()
    export_store._finalize()

    exported_collection = json.loads((destination / "collections_attrs.txt").read_text())[0]["collection"]
    assert exported_collection["populated_state"] == "ok"
    assert exported_collection["element_count"] == 1
