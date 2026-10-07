"""Configuration precedence and credential boundaries without a Galaxy installation."""

import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from galaxy.selenium.gxui import client
from galaxy.selenium.gxui.config import ConfigError, ConfigFile, resolve


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("GXUI_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "gxui" / "config.yml"
    path.parent.mkdir()
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "default_profile": "test",
                "defaults": {"headless": True, "idle_timeout": 60, "timeout_multiplier": 2},
                "profiles": {
                    "test": {
                        "url": "https://example.org/galaxy/",
                        "idle_timeout": 30,
                        "auth": {"username": "me@example.org", "password_env": "TEST_PASSWORD"},
                    }
                },
            }
        )
    )
    return path


def test_precedence_and_sources(config_file, monkeypatch):
    monkeypatch.setenv("GXUI_IDLE_TIMEOUT", "15")
    settings = resolve({"idle_timeout": 0})
    assert settings.values["idle_timeout"] == 0
    assert settings.sources["idle_timeout"] == "CLI"
    assert settings.values["timeout_multiplier"] == 2
    assert settings.sources["timeout_multiplier"] == "defaults"
    assert settings.profile == "test"
    assert resolve().values["idle_timeout"] == 15
    monkeypatch.delenv("GXUI_IDLE_TIMEOUT")
    assert resolve().values["idle_timeout"] == 30


def test_false_overrides_true(config_file, monkeypatch):
    monkeypatch.setenv("GXUI_HEADLESS", "false")
    assert resolve().values["headless"] is False
    assert resolve({"headless": True}).values["headless"] is True


def test_credentials_bound_to_full_base_url(config_file, monkeypatch):
    monkeypatch.setenv("TEST_PASSWORD", "test-only-secret")
    assert resolve({"url": "https://example.org/galaxy"}).credentials() == ("me@example.org", "test-only-secret")
    for url in ("https://other.org/galaxy", "https://example.org/other", "http://example.org/galaxy"):
        settings = resolve({"url": url})
        assert settings.auth == {}
        assert settings.credentials() == ("", "")


def test_show_redacts_without_reading_password_environment(config_file, monkeypatch):
    monkeypatch.setenv("TEST_PASSWORD", "test-only-secret")
    output = json.dumps(resolve().display(sources=True))
    assert "test-only-secret" not in output
    assert "TEST_PASSWORD" in output
    assert "environment" not in output  # the reference is visible, never dereferenced for display


def test_missing_password_environment_actionable(config_file):
    with pytest.raises(ConfigError, match="TEST_PASSWORD"):
        resolve().credentials()


def test_legacy_file(config_file):
    config_file.write_text("login_email: me@example.org\nlogin_password: local-secret\nunused: compatible\n")
    settings = resolve({"config": str(config_file), "url": "http://localhost:8080"})
    assert settings.credentials() == ("me@example.org", "local-secret")
    assert "local-secret" not in json.dumps(settings.display())


@pytest.mark.parametrize(
    "patch",
    [
        {"version": 99},
        {"defaults": {"headless": "maybe"}},
        {"defaults": {"idle_timeout": -1}},
        {"defaults": {"timeout_multiplier": 0}},
        {"defaults": {"port": 65536}},
        {"profiles": {"test": {"url": "ftp://example.org"}}},
        {"profiles": {"test": {"url": "https://example.org", "auth": {"password": "x", "password_env": "Y"}}}},
        {"defaults": {"typo_timeout": 5}},
        {"profiles": []},
    ],
)
def test_invalid_config_is_a_usage_error(config_file, patch):
    data = yaml.safe_load(config_file.read_text())
    data.update(patch)
    config_file.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigError):
        resolve()


def test_unknown_profile_and_missing_explicit_file(config_file):
    with pytest.raises(ConfigError, match="unknown profile"):
        resolve({"profile": "missing"})
    with pytest.raises(ConfigError, match="not found"):
        resolve({"config": str(config_file.parent / "missing.yml")})


def test_config_edit_is_validated_atomic_and_private(config_file):
    config = ConfigFile.load(str(config_file))
    original = config_file.read_text()
    with pytest.raises(ConfigError):
        config.set("defaults.headless", "maybe", None)
    assert config_file.read_text() == original
    config.set("auth.username", "someone@example.org", "test")
    assert yaml.safe_load(config_file.read_text())["profiles"]["test"]["auth"]["username"] == "someone@example.org"
    assert config_file.stat().st_mode & 0o777 == 0o600
    config.unset("auth.password_env", "test")
    assert "password_env" not in yaml.safe_load(config_file.read_text())["profiles"]["test"]["auth"]


def test_offline_config_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("GXUI_CONFIG", raising=False)
    request = Mock(side_effect=AssertionError("must not contact daemon"))
    monkeypatch.setattr(client, "request", request)
    assert client.main(["config", "init"]) == 0
    assert client.main(["config", "profile", "add", "local", "--url", "http://localhost:8080"]) == 0
    assert client.main(["config", "set", "default_profile", "local"]) == 0
    assert client.main(["--profile", "local", "config", "set", "auth.username", "me@example.org"]) == 0
    assert client.main(["--profile", "local", "config", "show", "--resolved", "--sources"]) == 0
    assert "me@example.org" in capsys.readouterr().out
    request.assert_not_called()


def test_profile_password_setting_prompts_without_echo(config_file, monkeypatch, capsys):
    monkeypatch.setattr(client.getpass, "getpass", lambda prompt: "private-example")
    assert client.main(["config", "unset", "auth.password_env"]) == 0
    assert client.main(["config", "set", "auth.password"]) == 0
    assert "private-example" not in capsys.readouterr().out
    assert yaml.safe_load(config_file.read_text())["profiles"]["test"]["auth"]["password"] == "private-example"


def test_invalid_environment_returns_clean_error(config_file, monkeypatch, capsys):
    monkeypatch.setenv("GXUI_IDLE_TIMEOUT", "bad")
    assert client.main(["status"]) == 1
    assert "idle_timeout" in capsys.readouterr().err


def test_login_missing_credentials_noninteractive(config_file, monkeypatch, capsys):
    monkeypatch.setattr(client.sys.stdin, "isatty", lambda: False)

    def request(session, payload, **kw):
        if payload["op"] == "auth-info":
            return {"ok": False, "error": "password environment variable TEST_PASSWORD is unset or empty"}
        return {"ok": True, "binding": {"url": "https://example.org/galaxy/", "profile": "test"}, "result": "running"}

    monkeypatch.setattr(client, "request", request)
    assert client.main(["login"]) == 1
    assert "TEST_PASSWORD" in capsys.readouterr().err


def test_start_rejects_other_server(config_file, monkeypatch):
    monkeypatch.setattr(
        client,
        "request",
        lambda *a, **kw: {
            "ok": True,
            "binding": {"url": "https://different.org", "profile": "test"},
            "result": "running",
        },
    )
    reply = client.start("test", [])
    assert reply["ok"] is False
    assert "different" in reply["error"]


def test_url_username_and_password_not_accepted_in_url(config_file):
    with pytest.raises(ConfigError):
        resolve({"url": "https://user:password@example.org"})


def test_set_auth_source_replaces_previous_one(config_file):
    config = ConfigFile.load(str(config_file))
    config.set("auth.password", "literal-example", "test")
    assert config.data["profiles"]["test"]["auth"] == {"username": "me@example.org", "password": "literal-example"}


def test_optional_keyring_uses_server_and_username(config_file, monkeypatch):
    import sys

    config = ConfigFile.load(str(config_file))
    config.set("auth.keyring", True, "test")
    keyring = Mock()
    keyring.get_password.return_value = "keyring-example"
    monkeypatch.setitem(sys.modules, "keyring", keyring)
    assert resolve().credentials() == ("me@example.org", "keyring-example")
    keyring.get_password.assert_called_once_with("gxui:https://example.org/galaxy", "me@example.org")
    assert "keyring-example" not in json.dumps(resolve().display())


def test_missing_optional_keyring_is_actionable(config_file, monkeypatch):
    import sys

    config = ConfigFile.load(str(config_file))
    config.set("auth.keyring", True, "test")
    monkeypatch.setitem(sys.modules, "keyring", None)
    with pytest.raises(ConfigError, match=r"galaxy-selenium\[keyring\]"):
        resolve().credentials()


def test_environment_config_profile_and_cli_profile_priority(config_file, monkeypatch, tmp_path):
    config = ConfigFile.load(str(config_file))
    config.set("profiles.local", {"url": "http://localhost:8080"}, None)
    monkeypatch.setenv("GXUI_CONFIG", str(config_file))
    monkeypatch.setenv("GXUI_PROFILE", "local")
    assert resolve().profile == "local"
    assert resolve({"profile": "test"}).profile == "test"
    assert resolve().values["session"] == "local"
    assert resolve({"session": "other"}).values["session"] == "other"
    other = tmp_path / "other.yml"
    other.write_text("version: 1\nprofiles:\n  local:\n    url: https://different.org\n")
    assert resolve({"config": str(other)}).values["url"] == "https://different.org"


def test_password_stdin_and_prompts_travel_in_payload(config_file, monkeypatch):
    import io

    captured = []

    def request(session, payload, **kw):
        captured.append(payload)
        if payload["op"] == "status":
            return {
                "ok": True,
                "result": "running",
                "binding": {"url": "https://example.org/galaxy/", "profile": "test"},
            }
        if payload["op"] == "auth-info":
            return {
                "ok": True,
                "result": {"username": "me@example.org", "password_available": bool(payload["password"])},
            }
        return {"ok": True, "result": "logged in"}

    monkeypatch.setattr(client, "request", request)
    monkeypatch.setattr(client.sys, "stdin", io.StringIO("stdin-example\n"))
    assert client.main(["login", "--password-stdin"]) == 0
    assert captured[-1]["password"] == "stdin-example"
    captured.clear()
    monkeypatch.setattr(client.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(client.getpass, "getpass", lambda prompt: "prompt-example")
    assert client.main(["login"]) == 0
    assert captured[-1]["password"] == "prompt-example"
    assert all("argv" not in payload for payload in captured)


def test_noninteractive_missing_password_has_no_prompt(config_file, monkeypatch, capsys):
    monkeypatch.setattr(client.sys.stdin, "isatty", lambda: False)

    def request(session, payload, **kw):
        if payload["op"] == "status":
            return {"ok": True, "result": "running"}
        return {"ok": True, "result": {"username": "me@example.org", "password_available": False}}

    monkeypatch.setattr(client, "request", request)
    assert client.main(["login"]) == 1
    assert "--password-stdin" in capsys.readouterr().err


def test_cli_headed_flag_overrides_environment(config_file, monkeypatch):
    captured = {}

    def start(session, argv, options):
        captured.update(resolve(options).values)
        return {"ok": True, "result": "running"}

    monkeypatch.setattr(client, "start", start)
    monkeypatch.setenv("GXUI_HEADLESS", "true")
    assert client.main(["start", "--headed"]) == 0
    assert captured["headless"] is False


@pytest.mark.parametrize(
    "content",
    ["[]", "false", "version: 1\nversion: 1\n", "default_profile: []\n", "defaults: {headless: true, headless: false}"],
)
def test_malformed_yaml_structure_has_clean_error(config_file, content):
    config_file.write_text(content)
    with pytest.raises(ConfigError):
        resolve()


def test_malformed_config_set_value_has_clean_error(config_file, capsys):
    assert client.main(["config", "set", "defaults.headless", "["]) == 1
    assert "YAML" in capsys.readouterr().err


def test_profile_relative_and_explicit_storage_state_paths(config_file):
    config = ConfigFile.load(str(config_file))
    config.set("auth.storage_state", "auth.json", "test")
    assert resolve().auth["storage_state"] == str(config_file.parent / "auth.json")
    assert resolve({"storage_state": "explicit.json"}).auth["storage_state"] == str(Path.cwd() / "explicit.json")


def test_authentication_overrides_follow_precedence(config_file, monkeypatch):
    monkeypatch.setenv("GXUI_STORAGE_STATE", "/tmp/example.json")
    assert resolve({"password": "explicit-example"}).auth["password"] == "explicit-example"
    assert "storage_state" not in resolve({"password": "explicit-example"}).auth
    monkeypatch.delenv("GXUI_STORAGE_STATE")
    monkeypatch.setenv("GXUI_USERNAME", "other@example.org")
    assert resolve().auth == {"username": "other@example.org"}
    monkeypatch.setenv("GXUI_PASSWORD", "env-example")
    assert resolve().credentials() == ("other@example.org", "env-example")


def test_conflicting_environment_auth_sources_report_error(config_file, monkeypatch):
    monkeypatch.setenv("GXUI_PASSWORD", "env-example")
    monkeypatch.setenv("GXUI_STORAGE_STATE", "/tmp/example.json")
    with pytest.raises(ConfigError, match="choose one authentication source"):
        resolve()


def test_startup_settings_use_pipe_not_process_arguments(config_file, monkeypatch, tmp_path):
    monkeypatch.setenv("GXUI_HOME", str(tmp_path / "runtime"))
    monkeypatch.setenv("GXUI_PASSWORD", "startup-example")
    replies = iter([{"ok": False}, {"ok": True, "result": "running"}])
    monkeypatch.setattr(client, "request", lambda *a, **kw: next(replies))
    process = Mock()
    process.poll.return_value = None
    popen = Mock(return_value=process)
    monkeypatch.setattr(client.subprocess, "Popen", popen)
    assert client.start("test", [])["ok"] is True
    assert "startup-example" not in json.dumps(popen.call_args.args)
    startup = json.loads(process.stdin.write.call_args.args[0])
    assert startup["auth"]["password"] == "startup-example"
    process.stdin.close.assert_called_once()
