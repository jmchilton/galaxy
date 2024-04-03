from galaxy.objectstore import (
    concrete_object_store,
    UserObjectStoresAppConfig,
)
from galaxy.objectstore.templates.models import DiskObjectStoreConfiguration
from .test_objectstore import MockDataset


def test_disk(tmpdir):
    files_dir = tmpdir / "moo"
    files_dir.mkdir()
    configuration = DiskObjectStoreConfiguration(
        type="disk",
        files_dir=str(files_dir),
    )
    _app_config = app_config(tmpdir)
    object_store = concrete_object_store(configuration, _app_config)

    absent_dataset = MockDataset(1)
    assert not object_store.exists(absent_dataset)

    # Write empty dataset 2 in second backend, ensure it is empty and
    # exists.
    empty_dataset = MockDataset(2)
    object_store.create(empty_dataset)
    object_store.exists(empty_dataset)
    assert object_store.size(empty_dataset) == 0

    example_dataset = MockDataset(3)
    temp_file = tmpdir / "example.txt"
    temp_file.write_text("moo cow", "utf-8")
    object_store.create(example_dataset)
    object_store.update_from_file(example_dataset, file_name=str(temp_file))
    assert object_store.size(example_dataset) == 7


def app_config(tmpdir) -> UserObjectStoresAppConfig:
    app_config = UserObjectStoresAppConfig(
        jobs_directory=str(tmpdir / "jobs"),
        new_file_path=str(tmpdir / "new_files"),
        umask=0o077,
        object_store_cache_path=str(tmpdir / "cache"),
        object_store_cache_size=1,
    )
    return app_config
