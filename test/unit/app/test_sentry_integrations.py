import sys
from types import SimpleNamespace

import pytest

from galaxy.app import SentryClientMixin

sentry_sdk = pytest.importorskip("sentry_sdk")


class SentryApp(SentryClientMixin):
    def __init__(self):
        self.config = SimpleNamespace(
            sentry_dsn="https://key@sentry.invalid/1",
            sentry_event_level="ERROR",
            sentry_traces_sample_rate=0.0,
            sentry_ca_certs=None,
            version_major="26.2",
            version_minor="dev",
        )


def _integrations() -> set[str]:
    SentryApp().configure_sentry_client()
    return set(sentry_sdk.get_client().integrations)


def test_sentry_skips_integrations_for_missing_libraries(monkeypatch):
    monkeypatch.setitem(sys.modules, "fastapi", None)
    monkeypatch.delitem(sys.modules, "sentry_sdk.integrations.fastapi", raising=False)
    integrations = _integrations()
    assert "fastapi" not in integrations
    assert {"logging", "starlette", "celery", "sqlalchemy"} <= integrations
