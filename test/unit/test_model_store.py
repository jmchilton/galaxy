import json
import os
from tempfile import mkdtemp

from galaxy import model
from galaxy.model import store
from galaxy.tools.imp_exp import export_history, unpack_tar_gz_archive
from .tools.test_history_imp_exp import _mock_app, Dummy


def test_import_export_history():
    dest_parent = mkdtemp()
    dest_export = os.path.join(dest_parent, "moo.tgz")

    app = _mock_app()
    sa_session = app.model.context

    u = model.User(email="collection@example.com", password="password")
    h = model.History(name="Test History", user=u)

    d1 = model.HistoryDatasetAssociation(extension="txt", history=h, create_dataset=True, sa_session=sa_session)
    d2 = model.HistoryDatasetAssociation(extension="txt", history=h, create_dataset=True, sa_session=sa_session)

    j = model.Job()
    j.user = u
    j.tool_id = "cat1"

    j.add_input_dataset("input1", d1)
    j.add_output_dataset("out_file1", d2)

    sa_session.add(d1)
    sa_session.add(d2)
    sa_session.add(h)
    sa_session.add(j)
    sa_session.flush()

    imported_history = _import_export_history(app, h, dest_export)

    assert imported_history.name == "imported from archive: Test History"

    datasets = imported_history.datasets
    assert len(datasets) == 2
    imported_job = datasets[1].creating_job
    assert imported_job
    assert imported_job.output_datasets
    assert imported_job.output_datasets[0].dataset == datasets[1]

    assert imported_job.input_datasets
    assert imported_job.input_datasets[0].dataset == datasets[0]


def test_import_export_datasets():
    app, h, temp_directory, import_history = _setup_simple_export({"for_edit": False})
    u = h.user

    import_model_store = store.get_import_model_store(app, u, temp_directory)
    with import_model_store.target_history(default_history=import_history):
        import_model_store.perform_import(None, import_history)

    datasets = import_history.datasets
    assert len(datasets) == 2
    imported_job = datasets[1].creating_job
    assert imported_job
    assert imported_job.output_datasets
    assert imported_job.output_datasets[0].dataset == datasets[1]

    assert imported_job.input_datasets
    assert imported_job.input_datasets[0].dataset == datasets[0]


def test_import_export_edit_datasets():
    app, h, temp_directory, import_history = _setup_simple_export({"for_edit": True})
    u = h.user

    # Fabric editing metadata...
    datasets_metadata_path = os.path.join(temp_directory, store.ATTRS_FILENAME_DATASETS)
    with open(datasets_metadata_path, "r") as f:
        datasets_metadata = json.load(f)

    datasets_metadata[0]["name"] = "my new name 0"
    datasets_metadata[1]["name"] = "my new name 1"

    assert "dataset" in datasets_metadata[0]
    datasets_metadata[0]["dataset"]["object_store_id"] = "foo1"

    with open(datasets_metadata_path, "w") as f:
        json.dump(datasets_metadata, f)

    import_model_store = store.get_import_model_store(app, u, temp_directory, store.ImportOptions(allow_edit=True))
    with import_model_store.target_history(default_history=import_history):
        import_model_store.perform_import(None, import_history)

    datasets = import_history.datasets
    assert len(datasets) == 0

    d1 = h.datasets[0]
    d2 = h.datasets[1]

    assert d1.name == "my new name 0", d1.name
    assert d2.name == "my new name 1", d2.name
    assert d1.dataset.object_store_id == "foo1", d1.dataset.object_store_id


def test_import_export_edit_collection():
    app = _mock_app()
    sa_session = app.model.context

    u = model.User(email="collection@example.com", password="password")
    h = model.History(name="Test History", user=u)

    c1 = model.DatasetCollection(collection_type="list", populated=False)
    hc1 = model.HistoryDatasetCollectionAssociation(history=h, hid=1, collection=c1, name="HistoryCollectionTest1")

    sa_session.add(hc1)
    sa_session.add(h)
    sa_session.flush()

    import_history = model.History(name="Test History for Import", user=u)
    sa_session.add(import_history)

    temp_directory = mkdtemp()
    with store.ModelExportStore(app, temp_directory, {"for_edit": True}) as export_store:
        export_store.add_dataset_collection(hc1)

    # Fabric editing metadata for collection...
    collections_metadata_path = os.path.join(temp_directory, store.ATTRS_FILENAME_COLLECTIONS)
    datasets_metadata_path = os.path.join(temp_directory, store.ATTRS_FILENAME_DATASETS)
    with open(collections_metadata_path, "r") as f:
        hdcas_metadata = json.load(f)

    assert len(hdcas_metadata) == 1
    hdca_metadata = hdcas_metadata[0]
    assert hdca_metadata
    assert "id" in hdca_metadata
    assert "collection" in hdca_metadata
    collection_metadata = hdca_metadata["collection"]
    assert "populated_state" in collection_metadata
    assert collection_metadata["populated_state"] == model.DatasetCollection.populated_states.NEW

    collection_metadata["populated_state"] = model.DatasetCollection.populated_states.OK

    d1 = model.HistoryDatasetAssociation(extension="txt", create_dataset=True, flush=False)
    d2 = model.HistoryDatasetAssociation(extension="txt", create_dataset=True, flush=False)
    serialization_options = model.SerializationOptions(for_edit=True)
    dataset_list = [d1.serialize(app, serialization_options),
                    d2.serialize(app, serialization_options)]

    dc = model.DatasetCollection(
        id=collection_metadata["id"],
        collection_type="list",
        element_count=2,
    )
    dc.populated_state = model.DatasetCollection.populated_states.OK
    dce1 = model.DatasetCollectionElement(
        element=d1,
        element_index=0,
        element_identifier="first",
    )
    dce2 = model.DatasetCollectionElement(
        element=d2,
        element_index=1,
        element_identifier="second",
    )
    dc.elements = [dce1, dce2]
    with open(datasets_metadata_path, "w") as datasets_f:
        json.dump(dataset_list, datasets_f)

    hdca_metadata["collection"] = dc.serialize(app, serialization_options)
    with open(collections_metadata_path, "w") as collections_f:
        json.dump(hdcas_metadata, collections_f)

    import_model_store = store.get_import_model_store(app, u, temp_directory, store.ImportOptions(allow_edit=True))
    with import_model_store.target_history(default_history=import_history):
        import_model_store.perform_import(None, import_history)

    sa_session.refresh(c1)
    assert c1.populated_state == model.DatasetCollection.populated_states.OK, c1.populated_state
    assert len(c1.elements) == 2


def test_import_datasets_with_ids_fails_if_not_editing_models():
    app, h, temp_directory, import_history = _setup_simple_export({"for_edit": True})
    u = h.user

    caught = None
    try:
        import_model_store = store.get_import_model_store(app, u, temp_directory, store.ImportOptions(allow_edit=False))
        with import_model_store.target_history(default_history=import_history):
            import_model_store.perform_import(None, import_history)
    except AssertionError as e:
        # TODO: catch a better exception
        caught = e
    assert caught


def _setup_simple_export(export_kwds):
    app = _mock_app()
    sa_session = app.model.context

    u = model.User(email="collection@example.com", password="password")
    h = model.History(name="Test History", user=u)

    d1 = model.HistoryDatasetAssociation(extension="txt", history=h, create_dataset=True, sa_session=sa_session)
    d2 = model.HistoryDatasetAssociation(extension="txt", history=h, create_dataset=True, sa_session=sa_session)

    j = model.Job()
    j.user = u
    j.tool_id = "cat1"

    j.add_input_dataset("input1", d1)
    j.add_output_dataset("out_file1", d2)

    sa_session.add(d1)
    sa_session.add(d2)
    sa_session.add(h)
    sa_session.add(j)
    sa_session.flush()

    import_history = model.History(name="Test History for Import", user=u)
    sa_session.add(import_history)

    temp_directory = mkdtemp()
    with store.ModelExportStore(app, temp_directory, **export_kwds) as export_store:
        export_store.add_dataset(d1)
        export_store.add_dataset(d2)

    return app, h, temp_directory, import_history


def _import_export_history(app, h, dest_export):
    temp_directory = mkdtemp()
    with store.ModelExportStore(app, temp_directory) as export_store:
        export_store.export_history(h)

    ret = export_history.main(["--gzip", temp_directory, dest_export])
    assert ret == 0

    imported_history = import_archive(dest_export, app, h.user)
    assert imported_history
    return imported_history


def import_archive(archive_path, app, user):
    dest_parent = mkdtemp()
    dest_dir = os.path.join(dest_parent, 'dest')

    options = Dummy()
    options.is_url = False
    options.is_file = True
    options.is_b64encoded = False

    args = (archive_path, dest_dir)
    unpack_tar_gz_archive.main(options, args)

    new_history = None
    model_store = store.get_import_model_store(app, user, dest_dir)
    with model_store.target_history(default_history=None) as new_history:
        model_store.perform_import(None, new_history)

    return new_history
