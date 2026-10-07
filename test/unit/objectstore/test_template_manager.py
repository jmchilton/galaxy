from galaxy.objectstore.templates import ConfiguredObjectStoreTemplates
from .test_template_models import (
    LIBRARY_2,
    LIBRARY_AZURE_CONTAINER,
)


class MockConfig:
    def __init__(self, config_path, config_dir=None):
        self.object_store_templates = None
        self.object_store_templates_config_file = config_path
        self.object_store_templates_config_dir = config_dir


def test_manager(tmpdir):
    config_path = tmpdir / "conf.yml"
    config_path.write_text(LIBRARY_2, "utf-8")
    config = MockConfig(config_path)
    templates = ConfiguredObjectStoreTemplates.from_app_config(config)
    summaries = templates.summaries
    assert summaries
    assert len(summaries.root) == 2


def test_manager_throws_exception_if_vault_is_required_but_configured(tmpdir):
    config_path = tmpdir / "conf.yml"
    config_path.write_text(LIBRARY_AZURE_CONTAINER, "utf-8")
    config = MockConfig(config_path)
    exc = None
    try:
        ConfiguredObjectStoreTemplates.from_app_config(config, vault_configured=False)
    except Exception as e:
        exc = e
    assert exc, "catalog creation should result in an exception"
    assert "vault must be configured" in str(exc)


def test_manager_with_secrets_is_fine_if_vault_is_required_and_configured(tmpdir):
    config_path = tmpdir / "conf.yml"
    config_path.write_text(LIBRARY_AZURE_CONTAINER, "utf-8")
    config = MockConfig(config_path)
    exc = None
    try:
        ConfiguredObjectStoreTemplates.from_app_config(config, vault_configured=True)
    except Exception as e:
        exc = e
    assert exc is None


def test_manager_does_not_throw_exception_if_vault_is_not_required(tmpdir):
    config_path = tmpdir / "conf.yml"
    config_path.write_text(LIBRARY_2, "utf-8")
    config = MockConfig(config_path)
    exc = None
    try:
        ConfiguredObjectStoreTemplates.from_app_config(config, vault_configured=False)
    except Exception as e:
        exc = e
    assert exc is None


def test_manager_loads_config_dir(tmpdir):
    config_dir = tmpdir / "object_store_templates.d"
    config_dir.mkdir()
    (config_dir / "disks.yml").write_text(LIBRARY_2, "utf-8")
    config = MockConfig(str(tmpdir / "missing.yml"), config_dir=str(config_dir))
    templates = ConfiguredObjectStoreTemplates.from_app_config(config)
    assert [t.id for t in templates.catalog.root] == ["general_disk", "secure_disk"]
