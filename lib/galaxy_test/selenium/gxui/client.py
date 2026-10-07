"""Thin gxui client. Stdlib only so each call starts fast; everything Galaxy lives in the daemon.

gxui [status]                 daemon, browser and Galaxy status for the session
gxui start [options]          start the session's daemon (idempotent), print its CDP URL
gxui stop | last              stop the daemon | print the latest transcript entry
gxui <verb> [args...]         run a verb; `gxui help` lists them
"""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time

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


def start(session: str, argv: list[str]) -> dict:
    parser = argparse.ArgumentParser(prog="gxui start")
    parser.add_argument("--url", default=os.environ.get("GXUI_GALAXY_URL", "http://localhost:8080"))
    parser.add_argument("--config", help="galaxy_selenium_context.yml-style file (login_email/login_password)")
    parser.add_argument("--storage-state", help="Playwright storage state JSON whose cookies are loaded")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--port", type=int, default=0, help="CDP port (default: a free one)")
    parser.add_argument("--idle-timeout", type=float, default=3600, help="seconds; 0 disables")
    parser.add_argument("--timeout-multiplier", type=float, default=1)
    parser.add_argument("--artifacts", help="transcript/screenshot dir (default: $GXUI_HOME/<session>)")
    parser.add_argument("--playwright-cli", default=os.environ.get("GXUI_PLAYWRIGHT_CLI"), help="command to attach")
    args = parser.parse_args(argv)

    status = request(session, {"op": "status"}, timeout=5)
    if status.get("ok"):
        status["result"] = "already running; " + status["result"]
        return status

    paths = session_paths(session)
    os.makedirs(gxui_home(), exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "galaxy_test.selenium.gxui.daemon",
        "--session",
        session,
        "--sock",
        paths["sock"],
        "--meta",
        paths["meta"],
        "--artifacts",
        args.artifacts or paths["artifacts"],
        "--url",
        args.url,
        "--port",
        str(args.port),
        "--idle-timeout",
        str(args.idle_timeout),
        "--timeout-multiplier",
        str(args.timeout_multiplier),
    ]
    for flag, value in (("--config", args.config), ("--storage-state", args.storage_state)):
        if value:
            command += [flag, os.path.abspath(os.path.expanduser(value))]
    if args.playwright_cli:
        command += ["--playwright-cli", args.playwright_cli]
    if args.headed:
        command.append("--headed")
    with open(paths["log"], "a") as log:
        subprocess.Popen(
            command,
            start_new_session=True,  # outlive the agent shell that started us
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
        )
    deadline = time.time() + 90
    while time.time() < deadline:
        reply = request(session, {"op": "status"}, timeout=5)
        if reply.get("ok"):
            return reply
        time.sleep(0.5)
    return {"ok": False, "error": f"daemon did not become ready; see {paths['log']}"}


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
    session = os.environ.get("GXUI_SESSION", "default")
    if argv[:1] == ["--session"] and len(argv) > 1:
        session, argv = argv[1], argv[2:]
    elif argv and argv[0].startswith("--session="):
        session, argv = argv[0].split("=", 1)[1], argv[1:]
    timeout = float(os.environ.get("GXUI_CLIENT_TIMEOUT", DEFAULT_CLIENT_TIMEOUT))

    command = argv[0] if argv else "status"
    if command in ("-h", "--help"):
        print(__doc__)
        return 0
    if command == "start":
        return emit(start(session, argv[1:]))
    if command in ("status", "stop", "last"):
        return emit(request(session, {"op": command}, timeout=timeout))
    return emit(request(session, {"op": "verb", "argv": argv}, timeout=timeout))


if __name__ == "__main__":
    sys.exit(main())
