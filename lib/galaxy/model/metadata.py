"""Compatibility re-exports for metadata primitives.

The canonical definitions live outside :mod:`galaxy.model` so datatype-only
processes do not construct Galaxy's SQLAlchemy declarative model graph.
"""

from galaxy.datatypes.metadata import *  # noqa: F401,F403
from galaxy.datatypes.metadata import __all__  # noqa: F401
