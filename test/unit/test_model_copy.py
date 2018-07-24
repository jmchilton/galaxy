import contextlib
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
SLOW_QUERY_LOG_THRESHOLD = 1000
INCLUDE_METADATA_FILE = True
THREAD_LOCAL_LOG = threading.local()


def test_history_dataset_copy(num_datasets=NUM_DATASETS, include_metadata_file=INCLUDE_METADATA_FILE):
    with setup_mapping_and_user() as (test_config, object_store, model, old_history):
        for i in range(num_datasets):
            o_metadata_path = test_config.write("moo", "test_metadata_original_%d" % i)
            hda1 = model.HistoryDatasetAssociation(extension="bam", create_dataset=True, sa_session=model.context)
            model.context.add(hda1)
            model.context.flush([hda1])
            object_store.update_from_file(hda1, file_name=o_metadata_path, create=True)
            if include_metadata_file:
                hda1.metadata.from_JSON_dict(json_dict={"bam_index": MetadataTempFile.from_JSON({"kwds": {}, "filename": o_metadata_path})})
                _check_metadata_file(hda1)
            hda1.set_size()
            old_history.add_dataset(hda1)
            hda1.add_item_annotation(model.context, old_history.user, hda1, "annotation #%d" % hda1.hid)

        model.context.flush()

        history_copy_timer = ExecutionTimer()
        new_history = old_history.copy(target_user=old_history.user)
        print("history copied %s" % history_copy_timer)
        assert new_history.name == "HistoryCopyHistory1"
        assert new_history.user == old_history.user
        for i, hda in enumerate(new_history.active_datasets):
            assert hda.get_size() == 3
            if include_metadata_file:
                _check_metadata_file(hda)
            annotation_str = hda.get_item_annotation_str(model.context, old_history.user, hda)
            assert annotation_str == "annotation #%d" % hda.hid, annotation_str


@contextlib.contextmanager
def setup_mapping_and_user():
    with TestConfig(DISK_TEST_CONFIG) as (test_config, object_store):
        # Start the database and connect the mapping
        model = mapping.init("/tmp", "sqlite:///:memory:", create_tables=True, object_store=object_store, slow_query_log_threshold=SLOW_QUERY_LOG_THRESHOLD, thread_local_log=THREAD_LOCAL_LOG)

        u = model.User(email="historycopy@example.com", password="password")
        h1 = model.History(name="HistoryCopyHistory1", user=u)
        model.context.add_all([u, h1])
        model.context.flush()
        yield test_config, object_store, model, h1


def _check_metadata_file(hda):
    assert hda.metadata.bam_index.id
    copied_index = hda.metadata.bam_index.file_name
    assert os.path.exists(copied_index)
    with open(copied_index, "r") as f:
        assert f.read() == "moo"
    assert copied_index.endswith("metadata_%d.dat" % hda.id)
