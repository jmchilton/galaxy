import os
from pathlib import Path

import pytest
from pydantic import (
    BaseModel,
    RootModel,
)

from galaxy.job_execution import metadata_lazy_imports
from galaxy.job_execution.metadata_constants import (
    LAZY_IMPORTS_ENV,
    LIGHTWEIGHT_MODELS_ENV,
    PYDANTIC_DISABLE_PLUGINS_ENV,
)
from galaxy.job_execution.metadata_runner import run_metadata
from galaxy.job_execution.pydantic_defer import defer_pydantic_model_builds


def test_external_adapter_uses_lightweight_entrypoint():
    adapter_source = Path("lib/galaxy_ext/metadata/set_metadata.py").read_text()

    assert "from galaxy.job_execution.set_metadata import set_metadata" in adapter_source


def test_configure_lazy_imports_defaults_to_all(monkeypatch):
    calls = []
    monkeypatch.delenv(LAZY_IMPORTS_ENV, raising=False)
    monkeypatch.delenv(LIGHTWEIGHT_MODELS_ENV, raising=False)
    monkeypatch.delenv(PYDANTIC_DISABLE_PLUGINS_ENV, raising=False)
    monkeypatch.setattr(
        metadata_lazy_imports.sys,
        "set_lazy_imports_filter",
        lambda lazy_import_filter: calls.append(("filter", lazy_import_filter)),
        raising=False,
    )
    monkeypatch.setattr(
        metadata_lazy_imports.sys,
        "set_lazy_imports",
        lambda mode: calls.append(("mode", mode)),
        raising=False,
    )
    lazy_imports_enabled = metadata_lazy_imports.configure_lazy_imports()

    assert calls == [
        ("filter", metadata_lazy_imports.set_metadata_lazy_import_filter),
        ("mode", "all"),
    ]
    assert os.environ[PYDANTIC_DISABLE_PLUGINS_ENV] == "logfire-plugin"
    assert os.environ[LIGHTWEIGHT_MODELS_ENV] == "1"
    assert lazy_imports_enabled is True


def test_configure_lazy_imports_only_disables_logfire_before_python_315(monkeypatch):
    calls = []
    monkeypatch.delenv(PYDANTIC_DISABLE_PLUGINS_ENV, raising=False)
    monkeypatch.setenv(LIGHTWEIGHT_MODELS_ENV, "1")
    monkeypatch.delattr(metadata_lazy_imports.sys, "set_lazy_imports_filter", raising=False)
    monkeypatch.delattr(metadata_lazy_imports.sys, "set_lazy_imports", raising=False)

    lazy_imports_enabled = metadata_lazy_imports.configure_lazy_imports()

    assert os.environ[PYDANTIC_DISABLE_PLUGINS_ENV] == "logfire-plugin"
    assert LIGHTWEIGHT_MODELS_ENV not in os.environ
    assert calls == []
    assert lazy_imports_enabled is False


def test_configure_lazy_imports_can_be_disabled(monkeypatch):
    calls = []
    monkeypatch.setenv(LAZY_IMPORTS_ENV, "normal")
    monkeypatch.setenv(LIGHTWEIGHT_MODELS_ENV, "1")
    monkeypatch.setattr(
        metadata_lazy_imports.sys,
        "set_lazy_imports_filter",
        lambda lazy_import_filter: calls.append(("filter", lazy_import_filter)),
        raising=False,
    )
    monkeypatch.setattr(
        metadata_lazy_imports.sys,
        "set_lazy_imports",
        lambda mode: calls.append(("mode", mode)),
        raising=False,
    )
    lazy_imports_enabled = metadata_lazy_imports.configure_lazy_imports()

    assert calls == [("filter", None), ("mode", "normal")]
    assert LIGHTWEIGHT_MODELS_ENV not in os.environ
    assert lazy_imports_enabled is False


def test_set_metadata_freezes_gc_after_successful_lazy_run(monkeypatch):
    calls = []
    monkeypatch.setattr("galaxy.job_execution.metadata_runner.gc.freeze", lambda: calls.append("freeze"))

    run_metadata(lambda: calls.append("set_metadata"), lazy_imports_enabled=True)

    assert calls == ["set_metadata", "freeze"]


def test_set_metadata_does_not_freeze_gc_in_rollback_mode(monkeypatch):
    calls = []
    monkeypatch.setattr("galaxy.job_execution.metadata_runner.gc.freeze", lambda: calls.append("freeze"))

    run_metadata(lambda: calls.append("set_metadata"), lazy_imports_enabled=False)

    assert calls == ["set_metadata"]


def test_set_metadata_does_not_freeze_gc_after_failure(monkeypatch):
    calls = []

    def fail():
        calls.append("set_metadata")
        raise RuntimeError("failed")

    monkeypatch.setattr("galaxy.job_execution.metadata_runner.gc.freeze", lambda: calls.append("freeze"))

    with pytest.raises(RuntimeError, match="failed"):
        run_metadata(fail, lazy_imports_enabled=True)

    assert calls == ["set_metadata"]


def test_defer_pydantic_model_builds_sets_inherited_defaults(monkeypatch):
    monkeypatch.setitem(BaseModel.model_config, "defer_build", False)
    monkeypatch.setitem(RootModel.model_config, "defer_build", False)

    defer_pydantic_model_builds()

    class DeferredModel(BaseModel):
        value: int

    class DeferredRootModel(RootModel[list[int]]):
        pass

    assert BaseModel.model_config["defer_build"] is True
    assert RootModel.model_config["defer_build"] is True
    assert DeferredModel.__pydantic_complete__ is False
    assert DeferredRootModel.__pydantic_complete__ is False


def test_disable_logfire_plugin_preserves_other_plugin_settings(monkeypatch):
    monkeypatch.setenv(PYDANTIC_DISABLE_PLUGINS_ENV, "other-plugin")

    metadata_lazy_imports.disable_logfire_plugin()

    assert os.environ[PYDANTIC_DISABLE_PLUGINS_ENV] == "logfire-plugin,other-plugin"


def test_configure_lazy_imports_rejects_invalid_mode(monkeypatch):
    monkeypatch.setenv(LAZY_IMPORTS_ENV, "invalid")
    monkeypatch.setattr(metadata_lazy_imports.sys, "set_lazy_imports_filter", lambda _: None, raising=False)
    monkeypatch.setattr(metadata_lazy_imports.sys, "set_lazy_imports", lambda _: None, raising=False)

    with pytest.raises(ValueError, match=LAZY_IMPORTS_ENV):
        metadata_lazy_imports.configure_lazy_imports()


def test_lazy_import_filter_only_keeps_sqlalchemy_and_pydantic_eager():
    lazy_import_filter = metadata_lazy_imports.set_metadata_lazy_import_filter

    assert lazy_import_filter("galaxy.metadata.set_metadata", "galaxy.model.mapping", None) is True
    assert lazy_import_filter("pydantic.plugin", "logfire.integrations.pydantic", None) is False
    assert lazy_import_filter("logfire", "opentelemetry.sdk.resources", None) is True
    assert lazy_import_filter("galaxy.datatypes.binary", "h5py", None) is True
    assert lazy_import_filter("galaxy.model", "sqlalchemy.orm", None) is False
    assert lazy_import_filter("sqlalchemy.orm", "typing", None) is False
