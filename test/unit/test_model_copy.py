import os
import threading

import galaxy.datatypes.registry
import galaxy.model
import galaxy.model.mapping as mapping
from galaxy.model.metadata import MetadataTempFile
from galaxy.util import ExecutionTimer

from .test_objectstore import DISK_TEST_CONFIG, TestConfig


datatypes_registry = galaxy.datatypes.registry.Registry()
datatypes_registry.load_datatypes()
galaxy.model.set_datatypes_registry(datatypes_registry)

NUM_DATASETS = 10
INCLUDE_METADATA_FILE = False


def test_history_copy(num_datasets=NUM_DATASETS, include_metadata_file=INCLUDE_METADATA_FILE):
    with TestConfig(DISK_TEST_CONFIG) as (test_config, object_store):
        # Start the database and connect the mapping
        thread_local_log = threading.local()
        model = mapping.init("/tmp", "sqlite:///:memory:", create_tables=True, object_store=object_store, slow_query_log_threshold=1000, thread_local_log=thread_local_log)

        u = model.User(email="historycopy@example.com", password="password")
        h1 = model.History(name="HistoryCopyHistory1", user=u)
        model.context.add_all([u, h1])
        model.context.flush()
        for i in range(num_datasets):
            o_metadata_path = os.path.join(test_config.temp_directory, "metadata_original_%d" % i)
            with open(o_metadata_path, "w") as f:
                f.write("moo")

            hda1 = model.HistoryDatasetAssociation(extension="bam", create_dataset=True, sa_session=model.context)
            model.context.add(hda1)
            model.context.flush([hda1])
            object_store.update_from_file(hda1, file_name=o_metadata_path, create=True)
            if include_metadata_file:
                hda1.metadata.from_JSON_dict(json_dict={"bam_index": MetadataTempFile.from_JSON({"kwds": {}, "filename": o_metadata_path})})
                _check_metadata_file(hda1)
            hda1.set_size()
            h1.add_dataset(hda1)
            hda1.add_item_annotation(model.context, u, hda1, "annotation #%d" % hda1.hid)

        model.context.flush()

        history_copy_timer = ExecutionTimer()
        new_history = h1.copy(target_user=u)
        print("history copied %s" % history_copy_timer)
        thread_local_log.log = False
        assert new_history.name == "HistoryCopyHistory1"
        model.context.refresh(new_history)
        for i, hda in enumerate(new_history.active_datasets):
            assert hda.get_size() == 3
            if include_metadata_file:
                _check_metadata_file(hda)
            annotation_str = hda.get_item_annotation_str(model.context, u, hda)
            assert annotation_str == "annotation #%d" % hda.hid, annotation_str


def _check_metadata_file(hda):
    assert hda.metadata.bam_index.id
    copied_index = hda.metadata.bam_index.file_name
    assert os.path.exists(copied_index)
    with open(copied_index, "r") as f:
        assert f.read() == "moo"
    assert copied_index.endswith("metadata_%d.dat" % hda.id)
