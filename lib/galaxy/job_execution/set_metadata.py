"""Lightweight entry point for the external metadata-setting process."""

from galaxy.job_execution.metadata_lazy_imports import configure_lazy_imports
from galaxy.job_execution.metadata_runner import run_metadata

# Importing this private console-script module is the process bootstrap: lazy
# imports must be configured before the worker is imported. Keeping both at
# module scope avoids hiding dependency edges in local imports.
_LAZY_IMPORTS_ENABLED = configure_lazy_imports()
from galaxy.metadata.set_metadata import set_metadata as _run_set_metadata  # noqa: E402


def set_metadata() -> None:
    run_metadata(_run_set_metadata, _LAZY_IMPORTS_ENABLED)


__all__ = ("set_metadata",)
