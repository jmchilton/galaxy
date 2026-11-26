# Tool security review

`galaxy.tool_util.security` reviews the command and configfile templates of a tool for places where a value a
user controls can leave the quotes or the argument it is written into: a text parameter, a collection element
identifier, a dataset name or metadata element, a group tag, a dataset's content, a user preference. Nothing
from the tool is run: the templates are compiled with Cheetah's compiler and the resulting syntax tree is
analysed. The review is static and offline; it does not change how Galaxy runs jobs.

To see what the review finds in tools, run

```console
$ galaxy-tool-security-review path/to/tool.xml [more/tools.xml ...] [path/to/tools/ ...]
```

(or `python -m galaxy.tool_util.security` from a Galaxy checkout). A directory is searched recursively for
tools. Only XML tools are reviewed. Each tool is listed with its id and version. A tool that fails to load or
review, a YAML or CWL tool (`not reviewed: only XML tools are analysed`) and a directory with no tools
(`no tools found`) are listed with an error instead, and the other tools are still reviewed. A tool reached
through several paths, such as a file and its directory, is reviewed once, under the first.

`--min-severity` hides findings below a severity in the text output. `--json` prints one JSON document with
every finding: by path, the report of the tool with its `tool_version`, its
[uncheckable codes](#uncheckable-codes) (`codes`) and its classified unchecked locations
(`uncheckable_locations`, see below). A path with an error has its `error` instead, `tool_id` and
`tool_version` when the tool loaded, and the code `uncheckable-review-failed`. The text output gives each
unchecked location and uncheckable code a `NOTE` line.

The exit code is 1 when a path has an error, when a `--fail-on` condition is met, or when a tool patch
regresses a tool (see `--tool-patch-path` below). `--fail-on` can be given several times:

- `--fail-on <severity>` (for example `high`) fails on any finding of that severity or above, vulnerability
  or capability alike: a tool whose templates run Python in the Galaxy process (`template-exec`, critical)
  fails `--fail-on critical`. `--judge` verdicts do not change which findings count.
- `--fail-on uncheckable` fails on a tool with an uncheckable code.
- `--fail-on unchecked` fails on a tool with any classified unchecked location (`uncheckable_locations`). That
  includes templates the review did not analyse, such as one that does not compile, which have no
  uncheckable code and so pass `--fail-on uncheckable`.

`--judge` asks Claude whether each vulnerability finding of medium severity or above is real
(it needs the `anthropic` package and credentials). `pip install galaxy-tool-util` installs the review, its CLI and the spec
cases below; `anthropic` is needed only for `--judge`.

`--tool-patch-path` (repeatable) reviews each tool before and after the tool patches (see `tool_patch_paths`) of
those collections, applying every op whatever a site's policy would allow. The report of each tool, its
`codes`, `uncheckable_locations`, `--fail-on` and `--judge` are then of the patched tool. The JSON adds the
patch states (`patches`), the reports `before` and `after` the patches, the findings the patches cleared
(`cleared`) or introduced (`introduced`), and the template parts the review can no longer follow
(`unanalyzed_added`); the text output gives them `PATCH`, `CLEARED`, `NEW` and `NEW NOTE` lines. Findings are
matched by rule, place, how the value lands there and the values read, not by template text, so a value moved
to another place (say, into a configfile) counts as cleared there and new here. A patch regresses a tool, and
the exit code is 1, when it introduces a finding of any severity or leaves part of a template unreviewable; the
review does not check that a patch cleared anything. A collection that does not load stops the run. Tools are
reviewed under their XML id and version (`_local` keys); `--guid` gives the Tool Shed guid of a single tool
file to match its shed key.

## Findings

The review reports two kinds of findings:

- **Vulnerabilities**: a user value reaches a place where its characters change what runs, such as
  `shell-injection` (the value can close its quotes, or is unquoted, and start another command).
  Mostly, `critical` and `high` findings let a value become code, `medium` ones let it stop being the data it is
  meant to be, and `low` ones let it split into extra plain words.
- **Capabilities**: what the tool's author made the tool able to do on the server, such as Python that runs
  inside the Galaxy process (`template-*` rules), network access, or a request for the user's API key
  (`capability-*` rules).

[Rules](#rules) below lists every rule, with the spec cases that show it.

A report also lists the parts of the templates the review could not follow, or that pipe text into a shell to
run (`unchecked_locations`), and the template code that rewrites values in ways that can bring back
characters the sanitizer took out (`rewrites`). A finding is `checkable` when the characters of a concrete
value decide whether it applies; the JSON report keeps the characters involved (`breakout`, `closes`,
`requires`) as inputs for such a value-level check. `galaxy.tool_util.security.classify.classify()` adds the
templates with a finding that is not checkable, or that read objects by name; the CLI prints this classified set
as `uncheckable_locations`, next to the report's own `unchecked_locations`. `classify()` also gives the
[uncheckable codes](#uncheckable-codes) of a tool whose templates the review cannot decide.

## Spec cases

The examples below are the cases of the review's declarative spec, `lib/galaxy/tool_util/security/spec/`,
which ships in `galaxy-tool-util`. Each case is a synthetic tool XML file and what the review must report for it:
findings that must match, the exact rules of its serious findings, its unchecked locations, whether it
rewrites values, its access patterns and its uncheckable codes. Galaxy's unit tests review every spec tool and
compare the report with its case.

<!-- BEGIN spec cases, generated by `python -m galaxy.tool_util.security.spec.docs` -->

### raw_text_shell_injection

A text value written past its sanitizer can close its single quotes and start a command.

Tool `raw_text_single_quoted.xml`:

```
echo '${word.value}' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  severity: high
  accessor: raw
  param: word
  checkable: true
serious_rules:
- shell-injection
codes: []
```

### sanitized_text_stays_quoted

The default sanitizer turns quotes into tokens, so a sanitized text value cannot leave its quotes.

Tool `sanitized_text_single_quoted.xml`:

```
echo '$word' > '$out'
```

Review:

```
serious_rules: []
codes: []
```

### element_identifier_shell_injection

Element identifiers are not sanitized; one in single quotes can start a command.

Tool `element_identifier_single_quoted.xml`:

```
#for $e in $input
echo '$e.element_identifier' >> '$out';
#end for
```

Review:

```
findings:
- rule: shell-injection
  accessor: element_identifier
  param: input
  checkable: true
serious_rules:
- shell-injection
```

### dataset_name_stays_quoted

Outside a collection, the element identifier of a dataset input is its name, which Galaxy sanitizes. The review still reports it as written as the user set it.

Tool `dataset_name_identifier.xml`:

```
echo '$input.element_identifier' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  accessor: element_identifier
  param: input
  checkable: true
serious_rules:
- shell-injection
```

### wrapped_names_stay_quoted

Galaxy sanitizes dataset names and metadata read through the dataset wrapper even in a tool that turns the sanitizer off. The review still reports them as written as users set them.

Tool `dataset_name_unsanitized.xml`:

```
echo '$input.name' '$input.metadata.column_names' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  accessor: dataset_attribute
  param: input
  key: name
  checkable: true
- rule: shell-injection
  accessor: metadata
  param: input
  key: column_names
  checkable: true
serious_rules:
- shell-injection
```

### group_tags_shell_injection

Group tags are not sanitized.

Tool `group_tags.xml`:

```
#for $g in $input.groups
echo '$g' >> '$out';
#end for
```

Review:

```
findings:
- rule: shell-injection
  accessor: group_tags
  param: input
  checkable: true
serious_rules:
- shell-injection
```

### dataset_content_shell_injection

A template that reads a dataset with open() writes its content, which the review follows.

Tool `dataset_content_first_line.xml`:

```
#set $first = open(str($input)).readline().strip()
echo '$first' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  accessor: dataset_content
  param: input
  checkable: true
- rule: template-file-io
serious_rules:
- shell-injection
patterns:
- file-access
codes: []
```

### user_preference_stays_quoted

Unless the tool turns the sanitizer off, Galaxy sanitizes what a template reads from the user object, preferences included. The review still reports a preference as written as the user set it.

Tool `user_preference.xml`:

```
echo '${__user__.extra_preferences.get("spec|label", "")}' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  accessor: user_preference
  key: spec|label
  checkable: true
serious_rules:
- shell-injection
```

### user_preference_shell_injection

With the sanitizer off, a preference is written as the user set it. Read by name, with a subscript or a Cheetah name, it can close its single quotes and start a command.

Tool `user_preference_unsanitized.xml`:

```
echo '${__user__.extra_preferences["spec|label"]}' '$__user__.extra_preferences.label' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  accessor: user_preference
  key: spec|label
  checkable: true
- rule: shell-injection
  accessor: user_preference
  key: label
  checkable: true
serious_rules:
- shell-injection
patterns:
- user-object
```

### stray_quote

A lone quote in one value is harmless by itself, but it flips the quoting of the rest of the line, which leaves the command characters of the next value unquoted.

Tool `stray_quote.xml`:

```
#for $e in $input
echo '$e.element_identifier' >> '$out';
#end for
echo '${word.value}' >> '$out'
```

Review:

```
serious_rules:
- shell-injection
```

### nested_shell

A value in the program of `bash -c` is shell code again, inside the outer quotes.

Tool `nested_shell.xml`:

```
bash -c 'echo ${word.value}' > '$out'
```

Review:

```
findings:
- rule: nested-interpreter
  accessor: raw
  param: word
  checkable: true
serious_rules:
- nested-interpreter
```

### sed_program

A value in a sed program can end the s command and add one that runs a shell command (`e`, GNU sed).

Tool `sed_program.xml`:

```
echo x | sed 's/x/${word.value}/' > '$out'
```

Review:

```
serious_rules:
- nested-interpreter
```

### configfile_python

A value in a string of a Python configfile can end the string and add Python code.

Tool `configfile_python.xml`:

```
python3 '$script' > '$out'
```

Review:

```
findings:
- rule: configfile-injection
  location: configfile:script
  accessor: raw
  param: word
  checkable: true
serious_rules:
- configfile-injection
```

### path_traversal

A file name the user gives is written as a path `cp` writes to. A slash in it can name a file outside the job's directory.

Tool `copy_to_named_file.xml`:

```
mkdir -p outputs && cp '$input' 'outputs/$name' && cp '$input' '$out'
```

Review:

```
findings:
- rule: path-traversal
  severity: medium
  accessor: text
  param: name
  checkable: true
```

### option_injection

A quoted value that starts an argument can begin with a dash, and `sort` reads it as an option.

Tool `sort_quoted_operand.xml`:

```
cp '$input' reads.txt && sort '$file' reads.txt > '$out'
```

Review:

```
findings:
- rule: option-injection
  severity: low
  accessor: text
  param: file
  checkable: true
```

### argument_injection

An unquoted value splits into words, and a word can be an option, a home directory, a path or a glob.

Tool `sort_unquoted_operands.xml`:

```
cp '$input' reads.txt && sort $files > '$out'
```

Review:

```
findings:
- rule: argument-injection
  severity: medium
  accessor: text
  param: files
  checkable: true
```

### path_like_name

`sort -o` writes to a file named after the element identifier. The review reports that the identifier can close its quotes.

Tool `sort_to_named_file.xml`:

```
mkdir -p sorted && sort -o 'sorted/${input.element_identifier}' '$input' && cp '$input' '$out'
```

Review:

```
findings:
- rule: shell-injection
  accessor: element_identifier
  param: input
  checkable: true
serious_rules:
- shell-injection
```

### env_assignment

`env` takes every word before the command as an assignment or the command: an unquoted value that splits runs a command of its own.

Tool `env_assignment.xml`:

```
env LABEL=$label sort '$input' > '$out'
```

Review:

```
findings:
- rule: argument-injection
  severity: high
  accessor: text
  param: label
  checkable: true
```

### export_name

A value that names the variable `export` sets can set BASH_ENV, PATH or LD_PRELOAD with letters alone.

Tool `export_name.xml`:

```
export $name=1 && sort '$input' > '$out'
```

Review:

```
serious_rules:
- variable-name
codes:
- uncheckable-letters-are-code
```

### export_value

bash and dash from 0.5.11 take an operand of `export` whole, older dash splits it into more assignments: an unquoted value of one that holds a space and a `=` can set another variable.

Tool `export_value.xml`:

```
export LABEL=$label && sort '$input' > '$out'
```

Review:

```
findings:
- rule: argument-injection
  severity: medium
  accessor: text
  param: label
  checkable: true
```

### not_analysed_strict

Where the review does not follow parts of a template, it cannot tell which characters do harm there, and it lists the template as unchecked.

Tool `search_list.xml`:

```
#for $e in $input
echo '$e.element_identifier' >> '$out';
#end for
echo '$searchList' > /dev/null
```

Review:

```
unchecked_locations:
  command: parts of it were not analysed
codes: []
```

### raw_dataset_model

`$input.unsanitized.name` is the dataset's name as the user set it, without the sanitizer.

Tool `raw_dataset_model.xml`:

```
echo '${input.unsanitized.name}' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  accessor: raw_dataset_attribute
  param: input
  key: name
  checkable: true
- rule: template-model-access
serious_rules:
- shell-injection
patterns:
- model-access
```

### raw_dataset_history

Beyond the dataset's own strings and metadata, the model reaches its history, its tags and the job that made it, which the review cannot trace to one value: its finding is not checkable.

Tool `raw_dataset_history.xml`:

```
echo '${input.unsanitized.history.name}' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  accessor: opaque
  param: input
  checkable: false
patterns:
- model-access
codes:
- uncheckable-template-code
```

### pipe_to_shell

A value in text piped to a shell is code whatever its characters, so the review lists the command as unchecked.

Tool `pipe_to_shell.xml`:

```
echo 'echo ${word.value}' | sh > '$out'
```

Review:

```
unchecked_locations:
  command: it sends text to a shell to run
codes:
- uncheckable-letters-are-code
```

### shell_runs_script_file

A shell given a script file reads the data piped into it as input, not as code, so the value is reviewed where it is written.

Tool `pipe_to_shell_script.xml`:

```
printf '%s\n' '${word.value}' | sh '$script' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  severity: high
  accessor: raw
  param: word
  checkable: true
serious_rules:
- shell-injection
unchecked_locations: {}
```

### command_position

A value that names the program to run is code with letters alone.

Tool `command_position.xml`:

```
$program > '$out'
```

Review:

```
findings:
- rule: command-position
  accessor: text
  param: program
  checkable: false
serious_rules:
- command-position
codes:
- uncheckable-letters-are-code
```

### rewrites_restore_tokens

A template that turns the sanitizer's tokens back into quotes and redirects undoes the sanitizer.

Tool `rewrites_restore_tokens.xml`:

```
echo '${str($word).replace("__sq__", "'").replace("__gt__", ">")}' > '$out'
```

Review:

```
serious_rules:
- shell-injection
rewrites: true
codes:
- uncheckable-rewrites
```

### literal_rewrite

A rewrite with literal text of a value adds what it writes only to a value that holds what it replaces, so the review does not count it among the rewrites it cannot follow. Escaping the double quote of a value that a string method reads past its sanitizer leaves `$` and backticks live.

Tool `raw_text_escaped_double_quoted.xml`:

```
#set $escaped = $word.replace('"', '\\"')
echo "$escaped" > '$out'
```

Review:

```
findings:
- rule: shell-injection
  severity: high
  accessor: raw
  param: word
  checkable: true
serious_rules:
- shell-injection
rewrites: false
```

### rewrites_and_template_code

The review reports both the rewrite of a value and the template code.

Tool `rewrites_and_template_code.xml`:

```
#import subprocess
echo '${str($word).replace("__sq__", "'").replace("__gt__", ">")}' > '$out'
```

Review:

```
findings:
- rule: template-exec
  severity: critical
serious_rules:
- shell-injection
rewrites: true
patterns:
- template-code
codes:
- uncheckable-rewrites
- uncheckable-template-code
```

### template_code

A template that imports code can read text no input carries, and the review does not follow it.

Tool `template_code.xml`:

```
#import subprocess
echo '$word' > '$out';
echo '$searchList' > /dev/null
```

Review:

```
findings:
- rule: template-exec
  severity: critical
unchecked_locations:
  command: parts of it were not analysed
patterns:
- template-code
codes:
- uncheckable-template-code
```

### server_python_command

Template Python runs in the Galaxy server process while the job is prepared. A value passed to a command it runs decides what the server executes, whatever its characters.

Tool `server_python_command.xml`:

```
#import subprocess
#set $first = subprocess.check_output('head -n1 ' + str($word), shell=True)
echo '$first' > '$out'
```

Review:

```
findings:
- rule: server-injection
  severity: critical
  accessor: text
  param: word
  checkable: false
serious_rules:
- server-injection
patterns:
- template-code
codes:
- uncheckable-letters-are-code
- uncheckable-template-code
```

### user_object_unsanitized

With the sanitizer off, the user object is read as it is stored. A template that reads it other than by the name of one preference, here every preference in a loop, writes values the review cannot trace.

Tool `user_preferences_unsanitized_loop.xml`:

```
#for $name in $__user__.extra_preferences
echo '${__user__.extra_preferences[$name]}' >> '$out' &&
#end for
true
```

Review:

```
findings:
- rule: template-app-access
  severity: medium
- rule: shell-injection
  accessor: opaque
  checkable: false
patterns:
- user-object
codes:
- uncheckable-template-code
- uncheckable-untraced-value
```

### untraced_value

A preference read in a loop, by a name the template computes, cannot be traced to one preference. Galaxy sanitizes it here, but the review reports a value it cannot check.

Tool `user_preferences_loop.xml`:

```
#for $name in $__user__.extra_preferences
echo '${__user__.extra_preferences[$name]}' >> '$out' &&
#end for
true
```

Review:

```
findings:
- rule: shell-injection
  accessor: opaque
  checkable: false
codes:
- uncheckable-untraced-value
```

### reflection_bypass

Read by name through `getattr`, the dataset model is out of the review's sight: it can write any value without a finding about it, its history's name as well as its own. The review reports the reflection.

Tool `reflection_getattr.xml`:

```
#set $name = getattr($input, 'unsanitized').name
echo '${name}' > '$out'
```

Review:

```
serious_rules: []
patterns:
- reflection
codes:
- uncheckable-template-code
```

### output_filter_vars

`vars()` in an output filter reaches Python objects, but Galaxy evaluates filters when it creates the outputs: nothing it reads is written into the command, which is reviewed as usual.

Tool `output_filter_vars.xml`:

```
echo '$label' > '$out'
```

Review:

```
patterns:
- reflection
codes: []
```

### getvar_user_name

A name the user gives (`$getVar(str($which))`) can be any variable, which the review cannot follow: it reports the reflection.

Tool `getvar_user_name.xml`:

```
echo '$getVar(str($which), "none")' > '$out'
```

Review:

```
patterns:
- reflection
codes:
- uncheckable-template-code
```

### known_helper

The read group helper of bwa and bowtie2 looks a parameter up with `getVar` by the name it is called with. Called with literal names only, it reads the parameters it names, whose values are reviewed as usual.

Tool `known_helper.xml`:

```
#def rg_param(name)
    #if $varExists("rg")
        #return $rg.get($name, None)
    #else
        #return $getVar($name, None)
    #end if
#end def
echo '${rg_param('word').value}' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  severity: high
  accessor: raw
  param: word
  checkable: true
serious_rules:
- shell-injection
```

### app_model_read

The application object reaches any data of the server. The review flags the read but follows no value of it, and this tool writes only a count.

Tool `app_model.xml`:

```
#set $users = $__app__.model.context.query($__app__.model.User).count()
echo '${users}' > '$out'
```

Review:

```
serious_rules: []
patterns:
- app-access
```

### job_metadata_read

The tool version of the job that made a dataset is set by the server, not by a user.

Tool `job_metadata.xml`:

```
#if $input.creating_job
echo '${input.creating_job.tool_version}' > '$out'
#else
echo unknown > '$out'
#end if
```

Review:

```
serious_rules: []
patterns:
- job-metadata
codes: []
```

### server_config_read

An id the server encodes is the server's value, not a user's.

Tool `server_config.xml`:

```
echo '${__app__.security.encode_id(1)}' > '$out'
```

Review:

```
serious_rules: []
patterns:
- server-config
```

## Access patterns

The review also reports reads it cannot follow to a value of a tool input. A read by name (reflection)
can write any value without a finding about it.

### Reads the review cannot follow

#### `reflection`

Reaches objects by name (`getattr`, `__getattribute__`, `getVar` with a computed name, Python or Cheetah internals). The review loses track of what is read, `.unsanitized` values included.

Cases: `reflection_bypass`, `output_filter_vars`, `getvar_user_name`.

#### `model-access`

Reads Galaxy's database objects (`.unsanitized`, `.dataset`, `.creating_job`, ...): names, metadata and parameters as users set them, without the sanitizer.

Cases: `raw_dataset_model`, `raw_dataset_history`.

#### `app-access`

Reads Galaxy's application object beyond its configuration (`$__app__.model`, ...), which reaches any data of the server.

Cases: `app_model_read`.

#### `user-object`

Reads the user object with the sanitizer off. A preference read by its name is traced; anything else read from the user object is not.

Cases: `user_preference_shell_injection`, `user_object_unsanitized`.

#### `file-access`

Reads or inspects files on the server (`open()`, `os.path`, ...). The review traces `open()` of an input dataset as its content; any other file is no value of a tool input.

Cases: `dataset_content_shell_injection`.

#### `template-code`

Runs Python the review cannot follow (`exec`, `compile`, imports of modules that start processes or open connections).

Cases: `rewrites_and_template_code`, `template_code`, `server_python_command`.

### Reads of values the server sets

#### `job-metadata`

Checks for the job that made a dataset, or reads its tool id or version, which the server sets.

Cases: `job_metadata_read`.

#### `server-config`

Reads the server's configuration or encodes ids (`$__app__.config`, `$__app__.security`).

Cases: `server_config_read`.

## Rules

Each finding has one of these rules.

### Vulnerabilities

#### `shell-injection`

A value can close the quotes around it, or is written unquoted, and start another shell command.

Cases: `raw_text_shell_injection`, `element_identifier_shell_injection`, `dataset_name_stays_quoted`, `wrapped_names_stay_quoted`, `group_tags_shell_injection`, `dataset_content_shell_injection`, `user_preference_stays_quoted`, `user_preference_shell_injection`, `stray_quote`, `path_like_name`, `raw_dataset_model`, `raw_dataset_history`, `shell_runs_script_file`, `rewrites_restore_tokens`, `literal_rewrite`, `rewrites_and_template_code`, `user_object_unsanitized`, `untraced_value`, `known_helper`.

#### `nested-interpreter`

A value is written into the program of another interpreter (`bash -c`, `sed`, `perl -e`, ...) and can change what that program does.

Cases: `nested_shell`, `sed_program`.

#### `configfile-injection`

A value is written into a configfile that a script runs and can end its string and add code.

Cases: `configfile_python`.

#### `command-position`

A value chooses the program that is run: letters alone can be code.

Cases: `command_position`.

#### `variable-name`

A value names the shell variable that is set, such as `BASH_ENV`, `PATH` or `LD_PRELOAD`: letters alone can be code.

Cases: `export_name`.

#### `path-traversal`

A value is written as a path a command writes or reads (a redirection, an argument of `cp`, `ln`, `mv`, ...) and can name a file outside the job's directory.

Cases: `path_traversal`.

#### `option-injection`

A value starts an argument and can begin with a dash, so the command reads it as an option.

Cases: `option_injection`.

#### `argument-injection`

A value is written unquoted, or can close its quotes, and can split into more words.

Cases: `argument_injection`, `env_assignment`, `export_value`.

#### `server-injection`

A value is passed to template Python that runs a command or opens a file (`subprocess`, `os.system`, `open()`, ...) in the Galaxy server process.

Cases: `server_python_command`.

### Capabilities

#### `template-compile-exec`

Uses a Cheetah directive that runs code while the template is compiled, in the Galaxy server process; the template is not analysed further.

#### `template-exec`

Runs Python that can start processes or load code (`exec`, `eval`, `subprocess`, `os.system`, ...).

Cases: `rewrites_and_template_code`, `template_code`.

#### `template-network`

Imports or uses modules that can open network connections.

#### `template-import`

Imports a module; high when the module can read or change server state.

#### `template-reflection`

Reaches objects by name (`getattr`, `getVar` with a computed name, Python or Cheetah internals).

#### `template-env`

Reads the server's environment (`os.environ`, `os.getenv`, ...).

#### `template-file-io`

Reads, writes or inspects files or process state of the server (`open()`, `os.path`, `time.sleep`, ...).

Cases: `dataset_content_shell_injection`.

#### `template-include`

Uses `#include` to read another file into the template.

#### `template-app-access`

Reads Galaxy's application object (`$__app__`) or the user object (`$__user__`).

Cases: `user_object_unsanitized`.

#### `template-model-access`

Reaches Galaxy's database objects (`.unsanitized`, `.dataset`, `.creating_job`, ...).

Cases: `raw_dataset_model`.

#### `capability-background`

Starts a process in the background (`&`).

#### `capability-pipe-to-shell`

Pipes data into a shell, which runs it as a script.

#### `capability-network`

Can reach the network: runs a network program (`curl`, `git`, `pip`, ...), names a URL, or is a data source or interactive tool.

#### `capability-privilege`

Runs a program that changes privileges or ownership (`sudo`, `chown`, `mount`, ...).

#### `capability-persistence`

Runs a program that can outlive the job (`nohup`, `crontab`, `screen`, ...).

#### `capability-environment`

Runs a program that prints the job's environment (`printenv`).

#### `capability-reverse-shell`

Opens a network socket from the shell (`/dev/tcp/...`).

#### `capability-sensitive-path`

Names a credential or system file (`/etc/passwd`, `.ssh`, `galaxy.yml`, ...).

#### `capability-miner`

Names cryptocurrency mining software.

#### `capability-obfuscation`

Contains a long encoded blob.

#### `capability-api-key`

Puts the user's Galaxy API key or identity provider token into the job's environment.

#### `capability-container`

Runs in a container image.

#### `tool-code-file`

Runs Python of the tool in the Galaxy server process (a `<code>` file, `dynamic_options`).

#### `tool-sanitize-off`

Turns parameter sanitization off for the whole tool.

#### `output-path`

Collects or discovers outputs outside the job directory.

## Uncheckable codes

Where a template writes values that no character test of a finding can judge (the classified unchecked
locations, `uncheckable_locations` in the CLI's JSON), only a check that every value is plain could vet a
job. `classify()` and the CLI give these codes when not even that could: the review cannot decide the tool
from its templates. A template the review did not analyse is unchecked but gets no code of its own, so
`--fail-on uncheckable` lets it through and `--fail-on unchecked` does not.

### Codes

#### `uncheckable-review-failed`

The review did not run: the tool could not be loaded or reviewed, it is not an XML tool, or a directory held no tools. Nothing is known about what the templates do.

#### `uncheckable-rewrites`

The templates change values in ways that can bring back characters the sanitizer took out (`chr()`, a decoder, a `.replace` or `re.sub` of the sanitizer's tokens, of text that is not literal, or of a value template code changed before).

Cases: `rewrites_restore_tokens`, `rewrites_and_template_code`.

#### `uncheckable-template-code`

The templates run Python that can read text no tool input carries (imports, `open()`, `$__app__`, `getattr`, what the dataset model behind `.unsanitized` reaches).

Cases: `raw_dataset_history`, `rewrites_and_template_code`, `template_code`, `server_python_command`, `user_object_unsanitized`, `reflection_bypass`, `getvar_user_name`.

#### `uncheckable-letters-are-code`

Letters alone can be code where the tool writes a value: the program to run, text piped to a shell that runs it, or unquoted Perl or Ruby code.

Cases: `export_name`, `pipe_to_shell`, `command_position`, `server_python_command`.

#### `uncheckable-untraced-value`

The templates write a value the review cannot trace to one input or preference (the user object read in a loop, a conditional built at run time).

Cases: `user_object_unsanitized`, `untraced_value`.

<!-- END spec cases -->
