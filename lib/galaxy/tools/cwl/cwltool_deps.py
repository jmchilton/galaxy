""" This module contains logic for dealing with cwltool as an optional
dependency for Galaxy and/or applications which use Galaxy as a library.
"""

try:
    from galaxy import eggs
    eggs.require("requests")
except Exception:
    pass

try:
    import requests
except ImportError:
    requests = None

try:
    from cwltool import (
        draft2tool,
    )
except ImportError:
    draft2tool = None

try:
    from cwltool.avro_ld import ref_resolver
except ImportError:
    ref_resolver = None

try:
    import avro
except ImportError:
    avro = None


def ensure_cwltool_available():
    if ref_resolver is None or draft2tool is None :
        message = "This feature requires cwltool and dependencies to be available, they are not."
        if avro is None:
            message += " Library avro unavailable."
        if requests is None:
            message += " Library requests unavailable."
        raise ImportError(message)


__all__ = [
    'ref_resolver',
    'draft2tool',
    'ensure_cwltool_available',
]
