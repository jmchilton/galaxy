"""Validated gxui profiles, precedence, and server-bound authentication settings."""

import copy
import importlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml

BUILTINS: dict[str, Any] = {
    "url": "http://localhost:8080",
    "headless": True,
    "port": 0,
    "idle_timeout": 3600.0,
    "timeout_multiplier": 1.0,
    "client_timeout": 110.0,
    "artifacts": None,
    "playwright_cli": None,
    "session": "default",
}
ENVIRONMENT = {key: f"GXUI_{key.upper()}" for key in BUILTINS}
ENVIRONMENT["url"] = "GXUI_GALAXY_URL"
AUTH_KEYS = {"username", "password", "password_env", "keyring", "storage_state"}
AUTH_SOURCES = AUTH_KEYS - {"username"}
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


class ConfigError(ValueError):
    """A configuration error suitable for printing without a traceback."""


class _UniqueLoader(yaml.SafeLoader):  # type: ignore[misc]  # PyYAML does not ship loader stubs.
    def construct_mapping(self, node: Any, deep: bool = False) -> Any:
        self.flatten_mapping(node)
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        try:
            if len(set(keys)) != len(keys):
                raise ConfigError("duplicate YAML configuration key")
        except TypeError:
            raise ConfigError("YAML configuration keys must be strings") from None
        return super().construct_mapping(node, deep=deep)


def config_path(explicit: str | None = None) -> Path:
    return (
        Path(
            explicit
            or os.environ.get("GXUI_CONFIG")
            or Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")) / "gxui/config.yml"
        )
        .expanduser()
        .absolute()
    )


def server_url(value: str) -> str:
    """Canonical Galaxy base URL, including a deployment's path prefix."""
    try:
        url = urlsplit(value)
        port = url.port
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError
    except ValueError:
        raise ConfigError("url must be an HTTP(S) Galaxy base URL without credentials, query or fragment") from None
    host = url.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port and (url.scheme, port) not in (("https", 443), ("http", 80)):
        host += f":{port}"
    return urlunsplit((url.scheme, host, url.path.rstrip("/"), "", ""))


def value_for(key: str, value: Any) -> Any:
    if key not in BUILTINS:
        raise ConfigError(f"unknown setting {key!r}")
    if key == "headless":
        if isinstance(value, str) and value.lower() in ("true", "false", "1", "0", "yes", "no"):
            return value.lower() in ("true", "1", "yes")
        if not isinstance(value, bool):
            raise ConfigError("headless must be true or false")
    elif key in ("port", "idle_timeout", "timeout_multiplier", "client_timeout"):
        try:
            if isinstance(value, bool):
                raise ValueError
            number = float(value)
            if (
                not math.isfinite(number)
                or number < 0
                or (key in ("timeout_multiplier", "client_timeout") and number == 0)
            ):
                raise ValueError
            if key == "port":
                if number != int(number) or number > 65535:
                    raise ValueError
                return int(number)
            return number
        except (ValueError, TypeError):
            raise ConfigError(f"{key} must be a valid positive number (port and idle_timeout allow 0)") from None
    elif value is not None and not isinstance(value, str):
        raise ConfigError(f"{key} must be a string")
    if key == "url":
        if not value:
            raise ConfigError("url cannot be empty")
        server_url(value)
    if key == "session" and (not isinstance(value, str) or not NAME.fullmatch(value)):
        raise ConfigError("session must contain only letters, numbers, underscores, dots or hyphens")
    return value


def validate(data: dict[str, Any]) -> None:
    if set(data) - {"version", "default_profile", "defaults", "profiles"}:
        raise ConfigError("unknown top-level configuration key")
    if type(data.get("version", 1)) is not int or data.get("version", 1) != 1:
        raise ConfigError("unsupported config version; expected 1")
    defaults, profiles = data.get("defaults", {}), data.get("profiles", {})
    if not isinstance(defaults, dict) or not isinstance(profiles, dict):
        raise ConfigError("defaults and profiles must be mappings")
    for key, value in defaults.items():
        value_for(key, value)
    for name, profile in profiles.items():
        if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(profile, dict):
            raise ConfigError("profiles require simple names and mapping values")
        if not profile.get("url"):
            raise ConfigError(f"profile {name!r} requires url")
        for key, value in profile.items():
            if key != "auth":
                value_for(key, value)
        auth = profile.get("auth", {})
        if not isinstance(auth, dict) or set(auth) - AUTH_KEYS:
            raise ConfigError(f"invalid auth settings in profile {name!r}")
        if len(AUTH_SOURCES & auth.keys()) > 1:
            raise ConfigError("choose one auth source: password, password_env, keyring or storage_state")
        for key, value in auth.items():
            if key == "keyring":
                if value is not True:
                    raise ConfigError("auth.keyring must be true")
            elif not isinstance(value, str) or not value:
                raise ConfigError(f"auth.{key} must be a nonempty string")
    if data.get("default_profile") is not None and (
        not isinstance(data["default_profile"], str) or data["default_profile"] not in profiles
    ):
        raise ConfigError("default_profile must name an existing profile")


def private_json(path: Path, data: dict[str, Any]) -> None:
    atomic_write(path, json.dumps(data))


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@dataclass
class ConfigFile:
    path: Path
    data: dict[str, Any]
    legacy: bool = False

    @classmethod
    def load(cls, explicit: str | None = None, missing_ok: bool = False) -> "ConfigFile":
        path = config_path(explicit)
        try:
            with path.open() as handle:
                data = yaml.load(handle, Loader=_UniqueLoader)
                if data is None:
                    data = {}
        except FileNotFoundError:
            if not missing_ok and (explicit or os.environ.get("GXUI_CONFIG")):
                raise ConfigError(f"config not found: {path}") from None
            data = {}
        except (OSError, yaml.YAMLError):
            raise ConfigError(f"cannot read YAML config: {path}") from None
        if not isinstance(data, dict):
            raise ConfigError("config must be a YAML mapping")
        legacy = bool({"login_email", "login_password", "local_galaxy_url"} & data.keys()) and "profiles" not in data
        if not legacy:
            validate(data)
        return cls(path, data, legacy)

    def write(self, data: dict[str, Any]) -> None:
        if self.legacy:
            raise ConfigError("legacy files are read-only; create a profile config at a new path")
        validate(data)
        atomic_write(self.path, yaml.safe_dump(data, sort_keys=False))
        self.data = data

    def selected_profile(self, explicit: str | None = None) -> str | None:
        name = explicit or os.environ.get("GXUI_PROFILE") or self.data.get("default_profile")
        if name and name not in self.data.get("profiles", {}):
            raise ConfigError(f"unknown profile {name!r}")
        return name

    def set(self, key: str, value: Any, profile: str | None) -> None:
        self._edit(key, value, profile, False)

    def unset(self, key: str, profile: str | None) -> None:
        self._edit(key, None, profile, True)

    def _edit(self, key: str, value: Any, profile: str | None, remove: bool) -> None:
        data = copy.deepcopy(self.data)
        parts = key.split(".")
        if key in ("version", "default_profile") or parts[0] in ("defaults", "profiles"):
            target = data
        else:
            name = self.selected_profile(profile)
            if not name:
                raise ConfigError("select a profile with --profile or set default_profile")
            target = data.setdefault("profiles", {})[name]
        for part in parts[:-1]:
            target = target.setdefault(part, {})
            if not isinstance(target, dict):
                raise ConfigError("config key traverses a value rather than a mapping")
        if remove:
            target.pop(parts[-1], None)
        else:
            if (parts[-1] in AUTH_SOURCES or (parts[-1] == "username" and target.get("username") != value)) and (
                parts[0] == "auth" or "auth" in parts[:-1]
            ):
                for source in AUTH_SOURCES - {parts[-1]}:
                    target.pop(source, None)
            target[parts[-1]] = value
        self.write(data)


def redacted(data: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(data)
    for key, value in result.items():
        if key in ("password", "login_password"):
            result[key] = "<redacted>"
        elif isinstance(value, dict):
            result[key] = redacted(value)
    return result


@dataclass
class Settings:
    config: ConfigFile
    profile: str | None
    values: dict[str, Any]
    auth: dict[str, Any]
    sources: dict[str, str]

    def credentials(self) -> tuple[str, str]:
        username = self.auth.get("username", "")
        password = self.auth.get("password", "")
        if variable := self.auth.get("password_env"):
            password = os.environ.get(variable, "")
            if not password:
                raise ConfigError(f"password environment variable {variable} is unset or empty; set it before login")
        if self.auth.get("keyring"):
            if not username:
                raise ConfigError("auth.keyring requires auth.username")
            try:
                keyring = importlib.import_module("keyring")
                password = keyring.get_password(f'gxui:{server_url(self.values["url"])}', username) or ""
            except ImportError:
                raise ConfigError("install galaxy-selenium[keyring] to use auth.keyring") from None
            except Exception:
                raise ConfigError("could not read gxui credentials from the keyring") from None
        return username, password

    def display(self, sources: bool = False) -> dict[str, Any]:
        result = {"config": str(self.config.path), "profile": self.profile, **self.values, "auth": redacted(self.auth)}
        if sources:
            result["sources"] = self.sources
        return result


def resolve(overrides: dict[str, Any] | None = None) -> Settings:
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    config = ConfigFile.load(overrides.get("config"))
    profile = config.selected_profile(overrides.get("profile"))
    values = BUILTINS.copy()
    sources = dict.fromkeys(values, "builtin")
    sources["config"] = (
        "CLI" if overrides.get("config") else "GXUI_CONFIG" if os.environ.get("GXUI_CONFIG") else "default path"
    )
    sources["profile"] = (
        "CLI" if overrides.get("profile") else "GXUI_PROFILE" if os.environ.get("GXUI_PROFILE") else "default_profile"
    )
    defaults = config.data.get("defaults", {}) if not config.legacy else {}
    selected = config.data.get("profiles", {}).get(profile, {})
    if config.legacy:
        selected = {"url": config.data.get("local_galaxy_url", values["url"])}
    for label, layer in (("defaults", defaults), (f"profile:{profile}", selected)):
        for key, value in layer.items():
            if key in BUILTINS:
                values[key], sources[key] = value_for(key, value), label
    if profile and sources["session"] == "builtin":
        values["session"], sources["session"] = profile, f"profile:{profile}"
    for key, variable in ENVIRONMENT.items():
        if variable in os.environ:
            values[key], sources[key] = value_for(key, os.environ[variable]), variable
    for key, value in overrides.items():
        if key in BUILTINS:
            values[key], sources[key] = value_for(key, value), "CLI"
    auth = copy.deepcopy(selected.get("auth", {}))
    if config.legacy:
        auth = {
            k: config.data[v]
            for k, v in (("username", "login_email"), ("password", "login_password"))
            if config.data.get(v)
        }
    elif auth and server_url(values["url"]) != server_url(selected["url"]):
        auth = {}
        sources["auth"] = "cleared: URL override differs from profile"
    else:
        sources["auth"] = f"profile:{profile}" if auth else "builtin"
    auth_environment = {
        key: os.environ[variable]
        for key, variable in (
            ("username", "GXUI_USERNAME"),
            ("password", "GXUI_PASSWORD"),
            ("storage_state", "GXUI_STORAGE_STATE"),
        )
        if variable in os.environ
    }
    for label, layer in (("environment", auth_environment), ("CLI", overrides)):
        selected_sources = AUTH_SOURCES & layer.keys()
        if len(selected_sources) > 1:
            raise ConfigError(f"choose one authentication source in {label}")
        if "username" in layer and layer["username"] != auth.get("username"):
            auth = {k: v for k, v in auth.items() if k not in AUTH_SOURCES}
        for key in AUTH_KEYS & layer.keys():
            value = layer[key]
            if key in AUTH_SOURCES:
                auth = {k: v for k, v in auth.items() if k not in AUTH_SOURCES}
            auth[key] = str(Path(value).expanduser().absolute()) if key == "storage_state" else value
            sources[f"auth.{key}"] = label if label == "CLI" else f"GXUI_{key.upper()}"
    for key in ("artifacts",):
        if values[key]:
            values[key] = str(Path(values[key]).expanduser().absolute())
    if auth.get("storage_state"):
        path = Path(auth["storage_state"]).expanduser()
        auth["storage_state"] = str((config.path.parent / path).absolute() if not path.is_absolute() else path)
    return Settings(config, profile, values, auth, sources)
