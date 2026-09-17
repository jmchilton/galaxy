import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from galaxy.job_execution.metadata_constants import (
    LAZY_IMPORTS_ENV,
    LIGHTWEIGHT_MODELS_ENV,
    PYDANTIC_DISABLE_PLUGINS_ENV,
)
from galaxy.job_execution.metadata_lazy_imports import set_metadata_lazy_import_filter

HAS_LAZY_IMPORTS = hasattr(sys, "set_lazy_imports") and hasattr(sys, "set_lazy_imports_filter")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def python_environment():
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "lib")
    environment.pop(LAZY_IMPORTS_ENV, None)
    environment.pop(LIGHTWEIGHT_MODELS_ENV, None)
    environment.pop(PYDANTIC_DISABLE_PLUGINS_ENV, None)
    return environment


def run_python(source, environment):
    return subprocess.run(
        [sys.executable, "-c", source],
        env=environment,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )


def test_external_adapter_bootstraps_metadata_in_fresh_process():
    result = run_python(
        """
import json
import os
import sys

from galaxy_ext.metadata.set_metadata import set_metadata

assert callable(set_metadata)
print(json.dumps({
    "lightweight": os.environ.get("GALAXY_SET_METADATA_LIGHTWEIGHT_MODELS"),
    "plugins": os.environ.get("PYDANTIC_DISABLE_PLUGINS"),
    "model_loaded": "galaxy.model" in sys.modules,
}))
""",
        python_environment(),
    )

    state = json.loads(result.stdout)
    assert state["plugins"] == "logfire-plugin"
    assert state["lightweight"] == ("1" if HAS_LAZY_IMPORTS else None)
    if HAS_LAZY_IMPORTS:
        assert state["model_loaded"] is False


@pytest.mark.parametrize("mode", [None, "normal", "all"])
def test_metadata_import_mode_controls_actual_module_loading(tmp_path, mode):
    marker = tmp_path / "imported"
    probe = tmp_path / "metadata_import_probe.py"
    probe.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\nvalue = 42\n")
    environment = python_environment()
    environment["PYTHONPATH"] = os.pathsep.join((str(tmp_path), environment["PYTHONPATH"]))
    environment[PYDANTIC_DISABLE_PLUGINS_ENV] = "other-plugin"
    # Bootstrap must clear a stale lightweight flag in normal mode and on older Python.
    environment[LIGHTWEIGHT_MODELS_ENV] = "1"
    if mode is not None:
        environment[LAZY_IMPORTS_ENV] = mode

    result = run_python(
        f"""
import json
import os
from pathlib import Path
from galaxy.job_execution.metadata_lazy_imports import configure_lazy_imports

enabled = configure_lazy_imports()
import metadata_import_probe
loaded_before_access = Path({str(marker)!r}).exists()
assert metadata_import_probe.value == 42
assert Path({str(marker)!r}).read_text() == "imported"
print(json.dumps({{
    "enabled": enabled,
    "loaded_before_access": loaded_before_access,
    "lightweight": os.environ.get("GALAXY_SET_METADATA_LIGHTWEIGHT_MODELS"),
    "plugins": os.environ["PYDANTIC_DISABLE_PLUGINS"],
}}))
""",
        environment,
    )

    state = json.loads(result.stdout)
    expected_lazy = HAS_LAZY_IMPORTS and mode != "normal"
    assert state["enabled"] is expected_lazy
    assert state["loaded_before_access"] is not expected_lazy
    assert state["lightweight"] == ("1" if expected_lazy else None)
    assert state["plugins"] == "logfire-plugin,other-plugin"


@pytest.mark.parametrize("lazy_enabled,fails", [(True, False), (False, False), (True, True)])
def test_metadata_runner_finalizes_real_gc_without_swallowing_errors(tmp_path, lazy_enabled, fails):
    marker = tmp_path / "metadata"
    run_python(
        f"""
import gc
from pathlib import Path
from galaxy.job_execution.metadata_runner import run_metadata

gc.unfreeze()
assert gc.get_freeze_count() == 0

def calculate_metadata():
    Path({str(marker)!r}).write_text("metadata complete")
    if {fails!r}:
        raise RuntimeError("metadata failed")

try:
    run_metadata(calculate_metadata, lazy_imports_enabled={lazy_enabled!r})
except RuntimeError as exc:
    assert {fails!r}
    assert str(exc) == "metadata failed"
else:
    assert not {fails!r}

assert Path({str(marker)!r}).read_text() == "metadata complete"
assert (gc.get_freeze_count() > 0) is {lazy_enabled and not fails!r}
""",
        python_environment(),
    )


def test_deferred_pydantic_models_still_validate_in_fresh_process():
    run_python(
        """
from pydantic import BaseModel, RootModel, ValidationError
from galaxy.job_execution.pydantic_defer import defer_pydantic_model_builds

defer_pydantic_model_builds()

class DeferredModel(BaseModel):
    value: int

class DeferredRootModel(RootModel[list[int]]):
    pass

assert not DeferredModel.__pydantic_complete__
assert not DeferredRootModel.__pydantic_complete__
assert DeferredModel(value="42").value == 42
assert DeferredRootModel(["1", "2"]).root == [1, 2]
for model, data in ((DeferredModel, {"value": "invalid"}), (DeferredRootModel, ["invalid"])):
    try:
        model.model_validate(data)
    except ValidationError:
        pass
    else:
        raise AssertionError("Deferred model accepted invalid data")
""",
        python_environment(),
    )


@pytest.mark.skipif(not HAS_LAZY_IMPORTS, reason="Lazy-import configuration requires Python 3.15")
def test_configure_lazy_imports_rejects_invalid_mode():
    environment = python_environment()
    environment[LAZY_IMPORTS_ENV] = "invalid"
    with pytest.raises(subprocess.CalledProcessError) as exc:
        run_python(
            "from galaxy.job_execution.metadata_lazy_imports import configure_lazy_imports; configure_lazy_imports()",
            environment,
        )
    assert "ValueError" in exc.value.stderr
    assert LAZY_IMPORTS_ENV in exc.value.stderr


@pytest.mark.parametrize("plugins", ["__all__", "1", "true"])
def test_disable_logfire_plugin_preserves_disable_all_settings(plugins):
    environment = python_environment()
    environment[PYDANTIC_DISABLE_PLUGINS_ENV] = plugins
    result = run_python(
        """
import os
from galaxy.job_execution.metadata_lazy_imports import disable_logfire_plugin

disable_logfire_plugin()
print(os.environ["PYDANTIC_DISABLE_PLUGINS"])
""",
        environment,
    )
    assert result.stdout.strip() == plugins


def test_lazy_import_filter_only_keeps_sqlalchemy_and_pydantic_eager():
    assert set_metadata_lazy_import_filter("galaxy.metadata.set_metadata", "galaxy.model.mapping", None) is True
    assert set_metadata_lazy_import_filter("pydantic.plugin", "logfire.integrations.pydantic", None) is False
    assert set_metadata_lazy_import_filter("logfire", "opentelemetry.sdk.resources", None) is True
    assert set_metadata_lazy_import_filter("galaxy.datatypes.binary", "h5py", None) is True
    assert set_metadata_lazy_import_filter("galaxy.model", "sqlalchemy.orm", None) is False
    assert set_metadata_lazy_import_filter("sqlalchemy.orm", "typing", None) is False
