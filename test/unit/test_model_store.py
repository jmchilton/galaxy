import json
import os
from tempfile import mkdtemp

from galaxy import model
from galaxy.model import store
from galaxy.tools.imp_exp import unpack_tar_gz_archive
from .tools.test_history_imp_exp import _create_datasets, _mock_app, Dummy


def test_import_export_history():
    dest_parent = mkdtemp()
    dest_export = os.path.join(dest_parent, "moo.tgz")

    app = _mock_app()
    sa_session = app.model.context

    u = model.User(email="collection@example.com", password="password")
    h = model.History(name="Test History", user=u)

    d1, d2 = _create_datasets(sa_session, h, 2)

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

    app.object_store.update_from_file(d1, file_name="test-data/1.txt", create=True)
    app.object_store.update_from_file(d2, file_name="test-data/2.bed", create=True)

    imported_history = _import_export_history(app, h, dest_export, export_files="copy")

    assert imported_history.name == "imported from archive: Test History"

    datasets = imported_history.datasets
    assert len(datasets) == 2
    imported_job = datasets[1].creating_job
    assert imported_job
    assert imported_job.output_datasets
    assert imported_job.output_datasets[0].dataset == datasets[1]

    assert imported_job.input_datasets
    assert imported_job.input_datasets[0].dataset == datasets[0]

    with open(datasets[0].file_name, "r") as f:
        assert f.read().startswith("chr1    4225    19670")
    with open(datasets[1].file_name, "r") as f:
        assert f.read().startswith("chr1\t147962192\t147962580\tNM_005997_cds_0_0_chr1_147962193_r\t0\t-")


def test_import_export_bag_archive():
    dest_parent = mkdtemp()
    dest_export = os.path.join(dest_parent, "moo.tgz")

    app = _mock_app()
    sa_session = app.model.context

    u = model.User(email="collection@example.com", password="password")
    h = model.History(name="Test History", user=u)

    d1, d2 = _create_datasets(sa_session, h, 2)

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

    app.object_store.update_from_file(d1, file_name="test-data/1.txt", create=True)
    app.object_store.update_from_file(d2, file_name="test-data/2.bed", create=True)

    with store.BagArchiveModelExportStore(app, dest_export, bag_archiver="tgz", export_files="copy") as export_store:
        export_store.export_history(h)

    model_store = store.BagArchiveImportModelStore(app, h.user, dest_export)
    with model_store.target_history(default_history=None) as imported_history:
        model_store.perform_import(imported_history)
    assert imported_history

    assert imported_history.name == "imported from archive: Test History"

    datasets = imported_history.datasets
    assert len(datasets) == 2
    imported_job = datasets[1].creating_job
    assert imported_job
    assert imported_job.output_datasets
    assert imported_job.output_datasets[0].dataset == datasets[1]

    assert imported_job.input_datasets
    assert imported_job.input_datasets[0].dataset == datasets[0]

    with open(datasets[0].file_name, "r") as f:
        assert f.read().startswith("chr1    4225    19670")
    with open(datasets[1].file_name, "r") as f:
        assert f.read().startswith("chr1\t147962192\t147962580\tNM_005997_cds_0_0_chr1_147962193_r\t0\t-")


def test_import_export_datasets():
    app, h, temp_directory, import_history = _setup_simple_export({"for_edit": False})
    u = h.user

    import_model_store = store.get_import_model_store(app, u, temp_directory)
    with import_model_store.target_history(default_history=import_history):
        import_model_store.perform_import(import_history)

    datasets = import_history.datasets
    assert len(datasets) == 2
    imported_job = datasets[1].creating_job
    assert imported_job
    assert imported_job.output_datasets
    assert imported_job.output_datasets[0].dataset == datasets[1]

    assert imported_job.input_datasets
    assert imported_job.input_datasets[0].dataset == datasets[0]


def test_import_library_require_permissions():
    app = _mock_app()
    sa_session = app.model.context

    u = model.User(email="collection@example.com", password="password")

    library = model.Library(name="my library 1", description="my library description", synopsis="my synopsis")
    root_folder = model.LibraryFolder(name="my library 1", description='folder description')
    library.root_folder = root_folder
    sa_session.add_all((library, root_folder))
    sa_session.flush()

    temp_directory = mkdtemp()
    with store.DirectoryModelExportStore(app, temp_directory) as export_store:
        export_store.export_library(library)

    error_caught = False
    try:
        import_model_store = store.get_import_model_store(app, u, temp_directory)
        import_model_store.perform_import()
    except AssertionError:
        # TODO: throw and catch a better exception...
        error_caught = True

    assert error_caught


def test_import_export_library():
    app = _mock_app()
    sa_session = app.model.context

    u = model.User(email="collection@example.com", password="password")

    library = model.Library(name="my library 1", description="my library description", synopsis="my synopsis")
    root_folder = model.LibraryFolder(name="my library 1", description='folder description')
    library.root_folder = root_folder
    sa_session.add_all((library, root_folder))
    sa_session.flush()

    subfolder = model.LibraryFolder(name="sub folder 1", description="sub folder")
    root_folder.add_folder(subfolder)
    sa_session.add(subfolder)

    ld = model.LibraryDataset(folder=root_folder, name="my name", info="my library dataset")
    ldda = model.LibraryDatasetDatasetAssociation(
        create_dataset=True, flush=False
    )
    ld.library_dataset_dataset_association = ldda
    root_folder.add_library_dataset(ld)

    sa_session.add(ld)
    sa_session.add(ldda)

    sa_session.flush()
    assert len(root_folder.datasets) == 1 
    assert len(root_folder.folders) == 1 

    temp_directory = mkdtemp()
    with store.DirectoryModelExportStore(app, temp_directory) as export_store:
        export_store.export_library(library)

    import_model_store = store.get_import_model_store(app, u, temp_directory, store.ImportOptions(allow_library_creation=True))
    import_model_store.perform_import()

    all_libraries = sa_session.query(model.Library).all()
    assert len(all_libraries) == 2, len(all_libraries)
    all_lddas = sa_session.query(model.LibraryDatasetDatasetAssociation).all()
    assert len(all_lddas) == 2, len(all_lddas)

    new_library = [l for l in all_libraries if l.id != library.id][0]
    assert new_library.name == "my library 1"
    assert new_library.description == "my library description"
    assert new_library.synopsis == "my synopsis"

    new_root = new_library.root_folder
    assert new_root
    assert new_root.name == "my library 1"

    assert len(new_root.folders) == 1
    assert len(new_root.datasets) == 1


def test_finalize_job_state():
    app, h, temp_directory, import_history = _setup_simple_export({"for_edit": False})
    u = h.user

    with open(os.path.join(temp_directory, store.ATTRS_FILENAME_JOBS), "r") as f:
        job_attrs = json.load(f)

    for job in job_attrs:
        job["state"] = "queued"

    with open(os.path.join(temp_directory, store.ATTRS_FILENAME_JOBS), "w") as f:
        json.dump(job_attrs, f)

    import_model_store = store.get_import_model_store(app, u, temp_directory)
    with import_model_store.target_history(default_history=import_history):
        import_model_store.perform_import(import_history)

    datasets = import_history.datasets
    assert len(datasets) == 2
    imported_job = datasets[1].creating_job
    assert imported_job
    assert imported_job.state == model.Job.states.ERROR


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
        import_model_store.perform_import(import_history)

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
    with store.DirectoryModelExportStore(app, temp_directory, {"for_edit": True}) as export_store:
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
    d1.hid = 1
    d2 = model.HistoryDatasetAssociation(extension="txt", create_dataset=True, flush=False)
    d2.hid = 2
    serialization_options = model.SerializationOptions(for_edit=True)
    dataset_list = [d1.serialize(app.security, serialization_options),
                    d2.serialize(app.security, serialization_options)]

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

    hdca_metadata["collection"] = dc.serialize(app.security, serialization_options)
    with open(collections_metadata_path, "w") as collections_f:
        json.dump(hdcas_metadata, collections_f)

    import_model_store = store.get_import_model_store(app, u, temp_directory, store.ImportOptions(allow_edit=True))
    with import_model_store.target_history(default_history=import_history):
        import_model_store.perform_import(import_history)

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
            import_model_store.perform_import(import_history)
    except AssertionError as e:
        # TODO: catch a better exception
        caught = e
    assert caught


def test_model_create_context_persist_hdas():
    work_directory = mkdtemp()
    with open(os.path.join(work_directory, "file1.txt"), "w") as f:
        f.write("hello world\nhello world line 2")
    target = {
        "destination": {
            "type": "hdas",
        },
        "elements": [{
            "filename": "file1.txt",
            "ext": "txt",
            "dbkey": "hg19",
            "name": "my file",
        }],
    }
    app = _mock_app(store_by="uuid")
    temp_directory = mkdtemp()
    with store.DirectoryModelExportStore(app, temp_directory, serialize_dataset_objects=True) as export_store:
        from galaxy.tools.parameters.output_collect import persist_target_to_export_store
        persist_target_to_export_store(target, export_store, app.object_store, work_directory)

    u = model.User(email="collection@example.com", password="password")
    import_history = model.History(name="Test History for Import", user=u)

    sa_session = app.model.context
    sa_session.add(u)
    sa_session.add(import_history)
    sa_session.flush()

    assert len(import_history.datasets) == 0

    import_options = store.ImportOptions(allow_dataset_object_edit=True)
    import_model_store = store.get_import_model_store(app, u, temp_directory, import_options=import_options)
    with import_model_store.target_history(default_history=import_history):
        import_model_store.perform_import(import_history)

    assert len(import_history.datasets) == 1
    imported_hda = import_history.datasets[0]
    assert imported_hda.ext == "txt"
    assert imported_hda.name == "my file"
    assert imported_hda.metadata.data_lines == 2

    with open(imported_hda.file_name, "r") as f:
        assert f.read().startswith("hello world\n")


def test_persist_target_library_dataset():
    work_directory = mkdtemp()
    with open(os.path.join(work_directory, "file1.txt"), "w") as f:
        f.write("hello world\nhello world line 2")
    target = {
        "destination": {
            "type": "library",
            "name": "Example Library",
            "description": "Example Library Description",
            "synopsis": "Example Library Synopsis",
        },
        "elements": [{
            "filename": "file1.txt",
            "ext": "txt",
            "dbkey": "hg19",
            "name": "my file",
        }],
    }
    sa_session = _import_library_target(target, work_directory)
    new_library = _assert_one_library_created(sa_session)

    assert new_library.name == "Example Library"
    assert new_library.description == "Example Library Description"
    assert new_library.synopsis == "Example Library Synopsis"

    new_root = new_library.root_folder
    assert new_root
    assert new_root.name == "Example Library"

    assert len(new_root.datasets) == 1
    ldda = new_root.datasets[0].library_dataset_dataset_association
    assert ldda.metadata.data_lines == 2
    with open(ldda.file_name, "r") as f:
        assert f.read().startswith("hello world\n")


def test_persist_target_library_folder():
    work_directory = mkdtemp()
    with open(os.path.join(work_directory, "file1.txt"), "w") as f:
        f.write("hello world\nhello world line 2")
    target = {
        "destination": {
            "type": "library",
            "name": "Example Library",
            "description": "Example Library Description",
            "synopsis": "Example Library Synopsis",
        },
        "items": [{
            "name": "Folder 1",
            "description": "Folder 1 Description",
            "items": [{
                "filename": "file1.txt",
                "ext": "txt",
                "dbkey": "hg19",
                "info": "dataset info",
                "name": "my file",
            }]
        }],
    }
    sa_session = _import_library_target(target, work_directory)
    new_library = _assert_one_library_created(sa_session)
    new_root = new_library.root_folder
    assert len(new_root.datasets) == 0
    assert len(new_root.folders) == 1

    child_folder = new_root.folders[0]
    assert child_folder.name == "Folder 1"
    assert child_folder.description == "Folder 1 Description"
    assert len(child_folder.folders) == 0
    assert len(child_folder.datasets) == 1
    ldda = child_folder.datasets[0].library_dataset_dataset_association
    assert ldda.metadata.data_lines == 2
    with open(ldda.file_name, "r") as f:
        assert f.read().startswith("hello world\n")


def _assert_one_library_created(sa_session):
    all_libraries = sa_session.query(model.Library).all()
    assert len(all_libraries) == 1, len(all_libraries)
    new_library = all_libraries[0]
    return new_library


def _import_library_target(target, work_directory):
    app = _mock_app(store_by="uuid")
    temp_directory = mkdtemp()
    with store.DirectoryModelExportStore(app, temp_directory, serialize_dataset_objects=True) as export_store:
        from galaxy.tools.parameters.output_collect import persist_target_to_export_store
        persist_target_to_export_store(target, export_store, app.object_store, work_directory)

    u = model.User(email="library@example.com", password="password")

    import_options = store.ImportOptions(allow_dataset_object_edit=True, allow_library_creation=True)
    import_model_store = store.get_import_model_store(app, u, temp_directory, import_options=import_options)
    import_model_store.perform_import()

    sa_session = app.model.context
    return sa_session


def _setup_simple_export(export_kwds):
    app = _mock_app()
    sa_session = app.model.context

    u = model.User(email="collection@example.com", password="password")
    h = model.History(name="Test History", user=u)

    d1, d2 = _create_datasets(sa_session, h, 2)

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
    with store.DirectoryModelExportStore(app, temp_directory, **export_kwds) as export_store:
        export_store.add_dataset(d1)
        export_store.add_dataset(d2)

    return app, h, temp_directory, import_history


def _import_export_history(app, h, dest_export, export_files=None):
    with store.TarModelExportStore(app, dest_export, export_files=export_files) as export_store:
        export_store.export_history(h)

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
        model_store.perform_import(new_history)

    return new_history
