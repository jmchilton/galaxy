"""gxui daemon: owns one browser and one GxuiContext per session, serves verbs over a Unix socket.

Playwright's sync API is bound to the thread that started it, so verbs run one at a time on the main
thread. An accept thread answers bookkeeping requests (status, last, note, gap, help) at once, so they
never queue behind a long verb.
"""

import argparse
import json
import os
import queue
import shlex
import socket
import subprocess
import threading
import time
import traceback
from typing import Any

import yaml
from playwright.sync_api import Error as PlaywrightError

from .context import GxuiContext
from .verbs import (
    help_text,
    register_method_verbs,
    REGISTRY,
    UsageError,
)

INLINE_OPS = {"status", "last", "stop"}
INLINE_VERBS = {"help", "note", "gap"}
BROWSER_GONE = "Target page, context or browser has been closed"


class Transcript:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        self.last_call: dict | None = None  # latest verb/component/call result, for `gxui last`
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def write(self, entry: dict) -> dict:
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **entry}
        with self.lock, open(self.path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
            if entry.get("layer") not in ("note", "external"):
                self.last_call = entry
        return entry


class Daemon:
    def __init__(self, args):
        self.args = args
        self.port = args.port or _free_port()
        self.cdp = f"http://127.0.0.1:{self.port}"
        self.transcript = Transcript(os.path.join(args.artifacts, "transcript.jsonl"))
        self.work: queue.Queue = queue.Queue()
        self.last_activity = time.time()
        self.busy: str | None = None
        self.busy_since = ""
        self.restarts = 0
        self.dialogs: list = []
        self.stopping = False
        self.config = _load_config(args.config)
        self.ctx = self.launch()
        register_method_verbs(GxuiContext)

    # -- browser ---------------------------------------------------------

    def launch(self) -> GxuiContext:
        ctx = GxuiContext(
            {
                **self.config,
                "local_galaxy_url": self.args.url,
                "timeout_multiplier": self.args.timeout_multiplier,
                "driver": {
                    "backend_type": "playwright",
                    "headless": not self.args.headed,
                    "remote_debugging_port": self.port,
                },
            },
            self.args.artifacts,
        )
        # A passive listener keeps dialogs open for `gxui dialog` or playwright-cli instead of
        # Playwright auto-dismissing them; verbs that expect one still use accept_alert.
        ctx.page.on("dialog", self.on_dialog)
        if self.args.storage_state:
            with open(self.args.storage_state) as f:
                ctx.page.context.add_cookies(json.load(f).get("cookies", []))
        ctx.page.goto(self.args.url)
        self.attach_cli()
        return ctx

    def on_dialog(self, dialog) -> None:
        self.dialogs.append(dialog)

    def relaunch(self) -> None:
        try:
            self.ctx.configured_driver.quit()
        except Exception:
            pass
        self.dialogs.clear()
        self.ctx = self.launch()
        self.restarts += 1

    def attach_cli(self) -> None:
        if not self.args.playwright_cli:
            return
        command = shlex.split(self.args.playwright_cli) + [f"-s={self.args.session}", "attach", f"--cdp={self.cdp}"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            print(f"playwright-cli attach failed: {result.stderr or result.stdout}", flush=True)

    # -- requests ----------------------------------------------------------

    def status(self) -> str:
        parts = [
            f"session {self.args.session}",
            f"galaxy {self.args.url}",
            f"cdp {self.cdp}",
            f"pid {os.getpid()}",
            f"transcript {self.transcript.path}",
        ]
        if self.busy:
            parts.append(f"busy: {self.busy}")
        if self.restarts:
            parts.append(f"browser relaunches {self.restarts}")
        if self.dialogs:
            parts.append(f"open dialog: {self.dialogs[-1].message!r}")
        return "\n".join(parts)

    def inline(self, req: dict) -> dict:
        op = req.get("op")
        if op == "status":
            return {"ok": True, "result": self.status()}
        if op == "last":
            if self.busy:
                return {"ok": True, "result": f"still running: {self.busy} (since {self.busy_since})"}
            return {"ok": True, "result": self.transcript.last_call or "no calls yet"}
        if op == "stop":
            self.stopping = True
            self.work.put(None)
            return {"ok": True, "result": "stopping"}
        argv = req["argv"]
        name, rest = argv[0], argv[1:]
        if name == "help":
            return {"ok": True, "result": help_text(rest[0] if rest else "")}
        text = " ".join(rest)
        if not text:
            return {"ok": False, "error": f"usage: gxui {name} TEXT"}
        layer = "external" if name == "gap" else "note"
        self.transcript.write({"layer": layer, "verb": name, "text": text})
        return {"ok": True, "result": "logged"}

    def run_verb(self, argv: list[str]) -> dict:
        name, rest = argv[0], argv[1:]
        if name == "dialog":
            return self.dialog(rest)
        verb = REGISTRY.get(name)
        if verb is None:
            return {"ok": False, "error": f"unknown verb {name!r}; see `gxui help`"}
        started = time.time()
        entry: dict[str, Any] = {"layer": verb.layer, "verb": name, "args": rest, "method": verb.method}
        try:
            args, kwargs = verb.parse(rest)
            self.busy, self.busy_since = " ".join(argv), time.strftime("%H:%M:%S")
            result = verb.func(self.ctx, *args, **kwargs)
            reply = {"ok": True, "result": _summarize(result)}
        except UsageError as e:
            reply = {"ok": False, "error": str(e)}
        except PlaywrightError as e:
            if BROWSER_GONE in str(e) or type(e).__name__ == "TargetClosedError":
                self.relaunch()
                reply = {"ok": False, "error": "browser died and was relaunched; page state and login are lost"}
            else:
                reply = self.failure(name, e)
        except Exception as e:
            reply = self.failure(name, e)
        finally:
            self.busy = None
        if self.dialogs:
            reply["hint"] = f"a dialog is open ({self.dialogs[-1].message!r}): `gxui dialog accept|dismiss`"
        entry.update(ok=reply["ok"], duration_ms=int((time.time() - started) * 1000))
        entry["result" if reply["ok"] else "error"] = reply.get("result") or reply.get("error")
        for key in ("screenshot", "url"):
            if key in reply:
                entry[key] = reply[key]
        self.transcript.write(entry)
        return reply

    def failure(self, name: str, e: Exception) -> dict:
        reply = {"ok": False, "error": f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"}
        try:
            reply["url"] = self.ctx.page.url
            reply["screenshot"] = self.ctx.screenshot(f"error-{time.strftime('%H%M%S')}-{name}")
        except Exception:
            pass
        reply["hint"] = "inspect with `gxui snapshot`, or `gxui gap REASON` then playwright-cli"
        print(traceback.format_exc(), flush=True)
        return reply

    def dialog(self, rest: list[str]) -> dict:
        if not self.dialogs:
            return {"ok": False, "error": "no open dialog"}
        dialog = self.dialogs.pop()
        if rest[:1] == ["accept"]:
            dialog.accept(*rest[1:2])
        elif rest[:1] == ["dismiss"]:
            dialog.dismiss()
        else:
            self.dialogs.append(dialog)
            return {"ok": False, "error": "usage: gxui dialog accept [TEXT] | dismiss"}
        self.transcript.write({"layer": "verb", "verb": "dialog", "args": rest, "ok": True})
        return {"ok": True, "result": f"{rest[0]}ed {dialog.type} {dialog.message!r}"}

    # -- serving -------------------------------------------------------------

    def accept_loop(self, server: socket.socket) -> None:
        while not self.stopping:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            try:
                req = json.loads(conn.makefile().readline())
            except Exception:
                conn.close()
                continue
            self.last_activity = time.time()
            argv = req.get("argv") or [""]
            if req.get("op") in INLINE_OPS or argv[0] in INLINE_VERBS:
                _reply(conn, self.inline(req))
            else:
                self.work.put((conn, req))

    def serve(self) -> None:
        sock_path = self.args.sock
        if os.path.exists(sock_path):
            os.unlink(sock_path)
        server = socket.socket(socket.AF_UNIX)
        server.bind(sock_path)
        server.listen(16)
        with open(self.args.meta, "w") as f:
            json.dump({"pid": os.getpid(), "cdp": self.cdp, "url": self.args.url, "artifacts": self.args.artifacts}, f)
        threading.Thread(target=self.accept_loop, args=(server,), daemon=True).start()
        print(f"serving {self.args.session} pid={os.getpid()} cdp={self.cdp}", flush=True)
        try:
            while True:
                try:
                    item = self.work.get(timeout=1)
                except queue.Empty:
                    idle = self.args.idle_timeout
                    if idle and time.time() - self.last_activity > idle:
                        print("idle timeout", flush=True)
                        break
                    continue
                if item is None:
                    break
                conn, req = item
                try:
                    reply = self.run_verb(req["argv"])
                except Exception as e:  # a bug in gxui must not take the browser down with it
                    print(traceback.format_exc(), flush=True)
                    reply = {"ok": False, "error": f"gxui internal error: {type(e).__name__}: {e}"}
                _reply(conn, reply)
                self.last_activity = time.time()
        finally:
            self.stopping = True
            server.close()
            for path in (sock_path, self.args.meta):
                if os.path.exists(path):
                    os.unlink(path)
            try:
                self.ctx.configured_driver.quit()
            except Exception:
                pass


def _summarize(result) -> str | int | float | list | dict:
    """Verbs print short text; framework methods sometimes return components or elements."""
    if result is None:
        return "ok"
    if isinstance(result, (str, int, float)):
        return result
    try:
        json.dumps(result)
        return result
    except TypeError:
        return "ok"


def _reply(conn: socket.socket, reply: dict) -> None:
    try:
        with conn:
            conn.sendall(json.dumps(reply, default=str).encode())
    except (BrokenPipeError, ConnectionResetError, OSError):
        print(f"client gone before reply: {str(reply)[:200]}", flush=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _load_config(path: str | None) -> dict:
    if not path:
        return {}
    with open(path) as f:
        config = yaml.safe_load(f) or {}
    return {k: config[k] for k in ("login_email", "login_password") if k in config}


def main() -> None:
    parser = argparse.ArgumentParser(prog="gxui-daemon")
    parser.add_argument("--session", required=True)
    parser.add_argument("--sock", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--idle-timeout", type=float, default=3600)
    parser.add_argument("--timeout-multiplier", type=float, default=1)
    parser.add_argument("--config")
    parser.add_argument("--storage-state")
    parser.add_argument("--playwright-cli")
    parser.add_argument("--headed", action="store_true")
    Daemon(parser.parse_args()).serve()


if __name__ == "__main__":
    main()
