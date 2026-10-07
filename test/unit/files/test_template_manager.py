from yaml import safe_load

from galaxy.files.templates import ConfiguredFileSourceTemplates
from .test_template_models import (
    LIBRARY_AWS,
    LIBRARY_HOME_DIRECTORY,
)

SCRATCH_DIRECTORY = """
id: scratch_directory
name: Scratch Directory
description: Your Scratch Directory on this System
configuration:
  type: posix
  root: "/scratch/{{ user.username }}/"
"""


class MockConfig:
    def __init__(self, config_path, config_dir=None, inline=None):
        self.file_source_templates = inline
        self.file_source_templates_config_file = config_path
        self.file_source_templates_config_dir = config_dir


def test_manager(tmpdir):
    config_path = tmpdir / "conf.yml"
    config_path.write_text(LIBRARY_HOME_DIRECTORY, "utf-8")
    config = MockConfig(config_path)
    templates = ConfiguredFileSourceTemplates.from_app_config(config)
    summaries = templates.summaries
    assert summaries
    assert len(summaries.root) == 1


def test_manager_throws_exception_if_vault_is_required_but_configured(tmpdir):
    config_path = tmpdir / "conf.yml"
    config_path.write_text(LIBRARY_AWS, "utf-8")
    config = MockConfig(config_path)
    exc = None
    try:
        ConfiguredFileSourceTemplates.from_app_config(config, vault_configured=False)
    except Exception as e:
        exc = e
    assert exc, "catalog creation should result in an exception"
    assert "vault must be configured" in str(exc)


def test_manager_with_secrets_is_fine_if_vault_is_required_and_configured(tmpdir):
    config_path = tmpdir / "conf.yml"
    config_path.write_text(LIBRARY_AWS, "utf-8")
    config = MockConfig(config_path)
    exc = None
    try:
        ConfiguredFileSourceTemplates.from_app_config(config, vault_configured=True)
    except Exception as e:
        exc = e
    assert exc is None


def test_manager_does_not_throw_exception_if_vault_is_not_required(tmpdir):
    config_path = tmpdir / "conf.yml"
    config_path.write_text(LIBRARY_HOME_DIRECTORY, "utf-8")
    config = MockConfig(config_path)
    exc = None
    try:
        ConfiguredFileSourceTemplates.from_app_config(config, vault_configured=False)
    except Exception as e:
        exc = e
    assert exc is None


def test_manager_loads_config_dir_in_filename_order(tmpdir):
    config_dir = tmpdir / "file_source_templates.d"
    config_dir.mkdir()
    (config_dir / "20_scratch.yaml").write_text(SCRATCH_DIRECTORY, "utf-8")
    (config_dir / "10_home.yml").write_text(LIBRARY_HOME_DIRECTORY, "utf-8")
    (config_dir / ".05_hidden.yml").write_text(LIBRARY_AWS, "utf-8")
    (config_dir / "30_aws.yml.sample").write_text(LIBRARY_AWS, "utf-8")
    (config_dir / "README.md").write_text("not a template", "utf-8")
    config = MockConfig(None, config_dir=str(config_dir))
    templates = ConfiguredFileSourceTemplates.from_app_config(config)
    assert [t.id for t in templates.catalog.root] == ["home_directory", "scratch_directory"]


def test_manager_loads_config_file_before_config_dir(tmpdir):
    config_path = tmpdir / "conf.yml"
    config_path.write_text(LIBRARY_HOME_DIRECTORY, "utf-8")
    config_dir = tmpdir / "file_source_templates.d"
    config_dir.mkdir()
    (config_dir / "scratch.yml").write_text(SCRATCH_DIRECTORY, "utf-8")
    config = MockConfig(str(config_path), config_dir=str(config_dir))
    templates = ConfiguredFileSourceTemplates.from_app_config(config)
    assert [t.id for t in templates.catalog.root] == ["home_directory", "scratch_directory"]


def test_manager_ignores_missing_config_dir(tmpdir):
    config = MockConfig(None, config_dir=str(tmpdir / "missing.d"))
    templates = ConfiguredFileSourceTemplates.from_app_config(config)
    assert templates.catalog.root == []


def test_inline_templates_override_config_file_and_dir(tmpdir):
    config_path = tmpdir / "conf.yml"
    config_path.write_text(LIBRARY_HOME_DIRECTORY, "utf-8")
    config_dir = tmpdir / "file_source_templates.d"
    config_dir.mkdir()
    (config_dir / "aws.yml").write_text(LIBRARY_AWS, "utf-8")
    inline = [safe_load(SCRATCH_DIRECTORY)]
    config = MockConfig(str(config_path), config_dir=str(config_dir), inline=inline)
    templates = ConfiguredFileSourceTemplates.from_app_config(config)
    assert [t.id for t in templates.catalog.root] == ["scratch_directory"]
