"""Run metadata setting and finalize its short-lived interpreter."""

import gc
from collections.abc import Callable


def run_metadata(run_set_metadata: Callable[[], None], lazy_imports_enabled: bool) -> None:
    run_set_metadata()
    if lazy_imports_enabled:
        # CPython otherwise spends about half a second repeatedly tracing the
        # large, cyclic Galaxy model graph during interpreter shutdown. This is
        # a dedicated short-lived process, so let the OS reclaim those cycles
        # after normal atexit handling and stream flushing have taken place.
        gc.freeze()
