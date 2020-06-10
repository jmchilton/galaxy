import os
import tempfile

from galaxy.datatypes import sniff
from galaxy.files import (
    ConfiguredFileSources,
    ConfiguredFileSourcesConfig,
)
from ._util import (
    assert_realizes_as,
    find_file_a,
    list_root,
    serialize_and_recover,
    user_context_fixture,
)


def test_posix():
    file_sources = _configured_file_sources()
    _download_and_check_file(file_sources)

    res = list_root(file_sources, "gxfiles://test1", recursive=False)
    assert find_file_a(res)


def test_posix_link_security():
    file_sources = _configured_file_sources()
    e = None
    try:
        sniff.stream_url_to_file("gxfiles://test1/unsafe", file_sources=file_sources)
    except Exception as ex:
        e = ex
    assert e is not None


def test_posix_link_security_allowlist():
    file_sources = _configured_file_sources(include_allowlist=True)
    tmp_name = sniff.stream_url_to_file("gxfiles://test1/unsafe", file_sources=file_sources)
    try:
        with open(tmp_name, "r") as f:
            assert f.read() == "b\n"
    finally:
        os.remove(tmp_name)


def test_posix_disable_link_security():
    file_sources = _configured_file_sources(plugin_extra_config={"enforce_symlink_security": False})
    tmp_name = sniff.stream_url_to_file("gxfiles://test1/unsafe", file_sources=file_sources)
    try:
        with open(tmp_name, "r") as f:
            assert f.read() == "b\n"
    finally:
        os.remove(tmp_name)


def test_posix_per_user():
    file_sources = _configured_file_sources(per_user=True)
    user_context = user_context_fixture()
    assert_realizes_as(file_sources, "gxfiles://test1/a", "a\n", user_context=user_context)

    res = list_root(file_sources, "gxfiles://test1", recursive=False, user_context=user_context)
    assert find_file_a(res)


def test_posix_per_user_serialized():
    user_context = user_context_fixture()
    file_sources = serialize_and_recover(_configured_file_sources(per_user=True), user_context=user_context)

    # After serialization and recovery - no need to for user context.
    assert_realizes_as(file_sources, "gxfiles://test1/a", "a\n", user_context=None)


def test_user_ftp_explicit_config():
    file_sources_config = ConfiguredFileSourcesConfig()
    plugin = {
        'type': 'gxftp',
    }
    tmp, root = _setup_root()
    file_sources = ConfiguredFileSources(file_sources_config, conf_dict=[plugin])
    user_context = user_context_fixture(user_ftp_dir=root)
    _write_file_fixtures(tmp, root)

    assert_realizes_as(file_sources, "gxftp://a", "a\n", user_context=user_context)

    file_sources_remote = serialize_and_recover(file_sources, user_context=user_context)
    assert_realizes_as(file_sources_remote, "gxftp://a", "a\n")


def test_user_ftp_implicit_config():
    tmp, root = _setup_root()
    file_sources_config = ConfiguredFileSourcesConfig(
        ftp_upload_dir=root,
    )
    file_sources = ConfiguredFileSources(file_sources_config, conf_dict=[], load_stock_plugins=True)
    user_context = user_context_fixture(user_ftp_dir=root)
    _write_file_fixtures(tmp, root)

    assert_realizes_as(file_sources, "gxftp://a", "a\n", user_context=user_context)

    file_sources_remote = serialize_and_recover(file_sources, user_context=user_context)
    assert_realizes_as(file_sources_remote, "gxftp://a", "a\n")


def test_import_dir_explicit_config():
    tmp, root = _setup_root()
    file_sources_config = ConfiguredFileSourcesConfig(
        library_import_dir=root,
    )
    plugin = {
        'type': 'gximport',
    }
    file_sources = ConfiguredFileSources(file_sources_config, conf_dict=[plugin])
    _write_file_fixtures(tmp, root)

    assert_realizes_as(file_sources, "gximport://a", "a\n")


def test_import_dir_implicit_config():
    tmp, root = _setup_root()
    file_sources_config = ConfiguredFileSourcesConfig(
        library_import_dir=root,
    )
    file_sources = ConfiguredFileSources(file_sources_config, conf_dict=[], load_stock_plugins=True)
    _write_file_fixtures(tmp, root)

    assert_realizes_as(file_sources, "gximport://a", "a\n")


def test_user_import_dir_implicit_config():
    tmp, root = _setup_root()
    file_sources_config = ConfiguredFileSourcesConfig(
        user_library_import_dir=root,
    )
    file_sources = ConfiguredFileSources(file_sources_config, conf_dict=[], load_stock_plugins=True)

    _write_file_fixtures(tmp, os.path.join(root, 'alice'))

    user_context = user_context_fixture()
    assert_realizes_as(file_sources, "gxuserimport://a", "a\n", user_context=user_context)


def _configured_file_sources(include_allowlist=False, plugin_extra_config=None, per_user=False):
    tmp, root = _setup_root()
    config_kwd = {}
    if include_allowlist:
        config_kwd["symlink_allowlist"] = [tmp]
    file_sources_config = ConfiguredFileSourcesConfig(**config_kwd)
    plugin = {
        'type': 'posix',
        'id': 'test1',
    }
    if per_user:
        plugin['root'] = "%s/${user.username}" % root
        # setup files just for alice
        root = os.path.join(root, "alice")
        os.mkdir(root)
    else:
        plugin['root'] = root
    plugin.update(plugin_extra_config or {})
    _write_file_fixtures(tmp, root)
    return ConfiguredFileSources(file_sources_config, conf_dict=[plugin])


def _setup_root():
    tmp = os.path.realpath(tempfile.mkdtemp())
    root = os.path.join(tmp, "root")
    os.mkdir(root)
    return tmp, root


def _write_file_fixtures(tmp, root):
    if not os.path.exists(root):
        os.mkdir(root)
    os.symlink(os.path.join(tmp, "b"), os.path.join(root, "unsafe"))
    with open(os.path.join(root, "a"), "w") as f:
        f.write("a\n")
    with open(os.path.join(tmp, "b"), "w") as f:
        f.write("b\n")

    return tmp, root

def _download_and_check_file(file_sources):
    tmp_name = sniff.stream_url_to_file("gxfiles://test1/a", file_sources=file_sources)
    try:
        a_contents = open(tmp_name, "r").read()
        assert a_contents == "a\n"
    finally:
        os.remove(tmp_name)
