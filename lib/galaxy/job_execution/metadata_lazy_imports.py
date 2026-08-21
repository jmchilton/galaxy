"""Configure lazy imports for the external metadata-setting process."""

import os
import sys

from galaxy.job_execution.metadata_constants import (
    LAZY_IMPORTS_ENV,
    LIGHTWEIGHT_MODELS_ENV,
    PYDANTIC_DISABLE_PLUGINS_ENV,
)

_LOGFIRE_PLUGIN = "logfire-plugin"


def _is_sqlalchemy_module(module_name):
    return module_name == "sqlalchemy" or module_name.startswith("sqlalchemy.")


def _is_pydantic_module(module_name):
    return module_name == "pydantic" or module_name.startswith("pydantic.")


def set_metadata_lazy_import_filter(importing_module, imported_module, fromlist):
    # SQLAlchemy's preload registry and Pydantic's plugin loader both assume
    # their own imports resolve eagerly. Galaxy modules remain lazy.
    return not (
        _is_sqlalchemy_module(imported_module)
        or _is_pydantic_module(imported_module)
        or (importing_module is not None and _is_sqlalchemy_module(importing_module))
        or (importing_module is not None and _is_pydantic_module(importing_module))
    )


def disable_logfire_plugin():
    disabled_plugins = os.environ.get(PYDANTIC_DISABLE_PLUGINS_ENV)
    if disabled_plugins in ("__all__", "1", "true"):
        return
    plugins = {plugin for plugin in (disabled_plugins or "").split(",") if plugin}
    plugins.add(_LOGFIRE_PLUGIN)
    os.environ[PYDANTIC_DISABLE_PLUGINS_ENV] = ",".join(sorted(plugins))


def configure_lazy_imports():
    """Enable Python 3.15 lazy imports for this short-lived process only."""
    # The external metadata process does not need Pydantic instrumentation.
    # Disable it before importing any Galaxy modules that construct models.
    disable_logfire_plugin()
    os.environ.pop(LIGHTWEIGHT_MODELS_ENV, None)

    set_lazy_imports = getattr(sys, "set_lazy_imports", None)
    set_lazy_imports_filter = getattr(sys, "set_lazy_imports_filter", None)
    if set_lazy_imports is None or set_lazy_imports_filter is None:
        return False

    mode = os.environ.get(LAZY_IMPORTS_ENV, "all")
    if mode not in ("all", "normal"):
        raise ValueError(f"{LAZY_IMPORTS_ENV} must be 'all' or 'normal', got {mode!r}")
    set_lazy_imports_filter(set_metadata_lazy_import_filter if mode == "all" else None)
    set_lazy_imports(mode)
    if mode == "all":
        os.environ[LIGHTWEIGHT_MODELS_ENV] = "1"
    return mode == "all"
