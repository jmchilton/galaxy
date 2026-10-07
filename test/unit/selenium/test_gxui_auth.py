"""Login lifecycle, account checks, and redaction around the daemon boundary."""

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock

import pytest

from galaxy.selenium.gxui.config import ConfigFile, Settings
from galaxy.selenium.gxui.daemon import Daemon, Transcript
from galaxy.selenium.gxui.verbs import REGISTRY


@pytest.fixture
def daemon(tmp_path):
    daemon = object.__new__(Daemon)
    daemon.args = Namespace(url="https://example.org/galaxy", headed=False, config=None)
    daemon.settings = Settings(
        ConfigFile(tmp_path / "config.yml", {}),
        "test",
        {"url": daemon.args.url},
        {"username": "me@example.org", "password": "test-secret"},
        {},
    )
    daemon.ctx = Mock()
    daemon.ctx.is_logged_in.return_value = False
    daemon.ctx.get_logged_in_user.return_value = {"email": "me@example.org", "username": "me", "id": "user"}
    daemon.ctx.page.context.storage_state.return_value = {"cookies": [], "origins": []}
    daemon.transcript = Transcript(str(tmp_path / "transcript.jsonl"))
    daemon.secrets = set()
    daemon.resume_state = None
    daemon.dialogs = []
    return daemon


def test_login_uses_captured_credentials_and_verified_user(daemon):
    assert daemon.auth_info({})["result"]["password_available"] is True
    reply = daemon.run_login({})
    assert reply["ok"] is True
    daemon.ctx.submit_login.assert_called_once_with("me@example.org", "test-secret")
    assert "test-secret" not in Path(daemon.transcript.path).read_text()


def test_changing_account_clears_configured_password(daemon):
    assert daemon.credentials({"email": "other@example.org"}) == ("other@example.org", "")
    assert daemon.credentials({"email": "other@example.org", "password": "explicit-secret"}) == (
        "other@example.org",
        "explicit-secret",
    )


def test_existing_login_needs_no_password(daemon):
    daemon.ctx.is_logged_in.return_value = True
    daemon.settings.auth = {"username": "me@example.org", "password_env": "MISSING_EXAMPLE"}
    assert daemon.auth_info({})["result"]["logged_in"] is True
    assert daemon.run_login({})["ok"] is True
    daemon.ctx.submit_login.assert_not_called()


def test_wrong_account_never_saves_state(daemon, tmp_path):
    daemon.ctx.is_logged_in.return_value = True
    daemon.ctx.get_logged_in_user.return_value = {"email": "other@example.org"}
    path = tmp_path / "state.json"
    reply = daemon.run_login({"storage_state": str(path)})
    assert reply["ok"] is False and "logout" in reply["error"]
    assert not path.exists()


def test_login_requires_galaxy_confirmation_before_save(daemon, tmp_path):
    daemon.ctx.get_logged_in_user.return_value = None
    path = tmp_path / "state.json"
    reply = daemon.run_login({"storage_state": str(path)})
    assert reply["ok"] is False and "confirmed" in reply["error"]
    assert not path.exists()


def test_interactive_login_reopens_headed_and_saves_after_confirmation(daemon, tmp_path):
    daemon.ctx.is_logged_in.side_effect = [False, False, True]
    daemon.relaunch = Mock()
    path = tmp_path / "state.json"
    reply = daemon.run_login({"interactive": True, "timeout": 5, "storage_state": str(path)})
    assert reply["ok"] is True
    assert daemon.args.headed is True
    daemon.relaunch.assert_called_once()
    daemon.ctx.page.wait_for_timeout.assert_called_once_with(250)
    daemon.ctx.submit_login.assert_not_called()
    assert json.loads(path.read_text())["_gxui"]["url"] == daemon.args.url
    assert path.stat().st_mode & 0o777 == 0o600


def test_interactive_timeout_does_not_save(daemon, tmp_path, monkeypatch):
    daemon.args.headed = True
    monkeypatch.setattr("galaxy.selenium.gxui.daemon.time.monotonic", Mock(side_effect=[0, 10]))
    path = tmp_path / "state.json"
    reply = daemon.run_login({"interactive": True, "timeout": 5, "storage_state": str(path)})
    assert reply["ok"] is False and "timed out" in reply["error"]
    assert not path.exists()


def test_authentication_failure_redacts_exception_and_last(daemon):
    daemon.ctx.submit_login.side_effect = ValueError("test-secret was rejected")
    reply = daemon.run_login({})
    assert reply["ok"] is False
    assert "test-secret" not in json.dumps(reply)
    assert "test-secret" not in json.dumps(daemon.transcript.last_call)


def test_legacy_verb_redacts_password_while_busy_and_in_failure(daemon, monkeypatch, capsys):
    def fail(ctx, **kwargs):
        assert "direct-secret" not in daemon.busy
        raise ValueError("direct-secret failed")

    monkeypatch.setattr(REGISTRY["login"], "func", fail)
    reply = daemon.run_verb(["login", "--password", "direct-secret"])
    assert reply["ok"] is False
    assert "direct-secret" not in json.dumps(daemon.transcript.last_call)
    assert "direct-secret" not in capsys.readouterr().out
