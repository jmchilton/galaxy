from pkg_resources import resource_string

from galaxy.files.unittest_utils import (
    TestPosixConfiguredFileSources,
)
from galaxy.model import (
    HistoryDatasetAssociation,
    LibraryDatasetDatasetAssociation,
    store,
)
from galaxy.model.deferred import materializer_factory
from galaxy.model.unittest_utils.store_fixtures import deferred_hda_model_store_dict, one_ld_library_deferred_model_store_dict
from .model.test_model_store import (
    perform_import_from_store_dict,
    setup_fixture_context_with_history,
)
from .test_model_copy import (
    _create_hda,
)


CONTENTS_2_BED = resource_string(__name__, "model/2.bed").decode("UTF-8")


def test_undeferred_hdas_untouched(tmpdir):
    app, sa_session, user, history = setup_fixture_context_with_history()
    hda_fh = tmpdir.join("file.txt")
    hda_fh.write("Moo Cow")
    hda = _create_hda(sa_session, app.object_store, history, hda_fh, include_metadata_file=False)
    sa_session.flush()

    materializer = materializer_factory(True, object_store=app.object_store)
    assert materializer.ensure_materialized(hda) == hda


def test_deferred_hdas_basic_attached():
    fixture_context = setup_fixture_context_with_history()
    store_dict = deferred_hda_model_store_dict()
    perform_import_from_store_dict(fixture_context, store_dict)
    deferred_hda = fixture_context.history.datasets[0]
    assert deferred_hda
    _assert_2_bed_metadata(deferred_hda)
    assert deferred_hda.dataset.state == 'deferred'
    materializer = materializer_factory(True, object_store=fixture_context.app.object_store)
    materialized_hda = materializer.ensure_materialized(deferred_hda)
    materialized_dataset = materialized_hda.dataset
    assert materialized_dataset.state == 'ok'
    # only detached datasets would be created with an external_filename
    assert not materialized_dataset.external_filename
    object_store = fixture_context.app.object_store
    path = object_store.get_filename(materialized_dataset)
    assert path
    _assert_path_contains_2_bed(path)
    _assert_2_bed_metadata(materialized_hda)


def test_deferred_hdas_basic_attached_store_by_uuid():
    # skip a flush here so this is a different path...
    fixture_context = setup_fixture_context_with_history(store_by="uuid")
    store_dict = deferred_hda_model_store_dict()
    perform_import_from_store_dict(fixture_context, store_dict)
    deferred_hda = fixture_context.history.datasets[0]
    assert deferred_hda
    _assert_2_bed_metadata(deferred_hda)
    assert deferred_hda.dataset.state == 'deferred'
    materializer = materializer_factory(True, object_store=fixture_context.app.object_store)
    materialized_hda = materializer.ensure_materialized(deferred_hda)
    materialized_dataset = materialized_hda.dataset
    assert materialized_dataset.state == 'ok'
    # only detached datasets would be created with an external_filename
    assert not materialized_dataset.external_filename
    object_store = fixture_context.app.object_store
    path = object_store.get_filename(materialized_dataset)
    assert path
    _assert_path_contains_2_bed(path)


def test_deferred_hdas_basic_detached(tmpdir):
    fixture_context = setup_fixture_context_with_history()
    store_dict = deferred_hda_model_store_dict()
    perform_import_from_store_dict(fixture_context, store_dict)
    deferred_hda = fixture_context.history.datasets[0]
    assert deferred_hda
    _assert_2_bed_metadata(deferred_hda)
    assert deferred_hda.dataset.state == 'deferred'
    materializer = materializer_factory(False, transient_directory=tmpdir)
    materialized_hda = materializer.ensure_materialized(deferred_hda)
    materialized_dataset = materialized_hda.dataset
    assert materialized_dataset.state == 'ok'
    external_filename = materialized_dataset.external_filename
    assert external_filename
    assert external_filename.startswith(str(tmpdir))
    _assert_path_contains_2_bed(external_filename)
    _assert_2_bed_metadata(materialized_hda)


def test_deferred_hdas_basic_detached_from_detached_hda(tmpdir):
    fixture_context = setup_fixture_context_with_history()
    store_dict = deferred_hda_model_store_dict()
    perform_import_from_store_dict(fixture_context, store_dict)
    deferred_hda = fixture_context.history.datasets[0]
    assert deferred_hda

    _ensure_relations_attached_and_expunge(deferred_hda, fixture_context)

    assert deferred_hda.dataset.state == 'deferred'
    materializer = materializer_factory(False, transient_directory=tmpdir)
    materialized_hda = materializer.ensure_materialized(deferred_hda)
    materialized_dataset = materialized_hda.dataset
    assert materialized_dataset.state == 'ok'
    external_filename = materialized_dataset.external_filename
    assert external_filename
    assert external_filename.startswith(str(tmpdir))
    _assert_path_contains_2_bed(external_filename)
    _assert_2_bed_metadata(materialized_hda)


def test_deferred_hdas_basic_attached_from_detached_hda():
    fixture_context = setup_fixture_context_with_history()
    store_dict = deferred_hda_model_store_dict()
    perform_import_from_store_dict(fixture_context, store_dict)
    deferred_hda = fixture_context.history.datasets[0]
    assert deferred_hda

    _ensure_relations_attached_and_expunge(deferred_hda, fixture_context)

    assert deferred_hda.dataset.state == 'deferred'
    materializer = materializer_factory(True, object_store=fixture_context.app.object_store, sa_session=fixture_context.sa_session)
    materialized_hda = materializer.ensure_materialized(deferred_hda)
    materialized_dataset = materialized_hda.dataset
    assert materialized_dataset.state == 'ok'
    # only detached datasets would be created with an external_filename
    assert not materialized_dataset.external_filename
    object_store = fixture_context.app.object_store
    path = object_store.get_filename(materialized_dataset)
    assert path
    _assert_path_contains_2_bed(path)
    _assert_2_bed_metadata(materialized_hda)


def test_deferred_ldda_basic_attached():
    import_options = store.ImportOptions(
        allow_library_creation=True,
    )
    fixture_context = setup_fixture_context_with_history()
    store_dict = one_ld_library_deferred_model_store_dict()
    perform_import_from_store_dict(fixture_context, store_dict, import_options=import_options)
    deferred_ldda = fixture_context.sa_session.query(LibraryDatasetDatasetAssociation).all()[0]
    assert deferred_ldda
    assert deferred_ldda.dataset.state == 'deferred'

    materializer = materializer_factory(True, object_store=fixture_context.app.object_store)
    materialized_hda = materializer.ensure_materialized(deferred_ldda)
    assert materialized_hda.history is None
    materialized_dataset = materialized_hda.dataset
    assert materialized_dataset.state == 'ok'
    # only detached datasets would be created with an external_filename
    assert not materialized_dataset.external_filename
    object_store = fixture_context.app.object_store
    path = object_store.get_filename(materialized_dataset)
    assert path
    _assert_path_contains_2_bed(path)


def test_deferred_hdas_basic_attached_file_sources(tmpdir):
    root = tmpdir / "root"
    root.mkdir()
    content_path = root / "2.bed"
    content_path.write_text(CONTENTS_2_BED, encoding="utf-8")
    file_sources = TestPosixConfiguredFileSources(root)
    fixture_context = setup_fixture_context_with_history()
    store_dict = deferred_hda_model_store_dict(
        source_uri="gxfiles://test1/2.bed",
    )
    perform_import_from_store_dict(fixture_context, store_dict)
    deferred_hda = fixture_context.history.datasets[0]
    assert deferred_hda
    assert deferred_hda.dataset.state == 'deferred'
    materializer = materializer_factory(True, object_store=fixture_context.app.object_store, file_sources=file_sources)
    materialized_hda = materializer.ensure_materialized(deferred_hda)
    materialized_dataset = materialized_hda.dataset
    assert materialized_dataset.state == 'ok'
    # only detached datasets would be created with an external_filename
    assert not materialized_dataset.external_filename
    object_store = fixture_context.app.object_store
    path = object_store.get_filename(materialized_dataset)
    assert path
    _assert_path_contains_2_bed(path)
    _assert_2_bed_metadata(materialized_hda)


def test_deferred_hdas_with_deferred_metadata():
    fixture_context = setup_fixture_context_with_history()
    store_dict = deferred_hda_model_store_dict(metadata_deferred=True)
    perform_import_from_store_dict(fixture_context, store_dict)
    deferred_hda = fixture_context.history.datasets[0]
    assert deferred_hda
    assert deferred_hda.dataset.state == 'deferred'
    materializer = materializer_factory(True, object_store=fixture_context.app.object_store)
    materialized_hda = materializer.ensure_materialized(deferred_hda)
    materialized_dataset = materialized_hda.dataset
    assert not materialized_hda.metadata_deferred
    assert materialized_dataset.state == 'ok'
    # only detached datasets would be created with an external_filename
    assert not materialized_dataset.external_filename
    object_store = fixture_context.app.object_store
    path = object_store.get_filename(materialized_dataset)
    assert path
    _assert_path_contains_2_bed(path)
    _assert_2_bed_metadata(materialized_hda)


def _ensure_relations_attached_and_expunge(deferred_hda: HistoryDatasetAssociation, fixture_context) -> None:
    # make sure everything needed is in session (soures, hashes, and metadata)...
    # point here is exercise deferred_hda.history throws a detached error.
    [s.hashes for s in deferred_hda.dataset.sources]
    deferred_hda.dataset.hashes
    deferred_hda._metadata
    sa_session = fixture_context.sa_session
    sa_session.expunge_all()


def _assert_2_bed_metadata(hda: HistoryDatasetAssociation) -> None:
    # metadata_dbkey: ?
    # metadata_data_lines: 68
    # metadata_comment_lines: 0
    # metadata_columns: 6
    # metadata_column_types: ['str', 'int', 'int', 'str', 'int', 'str']
    # metadata_column_names: []
    # metadata_delimiter: '\t'
    # metadata_chromCol: 1
    # metadata_startCol: 2
    # metadata_endCol: 3
    # metadata_viz_filter_cols: [4]
    assert hda.metadata.columns == 6
    assert hda.metadata.data_lines == 68
    assert hda.metadata.comment_lines == 0
    assert hda.metadata.chromCol == 1
    assert hda.metadata.startCol == 2
    assert hda.metadata.endCol == 3
    assert hda.metadata.viz_filter_cols == [4]


def _assert_path_contains_2_bed(path) -> None:
    with open(path, "r") as f:
        contents = f.read()
    assert contents == CONTENTS_2_BED
