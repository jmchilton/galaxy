"""The rules of the review's findings (``Finding.rule``), with what each one reports."""

from enum import StrEnum


class Rule(StrEnum):
    # Vulnerabilities: a user value reaches a place where its characters change what runs.
    SHELL_INJECTION = "shell-injection"
    NESTED_INTERPRETER = "nested-interpreter"
    CONFIGFILE_INJECTION = "configfile-injection"
    COMMAND_POSITION = "command-position"
    VARIABLE_NAME = "variable-name"
    PATH_TRAVERSAL = "path-traversal"
    OPTION_INJECTION = "option-injection"
    ARGUMENT_INJECTION = "argument-injection"
    SERVER_INJECTION = "server-injection"
    # Capabilities of template Python, which runs in the Galaxy server process.
    TEMPLATE_COMPILE_EXEC = "template-compile-exec"
    TEMPLATE_EXEC = "template-exec"
    TEMPLATE_NETWORK = "template-network"
    TEMPLATE_IMPORT = "template-import"
    TEMPLATE_REFLECTION = "template-reflection"
    TEMPLATE_ENV = "template-env"
    TEMPLATE_FILE_IO = "template-file-io"
    TEMPLATE_INCLUDE = "template-include"
    TEMPLATE_MACRO = "template-macro"
    TEMPLATE_APP_ACCESS = "template-app-access"
    TEMPLATE_MODEL_ACCESS = "template-model-access"
    # Capabilities of the command the job runs.
    CAPABILITY_BACKGROUND = "capability-background"
    CAPABILITY_PIPE_TO_SHELL = "capability-pipe-to-shell"
    CAPABILITY_NETWORK = "capability-network"
    CAPABILITY_PRIVILEGE = "capability-privilege"
    CAPABILITY_PERSISTENCE = "capability-persistence"
    CAPABILITY_ENVIRONMENT = "capability-environment"
    CAPABILITY_REVERSE_SHELL = "capability-reverse-shell"
    CAPABILITY_SENSITIVE_PATH = "capability-sensitive-path"
    CAPABILITY_MINER = "capability-miner"
    CAPABILITY_OBFUSCATION = "capability-obfuscation"
    CAPABILITY_API_KEY = "capability-api-key"
    CAPABILITY_CONTAINER = "capability-container"
    # Capabilities the tool declares outside its templates.
    TOOL_CODE_FILE = "tool-code-file"
    TOOL_SANITIZE_OFF = "tool-sanitize-off"
    OUTPUT_PATH = "output-path"


VULNERABILITY_RULES = frozenset(
    (
        Rule.SHELL_INJECTION,
        Rule.NESTED_INTERPRETER,
        Rule.CONFIGFILE_INJECTION,
        Rule.COMMAND_POSITION,
        Rule.VARIABLE_NAME,
        Rule.PATH_TRAVERSAL,
        Rule.OPTION_INJECTION,
        Rule.ARGUMENT_INJECTION,
        Rule.SERVER_INJECTION,
    )
)

DESCRIPTIONS = {
    Rule.SHELL_INJECTION: "A value can close the quotes around it, or is written unquoted, and start another"
    " shell command.",
    Rule.NESTED_INTERPRETER: "A value is written into the program of another interpreter (`bash -c`, `sed`,"
    " `perl -e`, ...) and can change what that program does.",
    Rule.CONFIGFILE_INJECTION: "A value is written into a configfile that a script runs and can end its string"
    " and add code.",
    Rule.COMMAND_POSITION: "A value chooses the program that is run: letters alone can be code.",
    Rule.VARIABLE_NAME: "A value names the shell variable that is set, such as `BASH_ENV`, `PATH` or"
    " `LD_PRELOAD`: letters alone can be code.",
    Rule.PATH_TRAVERSAL: "A value is written as a path a command writes or reads (a redirection, an argument of"
    " `cp`, `ln`, `mv`, ...) and can name a file outside the job's directory.",
    Rule.OPTION_INJECTION: "A value starts an argument and can begin with a dash, so the command reads it as an"
    " option.",
    Rule.ARGUMENT_INJECTION: "A value is written unquoted, or can close its quotes, and can split into more words.",
    Rule.SERVER_INJECTION: "A value is passed to template Python that runs a command or opens a file (`subprocess`,"
    " `os.system`, `open()`, ...) in the Galaxy server process.",
    Rule.TEMPLATE_COMPILE_EXEC: "Uses a Cheetah directive that runs code while the template is compiled, in the"
    " Galaxy server process; the template is not analysed further.",
    Rule.TEMPLATE_EXEC: "Runs Python that can start processes or load code (`exec`, `eval`, `subprocess`,"
    " `os.system`, ...).",
    Rule.TEMPLATE_NETWORK: "Imports or uses modules that can open network connections.",
    Rule.TEMPLATE_IMPORT: "Imports a module; high when the module can read or change server state.",
    Rule.TEMPLATE_REFLECTION: "Reaches objects by name (`getattr`, `getVar` with a computed name, Python or"
    " Cheetah internals).",
    Rule.TEMPLATE_ENV: "Reads the server's environment (`os.environ`, `os.getenv`, ...).",
    Rule.TEMPLATE_FILE_IO: "Reads, writes or inspects files or process state of the server (`open()`, `os.path`,"
    " `time.sleep`, ...).",
    Rule.TEMPLATE_INCLUDE: "Uses `#include` of anything but a template macro (a file, fixed text, a value): reads"
    " in template code the review does not follow.",
    Rule.TEMPLATE_MACRO: "Includes a template macro of the tool, which the review reads in and analyses in place.",
    Rule.TEMPLATE_APP_ACCESS: "Reads Galaxy's application object (`$__app__`) or the user object (`$__user__`).",
    Rule.TEMPLATE_MODEL_ACCESS: "Reaches Galaxy's database objects (`.unsanitized`, `.dataset`, `.creating_job`,"
    " ...).",
    Rule.CAPABILITY_BACKGROUND: "Starts a process in the background (`&`).",
    Rule.CAPABILITY_PIPE_TO_SHELL: "Pipes data into a shell, which runs it as a script.",
    Rule.CAPABILITY_NETWORK: "Can reach the network: runs a network program (`curl`, `git`, `pip`, ...), names a"
    " URL, or is a data source or interactive tool.",
    Rule.CAPABILITY_PRIVILEGE: "Runs a program that changes privileges or ownership (`sudo`, `chown`, `mount`,"
    " ...).",
    Rule.CAPABILITY_PERSISTENCE: "Runs a program that can outlive the job (`nohup`, `crontab`, `screen`, ...).",
    Rule.CAPABILITY_ENVIRONMENT: "Runs a program that prints the job's environment (`printenv`).",
    Rule.CAPABILITY_REVERSE_SHELL: "Opens a network socket from the shell (`/dev/tcp/...`).",
    Rule.CAPABILITY_SENSITIVE_PATH: "Names a credential or system file (`/etc/passwd`, `.ssh`, `galaxy.yml`, ...).",
    Rule.CAPABILITY_MINER: "Names cryptocurrency mining software.",
    Rule.CAPABILITY_OBFUSCATION: "Contains a long encoded blob.",
    Rule.CAPABILITY_API_KEY: "Puts the user's Galaxy API key or identity provider token into the job's environment.",
    Rule.CAPABILITY_CONTAINER: "Runs in a container image.",
    Rule.TOOL_CODE_FILE: "Runs Python of the tool in the Galaxy server process (a `<code>` file,"
    " `dynamic_options`).",
    Rule.TOOL_SANITIZE_OFF: "Turns parameter sanitization off for the whole tool.",
    Rule.OUTPUT_PATH: "Collects or discovers outputs outside the job directory.",
}
