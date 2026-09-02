from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from galaxy.webapps.galaxy import fast_factory


def _patched_builder(monkeypatch):
    galaxy_app = SimpleNamespace(shutdown=Mock())
    wsgi_app = object()
    asgi_app = object()
    load_app_properties = Mock(return_value={"resolved": "configuration"})
    universe_application = Mock(return_value=galaxy_app)
    app_pair = Mock(return_value=(wsgi_app, galaxy_app))
    init_fast_app = Mock(return_value=asgi_app)
    monkeypatch.setattr(fast_factory, "load_app_properties", load_app_properties)
    monkeypatch.setattr(fast_factory, "GalaxyUniverseApplication", universe_application)
    monkeypatch.setattr(fast_factory, "app_pair", app_pair)
    return galaxy_app, wsgi_app, asgi_app, load_app_properties, universe_application, app_pair, init_fast_app


def test_programmatic_builder_returns_caller_owned_application(monkeypatch):
    (
        galaxy_app,
        wsgi_app,
        asgi_app,
        load_app_properties,
        universe_application,
        app_pair,
        init_fast_app,
    ) = _patched_builder(monkeypatch)

    web_app = fast_factory.build_galaxy_web_app(
        {"setting": "value"},
        global_conf={"__file__": "galaxy.yml"},
        load_app_kwds={"config_section": "galaxy"},
        wsgi_preflight=True,
        register_shutdown_at_exit=False,
        init_fast_app=init_fast_app,
    )

    assert web_app.galaxy_app is galaxy_app
    assert web_app.wsgi_app is wsgi_app
    assert web_app.asgi_app is asgi_app
    load_app_properties.assert_called_once_with(kwds={"setting": "value"}, config_section="galaxy")
    universe_application.assert_called_once_with(
        global_conf={"__file__": "galaxy.yml"},
        is_webapp=True,
        resolved="configuration",
        register_shutdown_at_exit=False,
    )
    app_pair.assert_called_once_with(
        {"__file__": "galaxy.yml"},
        app=galaxy_app,
        wsgi_preflight=True,
        resolved="configuration",
        register_shutdown_at_exit=False,
    )
    init_fast_app.assert_called_once_with(wsgi_app, galaxy_app)
    galaxy_app.shutdown.assert_not_called()


@pytest.mark.parametrize("failure_point", ["wsgi", "asgi"])
def test_programmatic_builder_shuts_down_partial_application(monkeypatch, failure_point):
    galaxy_app, _, _, _, _, app_pair, init_fast_app = _patched_builder(monkeypatch)
    construction_error = RuntimeError(f"{failure_point} construction failed")
    if failure_point == "wsgi":
        app_pair.side_effect = construction_error
    else:
        init_fast_app.side_effect = construction_error

    with pytest.raises(RuntimeError) as raised:
        fast_factory.build_galaxy_web_app(init_fast_app=init_fast_app)

    assert raised.value is construction_error
    galaxy_app.shutdown.assert_called_once_with()


def test_shutdown_failure_does_not_mask_construction_failure(monkeypatch):
    galaxy_app, _, _, _, _, app_pair, init_fast_app = _patched_builder(monkeypatch)
    construction_error = RuntimeError("application construction failed")
    app_pair.side_effect = construction_error
    galaxy_app.shutdown.side_effect = RuntimeError("shutdown failed")

    with pytest.raises(RuntimeError) as raised:
        fast_factory.build_galaxy_web_app(init_fast_app=init_fast_app)

    assert raised.value is construction_error
    galaxy_app.shutdown.assert_called_once_with()
