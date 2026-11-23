"""What the tool author made the tool able to do, beyond turning inputs into outputs.

These findings are not vulnerabilities a user can exploit. They answer the question an admin
asks before installing a tool from the Tool Shed: what does this tool do on my server?

Three places are inspected:

* Python that runs **inside the Galaxy server process**: Cheetah directives and expressions
  of ``<command>`` and ``<configfile>``, output ``<filter>`` expressions, ``<code>`` files,
  ``dynamic_options``. A job runs with the job's permissions; this code runs with Galaxy's.
* The literal text of the command line: programs it starts and paths and URLs it names.
* Declarations in the tool XML: API key injection, containers, tool type.
"""

from __future__ import annotations

import ast
import re
import warnings
from functools import partial
from typing import (
    Any,
    Callable,
)

from galaxy.tool_util.parser.interface import ToolSource
from . import shell
from .charsets import (
    CRITICAL,
    HIGH,
    INFO,
    LOW,
    MEDIUM,
    not_plain,
)
from .model import Model
from .report import (
    CAPABILITY,
    Finding,
    Report,
    SANITIZE_OFF,
)
from .template import (
    CompiledTemplate,
    name_lookup,
    NAMESPACE_LOOKUPS,
)

SERVER = "runs in the Galaxy server process"

# Modules a template may import without a finding: they compute, they do not act.
_HARMLESS_MODULES = frozenset(
    (
        "re json math string itertools collections shlex functools operator textwrap datetime decimal fractions"
        " statistics random copy numbers os os.path posixpath time locale unicodedata"
    ).split()
)
_EXEC_MODULES = frozenset("subprocess commands pty popen2 multiprocessing ctypes cffi importlib imp runpy code".split())
_NETWORK_MODULES = frozenset(
    "socket urllib urllib2 urllib3 requests http httplib ftplib smtplib telnetlib xmlrpc paramiko ssl".split()
)
_STATE_MODULES = frozenset(
    "pickle cPickle marshal shelve shutil tempfile glob pathlib sys builtins __builtin__ gc inspect".split()
)

_OS_EXEC = re.compile(r"^(system|popen\w*|exec\w*|spawn\w*|fork\w*|kill\w*|posix_spawn\w*|startfile)$")
_OS_WRITE = re.compile(
    r"^(remove|unlink|rename|renames|replace|rmdir|removedirs|chmod|chown|lchown|symlink|link|truncate|write"
    r"|open|mkfifo|mknod|utime|makedirs|mkdir|chdir|chroot|setuid|setgid|umask|putenv|unsetenv)$"
)
_OS_ENV = frozenset(("environ", "environb", "getenv", "getenvb"))
_OS_HARMLESS = frozenset(("path", "sep", "linesep", "pathsep", "curdir", "pardir", "extsep", "devnull", "name"))

_EXEC_BUILTINS = frozenset(("eval", "exec", "execfile", "compile", "__import__"))
_REFLECTION_BUILTINS = frozenset(
    ("getattr", "setattr", "delattr", "globals", "locals", "vars", "builtin", "builtins", "__builtins__", "dir")
)
_FILE_BUILTINS = frozenset(("open",))
_GENERATED_SELF = frozenset(("_CHEETAH__globalSetVars", "_CHEETAH__isBuffering", "getVar", "varExists", "hasVar"))
# Modules that act when passed around as a value (`#set $o = $os`): the call on them cannot be followed.
_MODULE_VALUES = frozenset(("os", "sys", "builtins", "__builtins__", "builtin"))
_GENERATED_NAMES = frozenset(("trans", "SL", "KWS", "write", "_filter", "_dummyTrans", "Template", "types"))
_REFLECTION_ATTRS = re.compile(
    r"^(__(class|globals|dict|subclasses|mro|bases|base|init|code|builtins|reduce|reduce_ex|getattribute|import"
    r"|loader|spec|module|closure|func|self|wrapped)__|func_globals|gi_frame|f_globals|f_locals|f_back|f_builtins)$"
)
_MODEL_ATTRS = frozenset("unsanitized sa_session api_keys object_store galaxy_session security creating_job".split())
# Calls whose result can hold characters that the value they read did not: a plain value can come
# out of them unsafe.
_REWRITE_CALLS = frozenset(
    "chr unichr fromhex unhexlify translate unquote unquote_plus unquote_to_bytes b64decode b32decode b16decode"
    " b85decode a85decode urlsafe_b64decode standard_b64decode decodebytes a2b_base64 a2b_hex a2b_qp".split()
)
_VFN = frozenset(("VFN",))
# `getattr(x, "name")` has the shape of a NameMapper call: the name is its second argument.
_GETATTR = frozenset(("getattr",))
# Codecs whose decode() keeps the characters of the text that encode() was given.
_KEEPING_CODECS = frozenset(("utf-8", "utf8", "utf_8", "ascii"))


class PythonAudit:
    """Flag Python in a template (or an expression) that acts on the server instead of computing text."""

    def __init__(self, report: Report, location: str, model: Model | None = None, assigned: set[str] | None = None):
        self.report = report
        self.location = location
        # The names the template mentions: which attributes, metadata and account values it reads.
        self.names: set[str] = set()
        # Keys the template stores into dicts, and the first names of what it looks up in the namespace.
        self.stored_keys: set[str] = set()
        self.namespace_reads: set[str] = set()
        self.model = model
        self.assigned = assigned or set()
        # Local name -> dotted origin, from `import os as o` and `from os import system`.
        self.aliases: dict[str, str] = {}
        # Names a `#set` or a loop variable cannot hide: an assignment the template never runs
        # (`#if False`) leaves the builtin in place when the name is read as `$name`.
        self.never_shadowed = (
            _EXEC_BUILTINS | _REFLECTION_BUILTINS | _FILE_BUILTINS | _EXEC_MODULES | _NETWORK_MODULES | _MODULE_VALUES
        ) - {"dir", "vars", "code", "http", "imp"}

    def add(self, rule: str, severity: str, message: str, expr: str, line: int | None = None) -> None:
        self.report.add(
            Finding(
                rule=rule,
                kind=CAPABILITY,
                severity=severity,
                message=f"{message} ({SERVER}).",
                location=self.location,
                line=line,
                expr=expr,
            )
        )

    def template(self, template: CompiledTemplate) -> None:
        for imported in template.imports:
            self.import_(imported, template.template_line(imported))
        self.assigned.update(template.helpers)
        for method in [template.main, *template.helpers.values()]:
            self.assigned.update(method.args)
            for stmt in method.body:
                for node in ast.walk(stmt):
                    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                        # Loop and #set variables shadow builtins of the same name ($file, $input, $dir).
                        self.assigned.add(node.id)
                    elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
                        key = node.slice
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            self.stored_keys.add(key.value)
                    elif lookup := name_lookup(node, NAMESPACE_LOOKUPS):
                        self.namespace_reads.add(lookup[1].split(".")[0])
        for method in [template.main, *template.helpers.values()]:
            for stmt in method.body:
                self.walk(stmt, template)
            # Argument defaults and decorators run when the template class is created.
            for expression in method.at_definition:
                self.walk(expression, template)
        for stmt in template.attrs:
            self.walk(stmt, template)

    def expression(self, source: str) -> None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(source.strip(), mode="eval")
        except SyntaxError:
            return
        self.walk(tree, None)

    def import_(self, node: ast.stmt, line: int | None) -> None:
        modules = (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [getattr(node, "module", "") or ""]
        )
        text = ast.unparse(node)
        for alias in node.names if isinstance(node, (ast.Import, ast.ImportFrom)) else []:
            if isinstance(node, ast.ImportFrom):
                origin = f"{node.module or ''}.{alias.name}"
                self.aliases[alias.asname or alias.name] = origin
                # `from os import system` is a use of os.system.
                self.judge(origin.split("."), line)
            elif alias.asname:
                self.aliases[alias.asname] = alias.name
        for module in modules:
            root = module.split(".")[0]
            if module in _HARMLESS_MODULES or root in _HARMLESS_MODULES:
                continue
            if root in _EXEC_MODULES:
                self.add(
                    "template-exec", CRITICAL, f"Imports `{module}`, which can start processes or load code", text, line
                )
            elif root in _NETWORK_MODULES:
                self.add(
                    "template-network", HIGH, f"Imports `{module}`, which can open network connections", text, line
                )
            elif root in _STATE_MODULES:
                self.add(
                    "template-import", HIGH, f"Imports `{module}`, which can read or change server state", text, line
                )
            else:
                self.add("template-import", MEDIUM, f"Imports `{module}`", text, line)

    def walk(self, tree: ast.AST, template: CompiledTemplate | None) -> None:
        line: int | None = None
        seen: set[int] = set()
        for node in ast.walk(tree):
            self.note_names(node)
            if rewrite := self.rewrite(node):
                found = self.report.rewrites.setdefault(self.location, [])
                if rewrite not in found:
                    found.append(rewrite)
            if template is not None and isinstance(node, ast.stmt):
                line = template.template_line(node) or line
            if isinstance(node, ast.Store) or id(node) in seen:
                continue
            if isinstance(node, ast.Call) and self.is_get_var(node.func):
                name = node.args[0] if node.args else None
                if isinstance(name, ast.Constant) and isinstance(name.value, str):
                    if not self.is_template_name(name.value.split(".")[0]):
                        self.judge(name.value.split("."), line)
                else:
                    self.add(
                        "template-reflection",
                        MEDIUM,
                        "Looks up a variable by a computed name with `getVar`",
                        "getVar",
                        line,
                    )
            chain = self.chain(node, seen)
            if chain:
                self.judge(chain, line)
            elif isinstance(node, ast.Attribute) and _REFLECTION_ATTRS.match(node.attr):
                self.add(
                    "template-reflection", HIGH, f"Reaches Python internals through `.{node.attr}`", node.attr, line
                )

    def chain(self, node: ast.AST, seen: set[int]) -> list[str] | None:
        """A dotted reference rooted at a name: `os.path.join`, or the NameMapper form `$os.path.join`."""
        if lookup := name_lookup(node, NAMESPACE_LOOKUPS):
            parts = lookup[1].split(".")
            if parts[0] in self.aliases:
                return self.aliases[parts[0]].split(".") + parts[1:]
            if self.is_template_name(parts[0]):
                # A tool input or a template variable; only its attributes are of interest.
                return ["$"] + parts[1:]
            return parts
        if (lookup := name_lookup(node, _VFN)) and isinstance(node, ast.Call):
            # Cheetah splits `$os.system('id')` into VFN(VFFSL(SL, "os"), "system"): put it back together.
            base = self.chain(node.args[0], seen)
            if base is not None:
                seen.add(id(node.args[0]))
                return base + lookup[1].split(".")
            return ["$"] + lookup[1].split(".")
        attrs: list[str] = []
        current = node
        while isinstance(current, ast.Attribute):
            seen.add(id(current))
            attrs.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name) and isinstance(current.ctx, ast.Load):
            seen.add(id(current))
            if current.id in self.aliases:
                return self.aliases[current.id].split(".") + attrs[::-1]
            if current.id in self.assigned and current.id not in self.never_shadowed:
                return ["$"] + attrs[::-1] if attrs else None
            return [current.id] + attrs[::-1]
        if attrs and isinstance(node, ast.Attribute):
            return ["$"] + attrs[::-1]
        return None

    def rewrite(self, node: ast.AST) -> str | None:
        """The name of the rewrite a node is, when it can turn a plain value into one that is not."""
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str) and "%c" in node.left.value:
                return "%c"
            return None
        if not isinstance(node, ast.Call):
            return None
        chain = self.chain(node.func, set())
        if not chain:
            return None
        name = chain[-1]
        if name in _REWRITE_CALLS:
            return name
        if name in ("sub", "subn") and (chain[0] == "re" or chain[:1] == ["$"]):
            return f"re.{name}"
        if name == "decode":
            codec = node.args[0] if node.args else None
            keeps = codec is None or (isinstance(codec, ast.Constant) and str(codec.value).lower() in _KEEPING_CODECS)
            return None if keeps and chain[0] != "codecs" else "decode"
        if name == "replace":
            if chain == ["str", "replace"] or len(node.args) < 2:
                return ".replace"
            new = node.args[1]
            plain = (
                isinstance(new, ast.Constant)
                and isinstance(new.value, str)
                and not not_plain(new.value)
                and "-" not in new.value
                and not any(c.isspace() for c in new.value)
            )
            return None if plain else ".replace"
        return None

    def note_names(self, node: ast.AST) -> None:
        """Record the names a template mentions: which attributes, metadata and account values it can read."""
        names: list[str] = []
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif lookup := name_lookup(node):
            names.extend(lookup[1].split("."))
        elif lookup := name_lookup(node, _GETATTR):
            names.append(lookup[1])
        self.names.update(names)

    @staticmethod
    def is_get_var(func: ast.expr) -> bool:
        if isinstance(func, ast.Name):
            return func.id == "getVar"
        if isinstance(func, ast.Attribute):
            return func.attr == "getVar"
        lookup = name_lookup(func, NAMESPACE_LOOKUPS)
        return lookup is not None and lookup[1] in ("getVar", "self.getVar")

    def is_template_name(self, name: str) -> bool:
        if name in ("__app__", "__user__"):
            return False
        if name in self.aliases:
            return False
        if name in self.never_shadowed:
            # Only an input at the top level of the tool is always in the namespace.
            return self.model is not None and name in self.model.root.children
        if name in self.assigned:
            return True
        return self.model is not None and self.model.lookup(name) is not None

    def judge(self, chain: list[str], line: int | None) -> None:
        root, rest = chain[0], chain[1:]
        dotted = ".".join(chain).replace("$.", "$")
        first = rest[0] if rest else ""
        if root in _MODULE_VALUES and not rest:
            self.add(
                "template-reflection",
                HIGH,
                f"Uses the `{root}` module as a value: what is called on it cannot be followed",
                dotted,
                line,
            )
        elif root == "operator" and first in ("attrgetter", "methodcaller"):
            self.add("template-reflection", HIGH, f"Uses `{dotted}`: can reach any attribute by name", dotted, line)
        elif root == "os" and rest:
            if _OS_EXEC.match(first):
                self.add("template-exec", CRITICAL, f"Calls `{dotted}`: starts a process", dotted, line)
            elif first in _OS_ENV:
                self.add("template-env", HIGH, f"Reads the server's environment through `{dotted}`", dotted, line)
            elif _OS_WRITE.match(first):
                self.add("template-file-io", HIGH, f"Calls `{dotted}`: changes files or process state", dotted, line)
            elif first not in _OS_HARMLESS:
                self.add("template-file-io", MEDIUM, f"Calls `{dotted}`: inspects the server", dotted, line)
        elif root in _EXEC_BUILTINS:
            self.add("template-exec", CRITICAL, f"Uses `{root}`: runs arbitrary Python", dotted, line)
        elif root in _EXEC_MODULES:
            self.add("template-exec", CRITICAL, f"Uses `{dotted}`: can start processes or load code", dotted, line)
        elif root in _NETWORK_MODULES:
            self.add("template-network", HIGH, f"Uses `{dotted}`: can open network connections", dotted, line)
        elif root in _FILE_BUILTINS:
            self.add("template-file-io", HIGH, f"Uses `{root}()`: reads or writes files on the server", dotted, line)
        elif root in _REFLECTION_BUILTINS:
            self.add("template-reflection", HIGH, f"Uses `{root}`: can reach any Python object", dotted, line)
        elif root == "sys":
            self.add("template-reflection", HIGH, f"Uses `{dotted}`: reaches interpreter state", dotted, line)
        elif root == "__app__":
            self.add(
                "template-app-access",
                HIGH,
                f"Reads Galaxy's application object through `${dotted}` (its config holds secrets)",
                dotted,
                line,
            )
        elif root == "__user__" and rest:
            self.add("template-app-access", MEDIUM, f"Reads the user object through `${dotted}`", dotted, line)
        elif root == "self" and rest:
            if first == "_handleCheetahInclude":
                self.add(
                    "template-include", HIGH, "Uses `#include`: reads another file into the template", dotted, line
                )
            elif first not in _GENERATED_SELF and first not in self.assigned:
                self.add("template-reflection", MEDIUM, f"Uses the template object through `{dotted}`", dotted, line)
        elif root == "trans" and first == "response":
            pass  # the writer Cheetah restores after `#capture`
        elif root in _GENERATED_NAMES and rest:
            self.add("template-reflection", MEDIUM, f"Uses Cheetah internals through `{dotted}`", dotted, line)
        elif root == "time" and first == "sleep":
            self.add("template-file-io", MEDIUM, "Calls `time.sleep`: blocks a job handler", dotted, line)
        for part in rest:
            if _REFLECTION_ATTRS.match(part):
                self.add("template-reflection", HIGH, f"Reaches Python internals through `{dotted}`", dotted, line)
                break
            if part in _MODEL_ATTRS:
                self.add(
                    "template-model-access",
                    MEDIUM,
                    f"Reaches Galaxy's database objects through `{dotted}`",
                    dotted,
                    line,
                )
                break


_NETWORK_COMMANDS = frozenset(
    (
        "curl wget nc ncat netcat ssh scp sftp rsync ftp lftp telnet git svn hg aria2c axel pip pip3 conda mamba"
        " micromamba npm gem cpan cpanm apt apt-get yum dnf apk docker singularity apptainer aws gsutil gcloud az"
        " rclone s3cmd socat ping dig nslookup"
    ).split()
)
_PRIVILEGE_COMMANDS = frozenset("sudo su doas chown chgrp setcap mount umount chroot nsenter unshare".split())
_PERSISTENCE_COMMANDS = frozenset("nohup setsid disown crontab at batch screen tmux systemctl service".split())
_ENVIRONMENT_COMMANDS = frozenset(("printenv",))
_URL = re.compile(r"\b(https?|ftp|sftp|s3|gs)://[^\s'\"]+")
_SENSITIVE_PATH = re.compile(
    r"/etc/(passwd|shadow|sudoers)|(^|/)\.(ssh|aws|kube|gnupg|netrc|pgpass|bash_history|bashrc|profile|docker)\b"
    r"|id_(rsa|ed25519|ecdsa)|authorized_keys|galaxy\.(yml|ini)|/proc/[^/]+/environ|docker\.sock"
)
_REVERSE_SHELL = re.compile(r"/dev/(tcp|udp)/")
_MINER = re.compile(r"xmrig|minerd|stratum\+tcp|cryptonight|nicehash", re.IGNORECASE)
_BLOB = re.compile(r"[A-Za-z0-9+/]{160,}={0,2}|(\\x[0-9a-fA-F]{2}){12,}")


def audit_shell_events(events: set[shell.Event], report: Report, location: str) -> None:
    """Judge the programs, paths and URLs named in the literal text of a command."""

    def add(rule: str, severity: str, message: str, expr: str) -> None:
        report.add(
            Finding(rule=rule, kind=CAPABILITY, severity=severity, message=message, location=location, expr=expr)
        )

    for event in sorted(events):
        if event[0] == "background":
            add("capability-background", INFO, "Starts a process in the background (`&`).", "&")
        elif event[0] == "command":
            name, piped = event[1], event[2]
            if name in shell.SHELLS and piped:
                add(
                    "capability-pipe-to-shell",
                    HIGH,
                    f"Pipes data into `{name}`, which runs it as a script.",
                    f"| {name}",
                )
            elif name in _NETWORK_COMMANDS:
                add("capability-network", LOW, f"Runs `{name}`, which can reach the network.", name)
            elif name in _PRIVILEGE_COMMANDS:
                add("capability-privilege", HIGH, f"Runs `{name}`, which changes privileges or ownership.", name)
            elif name in _PERSISTENCE_COMMANDS:
                add("capability-persistence", MEDIUM, f"Runs `{name}`, which can outlive the job.", name)
            elif name in _ENVIRONMENT_COMMANDS:
                add("capability-environment", LOW, f"Runs `{name}`, which prints the job's environment.", name)
        elif event[0] == "word":
            word = event[1]
            if _REVERSE_SHELL.search(word):
                add("capability-reverse-shell", HIGH, f"Opens a network socket from the shell (`{word}`).", word)
            if match := _SENSITIVE_PATH.search(word):
                add("capability-sensitive-path", HIGH, f"Names a credential or system file (`{word}`).", match.group(0))
            if _MINER.search(word):
                add("capability-miner", HIGH, f"Names cryptocurrency mining software (`{word}`).", word)
            if _BLOB.search(word):
                add("capability-obfuscation", MEDIUM, "Contains a long encoded blob.", word[:40] + "...")
            if match := _URL.search(word):
                add("capability-network", INFO, f"Names the URL `{match.group(0)}`.", match.group(0))


def audit_tool(tool_source: ToolSource, report: Report) -> None:
    """Declarations of the tool that give it more than a command line."""

    def add(rule: str, severity: str, message: str, expr: str, location: str = "tool") -> None:
        report.add(
            Finding(rule=rule, kind=CAPABILITY, severity=severity, message=message, location=location, expr=expr)
        )

    xml_tree = getattr(tool_source, "xml_tree", None)
    if xml_tree is not None:
        _audit_xml_code(xml_tree.getroot(), report, add)
    for variable in _parsed(tool_source.parse_environment_variables, []):
        inject = variable.get("inject") or ""
        if inject == "api_key":
            add(
                "capability-api-key",
                HIGH,
                f"Puts the user's Galaxy API key into the job as ${variable.get('name')}.",
                variable.get("name") or "",
            )
        elif inject.startswith("oidc_"):
            add(
                "capability-api-key",
                HIGH,
                f"Puts the user's identity provider token ({inject}) into the job as ${variable.get('name')}.",
                variable.get("name") or "",
            )
    tool_type = _parsed(tool_source.parse_tool_type, None) or ""
    if tool_type.startswith("data_source"):
        add(
            "capability-network",
            LOW,
            "Is a data source tool: fetches data from a URL a remote site provides.",
            tool_type,
        )
    if _parsed(tool_source.parse_interactivetool, []) or tool_type == "interactive":
        add(
            "capability-network",
            LOW,
            "Is an interactive tool: serves a network port for the job's lifetime.",
            tool_type,
        )
    requirements = _parsed(tool_source.parse_requirements, None)
    for container in requirements[1] if requirements else []:
        image = (container.identifier or "").strip()
        add("capability-container", INFO, f"Runs in the container image `{image}`.", image)
    outputs, collections = _parsed(lambda: tool_source.parse_outputs(None), ({}, {}))
    for output in outputs.values():
        path = getattr(output, "from_work_dir", None) or ""
        if _outside_job_directory(path):
            add(
                "output-path", MEDIUM, f"Collects an output from outside the job directory (`{path}`).", path, "outputs"
            )
    for output in (*outputs.values(), *collections.values()):
        # A collection with a static structure raises here: it discovers nothing.
        for description in _parsed(partial(getattr, output, "dataset_collector_descriptions"), []) or []:
            path = description.directory or ""
            if _outside_job_directory(path):
                add("output-path", MEDIUM, f"Discovers outputs outside the job directory (`{path}`).", path, "outputs")
    if _parsed(tool_source.parse_sanitize, True) is False:
        add(SANITIZE_OFF, MEDIUM, "Turns parameter sanitization off for the whole tool.", "sanitize=false")


def _parsed(parse: Callable[[], Any], default: Any) -> Any:
    """What a tool source method gives, or ``default`` for a tool it cannot parse (the review still returns)."""
    try:
        return parse()
    except Exception:
        return default


def _outside_job_directory(path: str) -> bool:
    return path.startswith("/") or ".." in path.split("/")


def _audit_xml_code(root: Any, report: Report, add: Callable[..., None]) -> None:
    """Python that only the XML of a tool can carry: code files, dynamic options, expressions, filters."""
    for code in root.findall("code"):
        file_name = code.get("file") or ""
        add("tool-code-file", HIGH, f"Loads the Python file `{file_name}` into the Galaxy server process.", file_name)
    for param in root.iter("param"):
        if expression := param.get("dynamic_options"):
            add(
                "tool-code-file",
                HIGH,
                f"Builds the options of `{param.get('name')}` by evaluating Python ({SERVER}).",
                expression,
                "inputs",
            )
    audit = PythonAudit(report, "inputs")
    for validator in root.iter("validator"):
        if validator.get("type") == "expression" and validator.text:
            audit.expression(validator.text)
    for options in root.iter("options"):
        for attribute in ("from_parameter", "transform_lines"):
            if options.get(attribute):
                PythonAudit(report, "inputs", assigned={"tool", "obj"}).expression(options.get(attribute))
    for output_filter in root.findall("./outputs//filter"):
        if output_filter.text:
            PythonAudit(report, "outputs").expression(output_filter.text)
