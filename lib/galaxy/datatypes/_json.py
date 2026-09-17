"""JSON encoding shared by datatype metadata and the ORM."""

import json

import numpy

from galaxy.util import unicodify


class SafeJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, numpy.int_):
            return int(obj)
        elif isinstance(obj, numpy.float64):
            return float(obj)
        elif isinstance(obj, bytes):
            return unicodify(obj)
        # Let the base class default method raise the TypeError
        return json.JSONEncoder.default(self, obj)


json_encoder = SafeJsonEncoder(sort_keys=True)
