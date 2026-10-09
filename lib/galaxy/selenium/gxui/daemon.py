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
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError

from .config import (
    ConfigError,
    ConfigFile,
    private_json,
    server_url,
    Settings,
)
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
        self.left_unsaved = False
        self.stopping = False
        startup = args.settings
        self.settings = Settings(
            ConfigFile(Path(startup["config"]), {}), startup["profile"], startup["values"], startup["auth"], {}
        )
        self.secrets: set[str] = set()
        self.resume_state = None
        self.ctx = self.launch()
        register_method_verbs(GxuiContext)

    # -- browser ---------------------------------------------------------

    def launch(self) -> GxuiContext:
        ctx = GxuiContext(
            {
                "storage_state": self.resume_state or self.settings.auth.get("storage_state"),
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
        ctx.page.goto(self.args.url)
        self.attach_cli()
        return ctx

    def on_dialog(self, dialog) -> None:
        if dialog.type == "beforeunload":
            # Leaving a page with unsaved work (the workflow editor). Held open, it would block the
            # navigating verb forever - `gxui dialog` queues behind that verb - so stay and say why.
            self.left_unsaved = True
            dialog.dismiss()
            return
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

    def reattach_cli_if_gone(self) -> bool:
        """A gap precedes playwright-cli use: make sure its session is still attached (runs have lost it)."""
        if not self.args.playwright_cli:
            return False
        command = shlex.split(self.args.playwright_cli) + [f"-s={self.args.session}", "eval", "1"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        except subprocess.TimeoutExpired:
            return False
        if "is not open" not in result.stdout + result.stderr:
            return False
        print(f"playwright-cli session {self.args.session} was gone; attaching again", flush=True)
        self.attach_cli()
        return True

    # -- requests ----------------------------------------------------------

    def status(self) -> str:
        parts = [
            f"session {self.args.session}",
            f"galaxy {self.args.url}",
            f"profile {self.settings.profile}",
            f"browser {'headed' if self.args.headed else 'headless'}",
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
            return {"ok": True, "result": self.status(), "binding": self.binding()}
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
        if name == "gap" and self.reattach_cli_if_gone():
            return {"ok": True, "result": "logged; the playwright-cli session had gone, so gxui attached it again"}
        return {"ok": True, "result": "logged"}

    def binding(self) -> dict:
        return {
            "url": self.args.url,
            "profile": self.settings.profile,
            "config": str(self.settings.config.path),
            "headless": not self.args.headed,
        }

    def credentials(self, req: dict) -> tuple[str, str]:
        configured_email = self.settings.auth.get("username", "")
        email = req.get("email") or configured_email
        password = req.get("password")
        # Changing the account also clears the configured password.
        if password is None and email == configured_email:
            _, password = self.settings.credentials()
        if password:
            self.secrets.add(password)
        return email, password or ""

    def auth_info(self, req: dict) -> dict:
        try:
            if self.ctx.is_logged_in():
                return {"ok": True, "result": {"logged_in": True}}
            email, password = self.credentials(req)
            return {"ok": True, "result": {"username": email, "password_available": bool(password)}}
        except ConfigError as e:
            return {"ok": False, "error": str(e)}

    def run_login(self, req: dict) -> dict:
        started = time.time()
        self.busy, self.busy_since = "login", time.strftime("%H:%M:%S")
        try:
            if req.get("interactive"):
                if not self.ctx.is_logged_in():
                    if not self.args.headed:
                        self.resume_state = self.ctx.page.context.storage_state()
                        self.args.headed = True
                        try:
                            self.relaunch()
                        except Exception:
                            # No display (an ssh session): keep a working headless browser.
                            self.args.headed = False
                            self.relaunch()
                            raise ConfigError(
                                "could not open a headed browser (no display?); the session is headless again"
                            ) from None
                    self.ctx.home()
                    deadline = time.monotonic() + req["timeout"]
                    while not self.ctx.is_logged_in():
                        if time.monotonic() >= deadline:
                            raise ConfigError("interactive login timed out; complete sign-in and retry login --save")
                        self.ctx.page.wait_for_timeout(250)
            elif not self.ctx.is_logged_in():
                email, password = self.credentials(req)
                if not email or not password:
                    raise ConfigError("login requires a username and password")
                self.ctx.home()
                self.ctx.submit_login(email, password)
            user = self.ctx.get_logged_in_user()
            if not user or not user.get("email"):
                raise ConfigError("Galaxy has not confirmed a logged-in user; state was not saved")
            expected = req.get("email") or self.settings.auth.get("username")
            if expected and expected.casefold() not in (user["email"].casefold(), user.get("username", "").casefold()):
                raise ConfigError(f"already logged in as {user['email']}; logout before switching accounts")
            email = user["email"]
            if path := req.get("storage_state"):
                state = self.ctx.page.context.storage_state()
                state["_gxui"] = {"url": server_url(self.args.url)}
                private_json(Path(path), state)
                self.resume_state = state
                result: dict | str = {"email": email, "storage_state": path}
            else:
                result = f"logged in as {email}"
            reply = {"ok": True, "result": result}
        except Exception as e:
            # Authentication failures contain no browser call trace or screenshot artifacts.
            reply = {"ok": False, "error": self.redact(f"{type(e).__name__}: {e}")}
        finally:
            self.busy = None
        self.transcript.write(
            {
                "layer": "verb",
                "verb": "login",
                "args": [],
                "method": "submit_login",
                "ok": reply["ok"],
                "duration_ms": int((time.time() - started) * 1000),
                "result" if reply["ok"] else "error": reply.get("result", reply.get("error")),
            }
        )
        return reply

    def redact(self, text: str) -> str:
        for secret in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(secret, "<redacted>")
        return text

    def run_verb(self, argv: list[str]) -> dict:
        name, rest = argv[0], argv[1:]
        if name == "dialog":
            return self.dialog(rest)
        verb = REGISTRY.get(name)
        if verb is None:
            return {"ok": False, "error": f"unknown verb {name!r}; see `gxui help`"}
        started = time.time()
        sensitive = name in ("login", "register") or (
            name == "call" and rest and rest[0] in ("submit_login", "fill_login_and_submit", "register")
        )
        safe_rest = ["<redacted>"] if sensitive else rest
        if sensitive:
            for index, value in enumerate(rest):
                if value.startswith("--password="):
                    self.secrets.add(value.split("=", 1)[1])
                elif value == "--password" and index + 1 < len(rest):
                    self.secrets.add(rest[index + 1])
            if name == "call" and len(rest) > 2:
                self.secrets.add(rest[2])
        entry: dict[str, Any] = {"layer": verb.layer, "verb": name, "args": safe_rest, "method": verb.method}
        try:
            args, kwargs = verb.parse(rest)
            self.busy, self.busy_since = " ".join([name, *safe_rest]), time.strftime("%H:%M:%S")
            result = verb.func(self.ctx, *args, **kwargs)
            reply = {"ok": True, "result": _summarize(result)}
        except UsageError as e:
            reply = {"ok": False, "error": self.redact(str(e))}
        except PlaywrightError as e:
            if BROWSER_GONE in str(e) or type(e).__name__ == "TargetClosedError":
                self.relaunch()
                restored = self.resume_state or self.settings.auth.get("storage_state")
                lost = "page state is lost; saved login restored" if restored else "page state and login are lost"
                reply = {"ok": False, "error": f"browser died and was relaunched; {lost}"}
            else:
                reply = self.failure(name, e)
        except Exception as e:
            reply = self.failure(name, e)
        finally:
            self.busy = None
        if self.dialogs:
            reply["hint"] = f"a dialog is open ({self.dialogs[-1].message!r}): `gxui dialog accept|dismiss`"
        if self.left_unsaved:
            self.left_unsaved = False
            reply["hint"] = (
                "this page has unsaved changes, so gxui stayed on it: save them (`gxui workflow-save`) first"
            )
        entry.update(ok=reply["ok"], duration_ms=int((time.time() - started) * 1000))
        entry["result" if reply["ok"] else "error"] = reply.get("result") or reply.get("error")
        for key in ("screenshot", "url"):
            if key in reply:
                entry[key] = reply[key]
        self.transcript.write(entry)
        return reply

    def failure(self, name: str, e: Exception) -> dict:
        reply = {"ok": False, "error": self.redact(f"{type(e).__name__}: {_error_text(e)}")}
        try:
            reply["url"] = self.ctx.page.url
            reply["screenshot"] = self.ctx.screenshot(f"error-{time.strftime('%H%M%S')}-{name}")
        except Exception:
            pass
        reply["hint"] = "inspect with `gxui snapshot`, or `gxui gap REASON` then playwright-cli"
        modal = self.open_modal()
        if modal:
            reply["hint"] = f"a modal is open and may block the page: {modal!r}; close it or retry"
        print(self.redact(traceback.format_exc()), flush=True)
        return reply

    def open_modal(self) -> str:
        """Text of a visible Galaxy modal (an error such as a rate-limited load blocks every click)."""
        try:
            modals = self.ctx.page.locator("dialog[open], .modal-dialog:visible")
            return " ".join(modals.first.inner_text(timeout=1000).split())[:300] if modals.count() else ""
        except Exception:
            return ""

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
                    if req.get("op") == "auth-info":
                        reply = self.auth_info(req)
                    elif req.get("op") == "login":
                        reply = self.run_login(req)
                    else:
                        reply = self.run_verb(req["argv"])
                except Exception as e:  # a bug in gxui must not take the browser down with it
                    print(self.redact(traceback.format_exc()), flush=True)
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


def _error_text(e: Exception) -> str:
    """A verb's own errors whole (invocation-wait lists every output); a framework or Playwright
    error's first line, without its call log."""
    text = str(e)
    if type(e).__module__ == "builtins":
        return text[:4000]
    return text.splitlines()[0] if text else ""


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
    parser.add_argument("--playwright-cli")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    # Startup settings (including credentials) arrive on stdin, never as process arguments.
    args.settings = json.load(sys.stdin)
    Daemon(args).serve()


if __name__ == "__main__":
    main()
