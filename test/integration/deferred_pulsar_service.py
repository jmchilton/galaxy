"""Serve real Pulsar HTTP API in a separately sandboxed process."""

import json
import logging
import sys
from pathlib import Path
from wsgiref.simple_server import make_server

from pulsar.web.wsgi import init_webapp

logging.basicConfig(level=logging.DEBUG)
settings = json.loads(Path(sys.argv[1]).read_text())
try:
    Path(settings.pop("probe")).read_bytes()
except PermissionError:
    pass
else:
    raise RuntimeError("Pulsar can read Galaxy storage: isolation probe failed")
ready = settings.pop("ready")
app = init_webapp(local_conf=settings, config_dir=str(Path(sys.argv[1]).parent))
server = make_server("127.0.0.1", 0, app)
Path(ready).write_text(json.dumps({"port": server.server_port, "isolation_probe": "denied"}))
try:
    server.serve_forever()
finally:
    app.shutdown()
