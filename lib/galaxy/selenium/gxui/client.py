"""Thin gxui client. Browser and Galaxy imports stay in the daemon.

gxui [status]                 daemon, browser and Galaxy status for the session
gxui start [options]          start the session's daemon (idempotent), print its CDP URL
gxui stop | last              stop the daemon | print the latest transcript entry
gxui <verb> [args...]         run a verb; `gxui help` lists them
"""

import argparse
import getpass
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from .config import (
    ConfigError,
    ConfigFile,
    redacted,
    resolve,
    server_url,
    Settings,
)

DEFAULT_CLIENT_TIMEOUT = 110.0  # under Claude Code's 2 min Bash default
MAX_SOCKET_PATH = 100  # macOS caps AF_UNIX paths at ~104 bytes


def gxui_home() -> str:
    return os.environ.get("GXUI_HOME", os.path.expanduser("~/.cache/gxui"))


def session_paths(session: str) -> dict[str, str]:
    home = gxui_home()
    sock = os.path.join(home, f"{session}.sock")
    if len(sock) > MAX_SOCKET_PATH:
        sock = os.path.join("/tmp", f"gxui-{hashlib.sha1(sock.encode()).hexdigest()[:12]}.sock")
    return {
        "sock": sock,
        "meta": os.path.join(home, f"{session}.json"),
        "log": os.path.join(home, f"{session}.log"),
        "artifacts": os.path.join(home, session),
    }


def remove_stale(session: str) -> None:
    paths = session_paths(session)
    for key in ("sock", "meta"):
        if os.path.exists(paths[key]):
            os.unlink(paths[key])


def request(session: str, payload: dict, timeout: float | None = None) -> dict:
    sock_path = session_paths(session)["sock"]
    client = socket.socket(socket.AF_UNIX)
    client.settimeout(timeout)
    try:
        client.connect(sock_path)
    except (FileNotFoundError, ConnectionRefusedError):
        stale = os.path.exists(sock_path)
        remove_stale(session)
        note = " (removed a stale socket)" if stale else ""
        return {"ok": False, "error": f"no gxui daemon for session {session!r}{note}; run `gxui start`"}
    try:
        with client:
            client.sendall(json.dumps(payload).encode() + b"\n")
            data = b""
            while chunk := client.recv(65536):
                data += chunk
    except TimeoutError:
        return {
            "ok": False,
            "timeout": True,
            "error": f"no reply within {timeout:.0f}s; the daemon keeps going - run `gxui last` for the result",
        }
    return json.loads(data)


def settings_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, allow_abbrev=False)
    for name in ("config", "profile", "session", "url", "storage-state", "artifacts", "playwright-cli"):
        parser.add_argument(f"--{name}")
    for name in ("port", "idle-timeout", "timeout-multiplier", "client-timeout"):
        parser.add_argument(f"--{name}")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--headed", dest="headless", action="store_false", default=None)
    group.add_argument("--headless", dest="headless", action="store_true", default=None)
    return parser


def check_binding(settings: Settings, reply: dict) -> None:
    binding = reply.get("binding", {})
    if binding and (
        server_url(binding["url"]) != server_url(settings.values["url"]) or binding.get("profile") != settings.profile
    ):
        raise ConfigError(
            f"session is running against {binding['url']} (profile {binding.get('profile')!r}); "
            f"requested {settings.values['url']}; use another --session or stop it before changing the target"
        )


def start(session: str, argv: list[str], overrides: dict | None = None) -> dict:
    options = {
        **(overrides or {}),
        **{k: v for k, v in vars(settings_parser("gxui start").parse_args(argv)).items() if v is not None},
    }
    settings = resolve(options)
    status = request(session, {"op": "status"}, timeout=5)
    if status.get("ok"):
        try:
            check_binding(settings, status)
        except ConfigError as e:
            return {"ok": False, "error": str(e)}
        status["result"] = "already running; " + status["result"]
        return status

    paths = session_paths(session)
    os.makedirs(gxui_home(), exist_ok=True, mode=0o700)
    command = [
        sys.executable,
        "-m",
        "galaxy.selenium.gxui.daemon",
        "--session",
        session,
        "--sock",
        paths["sock"],
        "--meta",
        paths["meta"],
        "--artifacts",
        settings.values["artifacts"] or paths["artifacts"],
        "--url",
        settings.values["url"],
        "--port",
        str(settings.values["port"]),
        "--idle-timeout",
        str(settings.values["idle_timeout"]),
        "--timeout-multiplier",
        str(settings.values["timeout_multiplier"]),
        "--settings-stdin",
    ]
    if settings.values["playwright_cli"]:
        command += ["--playwright-cli", settings.values["playwright_cli"]]
    if not settings.values["headless"]:
        command.append("--headed")
    # Startup settings travel over a pipe, never process arguments or a second credentials file.
    startup = {
        "config": str(settings.config.path),
        "profile": settings.profile,
        "values": settings.values,
        "auth": settings.auth,
    }
    with open(paths["log"], "a") as log:
        process = subprocess.Popen(command, start_new_session=True, stdin=subprocess.PIPE, stdout=log, stderr=log)
        assert process.stdin is not None
        process.stdin.write(json.dumps(startup).encode())
        process.stdin.close()
    deadline = time.time() + 90
    while time.time() < deadline:
        if process.poll() is not None:
            return {"ok": False, "error": f"daemon exited during startup; see {paths['log']}"}
        reply = request(session, {"op": "status"}, timeout=5)
        if reply.get("ok"):
            return reply
        time.sleep(0.5)
    return {"ok": False, "error": f"daemon did not become ready; see {paths['log']}"}


def config_command(argv: list[str], options: dict) -> dict:
    parser = argparse.ArgumentParser(prog="gxui config", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    show = commands.add_parser("show")
    show.add_argument("--resolved", action="store_true")
    show.add_argument("--sources", action="store_true")
    set_parser = commands.add_parser("set")
    set_parser.add_argument("key")
    set_parser.add_argument("value", nargs="?")
    unset = commands.add_parser("unset")
    unset.add_argument("key")
    profile = commands.add_parser("profile").add_subparsers(dest="profile_command", required=True)
    add = profile.add_parser("add")
    add.add_argument("name")
    add.add_argument("--url", required=True)
    profile.add_parser("list")
    args = parser.parse_args(argv)
    config = ConfigFile.load(options.get("config"), missing_ok=args.command in ("init", "set", "profile"))
    if args.command == "init":
        if config.path.exists():
            raise ConfigError(f"config already exists: {config.path}")
        config.write({"version": 1, "defaults": {"headless": True}, "profiles": {}})
    elif args.command == "show":
        return {
            "ok": True,
            "result": (
                resolve(options).display(args.sources) if args.resolved or args.sources else redacted(config.data)
            ),
        }
    elif args.command in ("set", "unset"):
        if args.command == "unset":
            config.unset(args.key, options.get("profile"))
        else:
            if args.value is None:
                if args.key.split(".")[-1] != "password":
                    raise ConfigError("config set requires a value (auth.password prompts when omitted)")
                value = getpass.getpass("Password: ")
            else:
                # Strings stay strings for auth/usernames/paths; YAML scalars handle numbers and booleans.
                import yaml

                try:
                    value = (
                        args.value
                        if (args.key.startswith("auth.") or ".auth." in args.key) and not args.key.endswith(".keyring")
                        else yaml.safe_load(args.value)
                    )
                except yaml.YAMLError:
                    raise ConfigError("value must be a YAML scalar or mapping") from None
            config.set(args.key, value, options.get("profile"))
    elif args.profile_command == "list":
        return {"ok": True, "result": list(config.data.get("profiles", {}))}
    else:
        if args.name in config.data.get("profiles", {}):
            raise ConfigError(f"profile {args.name!r} already exists")
        data = {**config.data, "profiles": {**config.data.get("profiles", {}), args.name: {"url": args.url}}}
        config.write(data)
    return {"ok": True, "result": f"updated {config.path}"}


def login_command(session: str, argv: list[str], options: dict, timeout: float) -> dict:
    parser = argparse.ArgumentParser(prog="gxui login", allow_abbrev=False)
    parser.add_argument("email", nargs="?")
    passwords = parser.add_mutually_exclusive_group()
    passwords.add_argument("--password")
    passwords.add_argument("--password-stdin", action="store_true")
    parser.add_argument("--interactive", action="store_true", help="complete SSO/2FA in a headed browser; save state")
    parser.add_argument("--save", action="store_true", help="save state and select it for this profile")
    parser.add_argument("--timeout", type=float, default=300, help="interactive login deadline in seconds")
    args = parser.parse_args(argv)
    status = request(session, {"op": "status"}, timeout=5)
    if not status.get("ok"):
        return status
    binding = status.get("binding", {})
    # An unqualified login follows the running session's captured settings. Explicit selectors must match.
    if any(
        options.get(key) is not None or os.environ.get(env)
        for key, env in (("profile", "GXUI_PROFILE"), ("url", "GXUI_GALAXY_URL"), ("config", "GXUI_CONFIG"))
    ):
        check_binding(resolve(options), status)
    if args.interactive and (not args.timeout > 0 or not args.timeout < float("inf")):
        raise ConfigError("interactive timeout must be positive and finite")
    email, password = args.email or os.environ.get("GXUI_USERNAME"), args.password or os.environ.get("GXUI_PASSWORD")
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise ConfigError("no password received on stdin")
    if not args.interactive:
        info = request(session, {"op": "auth-info", "email": email, "password": password}, timeout=timeout)
        if not info.get("ok"):
            return info
        auth = info["result"]
        if not auth.get("logged_in"):
            if not email and not auth.get("username"):
                if not sys.stdin.isatty():
                    raise ConfigError(
                        "no username: configure auth.username or pass EMAIL; interactive login is also available"
                    )
                email = input("Username or email: ").strip()
            if not password and not auth.get("password_available"):
                if not sys.stdin.isatty():
                    raise ConfigError(
                        "no password: configure auth.password_env, set GXUI_PASSWORD, or use --password-stdin"
                    )
                password = getpass.getpass("Password: ")
            if email == "" or password == "":
                raise ConfigError("username and password cannot be empty")
    if args.interactive:
        print("Complete sign-in in the browser; waiting for Galaxy to confirm login.", file=sys.stderr)
    save = args.save or args.interactive
    state_home = Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser()
    state_path = str(state_home / "gxui" / f"{session}-auth.json") if save else None
    reply = request(
        session,
        {
            "op": "login",
            "email": email,
            "password": password,
            "interactive": args.interactive,
            "timeout": args.timeout,
            "storage_state": state_path,
        },
        timeout=max(timeout, args.timeout + 10) if args.interactive else timeout,
    )
    if reply.get("ok") and save:
        result = reply["result"]
        if binding.get("profile"):
            config = ConfigFile.load(binding.get("config"))
            profile = config.data.get("profiles", {}).get(binding["profile"])
            if profile is None or server_url(profile["url"]) != server_url(binding["url"]):
                raise ConfigError(f"login state saved to {state_path}; profile changed, so config was not updated")
            config.set("auth", {"username": result["email"], "storage_state": state_path}, binding["profile"])
        reply["result"] = f"logged in as {result['email']}; saved state to {state_path}"
    return reply


def emit(reply: dict) -> int:
    if reply.get("ok"):
        result = reply.get("result")
        if result not in (None, ""):
            print(result if isinstance(result, str) else json.dumps(result, indent=1))
        return 0
    print(f"error: {reply.get('error')}", file=sys.stderr)
    for key in ("url", "screenshot", "snapshot", "hint"):
        if reply.get(key):
            print(f"  {key}: {reply[key]}", file=sys.stderr)
    return 3 if reply.get("timeout") else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = settings_parser("gxui")
    parser.description = __doc__
    parser.epilog = "Settings: CLI > GXUI_* environment > profile > defaults > builtins. Use gxui config --help."
    # Parse only leading settings: verb flags belong to the verb, even when their names overlap.
    split = 0
    while split < len(argv) and argv[split].startswith("-"):
        flag = argv[split].split("=", 1)[0]
        if flag in ("--headed", "--headless", "-h", "--help") or "=" in argv[split]:
            split += 1
        else:
            split += 2
    try:
        options = {k: v for k, v in vars(parser.parse_args(argv[:split])).items() if v is not None}
        rest = argv[split:]
        command = rest[0] if rest else "status"
        if command == "config":
            return emit(config_command(rest[1:], options))
        if command == "start":
            options.update(
                {k: v for k, v in vars(settings_parser("gxui start").parse_args(rest[1:])).items() if v is not None}
            )
        settings = resolve(options)
        session, timeout = settings.values["session"], settings.values["client_timeout"]
        if command == "start":
            return emit(start(session, [], options))
        if command == "login":
            return emit(login_command(session, rest[1:], options, timeout))
        if command in ("status", "stop", "last"):
            return emit(request(session, {"op": command}, timeout=timeout))
        if any(
            options.get(key) is not None or os.environ.get(env)
            for key, env in (("profile", "GXUI_PROFILE"), ("url", "GXUI_GALAXY_URL"), ("config", "GXUI_CONFIG"))
        ):
            status = request(session, {"op": "status"}, timeout=5)
            if not status.get("ok"):
                return emit(status)
            check_binding(settings, status)
        return emit(request(session, {"op": "verb", "argv": rest}, timeout=timeout))
    except (ConfigError, OSError, EOFError) as e:
        return emit({"ok": False, "error": str(e)})
    except KeyboardInterrupt:
        return emit({"ok": False, "error": "interrupted; the daemon may still be running (gxui last)"})


if __name__ == "__main__":
    sys.exit(main())
