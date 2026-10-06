from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

from galaxy.exceptions import MessageException
from galaxy.files.models import FilesSourceRuntimeContext
from galaxy.files.plugins import FileSourcePluginsConfig
from galaxy.files.sources.xrootd import (
    XRootDFileSourceConfiguration,
    XRootDFilesSource,
)


def _source_and_context(
    root: str = " /Folder/ ",
) -> tuple[XRootDFilesSource, FilesSourceRuntimeContext[XRootDFileSourceConfiguration]]:
    template = XRootDFilesSource.build_template_config(
        id="test",
        type="xrootd",
        root=root,
        hostid="localhost:1094",
        writable=True,
        file_sources_config=FileSourcePluginsConfig(listings_expiry_time=60),
    )
    with patch.object(XRootDFilesSource, "required_module", MagicMock()):
        source = XRootDFilesSource(template)
    return source, source._get_runtime_context()


def test_list_paths_are_scoped_to_configured_root():
    source, context = _source_and_context()
    fs = MagicMock()
    fs.ls.side_effect = [
        [{"name": "/Folder/nested", "type": "directory"}],
        [{"name": "/Folder/nested/hello.txt", "type": "file", "size": 5}],
    ]
    with patch.object(source, "_open_fs", return_value=fs):
        root_entries, _ = source._list(context, "/")
        nested_entries, _ = source._list(context, "/nested")

    assert root_entries[0].path == "/nested"
    assert nested_entries[0].path == "/nested/hello.txt"
    assert nested_entries[0].uri == "xrootd://test/nested/hello.txt"
    assert [call.args[0] for call in fs.ls.call_args_list] == ["/Folder", "/Folder/nested"]


def test_list_under_server_root():
    source, context = _source_and_context(root="/")
    fs = MagicMock()
    # fsspec-xrootd joins entry names onto "/" with a separator, yielding a double slash.
    fs.ls.return_value = [{"name": "//a/b.txt", "type": "file", "size": 5}]
    with patch.object(source, "_open_fs", return_value=fs):
        entries, _ = source._list(context, "/a")

    assert entries[0].path == "/a/b.txt"
    fs.ls.assert_called_once_with("/a", detail=True)


def test_realize_path_is_scoped_to_configured_root():
    source, context = _source_and_context()
    fs = MagicMock()
    with patch.object(source, "_open_fs", return_value=fs):
        source._realize_to("/nested/hello.txt", "/tmp/hello.txt", context)

    fs.get_file.assert_called_once_with("/Folder/nested/hello.txt", "/tmp/hello.txt")


def test_write_streams_through_open(tmp_path):
    source, context = _source_and_context()
    native_path = tmp_path / "hello.txt"
    native_path.write_bytes(b"hello")
    fs = MagicMock()
    destination = fs.open.return_value.__enter__.return_value
    with patch.object(source, "_open_fs", return_value=fs):
        source._write_from("/nested/hello.txt", str(native_path), context)

    fs.open.assert_called_once_with("/Folder/nested/hello.txt", "wb")
    destination.write.assert_called_once_with(b"hello")
    fs.put_file.assert_not_called()


@pytest.mark.parametrize("path", ["/../secret", "../secret", "/nested/../../secret", "/.."])
def test_dotdot_does_not_escape_root(path, tmp_path):
    source, context = _source_and_context()
    native_path = tmp_path / "hello.txt"
    native_path.write_bytes(b"hello")
    fs = MagicMock()
    with patch.object(source, "_open_fs", return_value=fs):
        with pytest.raises(MessageException, match="outside configured XRootD root"):
            source._list(context, path)
        with pytest.raises(MessageException, match="outside configured XRootD root"):
            source._realize_to(path, "/tmp/hello.txt", context)
        with pytest.raises(MessageException, match="outside configured XRootD root"):
            source._write_from(path, str(native_path), context)
    fs.ls.assert_not_called()
    fs.get_file.assert_not_called()
    fs.open.assert_not_called()


@pytest.mark.parametrize("path", ["/Folder2/x", "/Other/x", "/Folder/../Other/x"])
def test_adapt_rejects_outside_root(path):
    source, context = _source_and_context()
    fs = MagicMock()
    fs.ls.return_value = [{"name": path, "type": "file", "size": 5}]
    with patch.object(source, "_open_fs", return_value=fs):
        with pytest.raises(MessageException, match="outside configured .*root"):
            source._list(context, "/")
