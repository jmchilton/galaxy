# Tool security review

`galaxy.tool_util.security` reviews the command and configfile templates of a tool for places where a value a
user controls can leave the quotes or the argument it is written into: a text parameter, a collection element
identifier, a dataset name or metadata element, a group tag, a dataset's content, a user preference. Nothing
from the tool is run: the templates are compiled with Cheetah's compiler and the resulting syntax tree is
analysed. Galaxy also checks the values of each job against the review of its tool (see
[Checking jobs](#checking-jobs)).

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

The exit code is 1 when a path has an error, or when a `--fail-on` condition is met. `--fail-on` can be
given several times:

- `--fail-on <severity>` (for example `high`) fails on any finding of that severity or above, vulnerability
  or capability alike: a tool whose templates run Python in the Galaxy process (`template-exec`, critical)
  fails `--fail-on critical`.
- `--fail-on uncheckable` fails on a tool with an uncheckable code.
- `--fail-on unchecked` fails on a tool with any classified unchecked location (`uncheckable_locations`). That
  includes templates the review did not analyse, such as one that does not compile, which have no
  uncheckable code and so pass `--fail-on uncheckable`.

`pip install galaxy-tool-util` installs the review, its CLI and the spec cases below.

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
`requires`), which the [job check](#checking-jobs) compares with a job's values.
`galaxy.tool_util.security.classify.classify()` adds the templates with a finding that is not checkable, or
that read objects by name; the CLI prints this classified set as `uncheckable_locations`, next to the report's
own `unchecked_locations`. `classify()` also gives the [uncheckable codes](#uncheckable-codes) of a tool whose
templates the review cannot decide.

## Checking jobs

A Galaxy process that prepares jobs reviews a tool when it prepares the tool's first job, and keeps the review
as long as it keeps the tool. Before a job's command line is built, the values of the job are compared with the
tool's findings. Two options in `galaxy.yml` control what happens then:

- `tool_security_review` sets what a value may not do. Each level fails the jobs the one before it fails, and
  more:
  - `enforce_code` (the default): a value may not become code, such as starting a shell command, changing the
    program of another interpreter or the code of a configfile, or choosing the program that is run.
  - `enforce_data`: a value also stays the data it is meant to be. It may not name a path outside the job's
    directory, be read as an option, split into words that are options or paths, or change the structure of a
    data configfile. Element identifiers and dataset names that a template writes may not contain `/` or start
    with `-` or `~`.
  - `enforce_all`: a value also may not split into extra plain words or close its quotes.

  `log` only logs a warning for what `enforce_all` would fail, and `off` turns the review and the checks off.

- `tool_security_review_when_unsure`: for jobs the review cannot check, `strict` (the default) requires every
  value the job carries to be plain, and refuses every job of a tool none of whose values can be checked (a
  tool with an [uncheckable code](#uncheckable-codes)). `refuse` fails every such job, and `log` runs it and
  logs what `strict` would fail.

A plain value has no quotes, no `$ ; & | < > \ ( ) { } [ ] % # *`, no newline or tab, no word that starts with
`-`, and none of Galaxy's sanitizer tokens such as `__gt__`. Each refused job carries
[refusal codes](#refusal-codes).

Galaxy's own tools are not reviewed: the upload tool (`upload1`) and the tools Galaxy runs itself (set
metadata, data fetch, history import and export). Nor are tools without a command template, user-defined tools
and expression tools. Every other tool Galaxy ships with a command template is reviewed: its stock tools
wherever Galaxy is installed, the datatype converters and the sample sheet tools (the collection operations have
no command). Galaxy's own tools are matched by their real path, so a copy of one elsewhere is reviewed like any
other tool. Galaxy logs once per tool, at `INFO`, that one of its own tools is not reviewed.

The upload tool is the one the default settings would otherwise refuse. Galaxy gives an upload job its outputs
when it creates the job, so the tool cannot list them and its template reads them by a computed name
(`$getVar('output%i' % $outnum)`), which the review cannot check. Its file is `data_source/upload.xml` in
Galaxy's bundled tools (`tools/` in a source checkout), or a link to it. A Tool Shed or local tool that declares
the same id and upload action from another path gets a warning naming the bundled file, once per tool.

## Spec cases

The examples below are the cases of the review's declarative spec, `lib/galaxy/tool_util/security/spec/`,
which ships in `galaxy-tool-util`. Each case is a synthetic tool XML file, what the review must report for it
(findings that must match, the exact rules of its serious findings, its unchecked locations, whether it
rewrites values, its access patterns and its uncheckable codes), and the jobs it refuses and runs. A job lists
everything a template can read: parameter values (`inputs`), datasets (`name`, `content`, `metadata`,
`tags`), collections (element identifiers), the user's preferences, and the review's settings (`config`).
Galaxy's unit tests review every spec tool and compare the report with its case. They also run every job
through the evaluator that prepares real jobs, in the mode of the job's `config` and in `log` mode. For the
refused jobs that show `harm-marker`, they build the command with the review off and run it, to show that the
value does harm without the review. They also sweep every job: with the default settings, each value a job
sets, each of a few preferences, and the user's email and name in turn hold a value that starts a command, and
the job must be refused or run without harm.

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

Refused

```
inputs:
  word: a';touch harm-marker;'
```

Runs: Command characters stay inside the quotes when no quote closes them.

```
inputs:
  word: a;b|c && d
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

Runs

```
inputs:
  word: a';touch harm-marker;'
```

### file_param_stays_quoted

A file param is written as Galaxy writes a text param, through its sanitizer, so it cannot leave its single quotes.

Tool `file_param_single_quoted.xml`:

```
cat '$f' > '$out'
```

Review:

```
serious_rules: []
codes: []
```

Runs

```
inputs:
  f: a';touch harm-marker;'
```

Runs: A file that exists, so the sweep's payloads are checked for harm.

```
inputs:
  f: /dev/null
```

### ftpfile_param_shell_injection

An ftpfile param is written as the user's file names, with no sanitizer, and can close its single quotes.

Tool `ftpfile_param_single_quoted.xml`:

```
cat '$f' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  severity: high
  accessor: raw
  param: f
  checkable: true
serious_rules:
- shell-injection
```

Refused

```
inputs:
  f: a';touch harm-marker;'
```

Refused: Galaxy writes the file names after the user's FTP directory, which is named after the email address by default.

```
inputs:
  f: reads.txt
user:
  email: a'$(touch harm-marker)'@example.org
```

Runs

```
inputs:
  f: a;b|c && d
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

Refused

```
collections:
  input:
    elements:
    - identifier: a';touch harm-marker;'
```

Runs: Spaces, slashes and dots are common in identifiers and stay in place.

```
collections:
  input:
    elements:
    - identifier: sample 1/reads.fq
```

Runs: A lone quote only splits arguments, a medium finding the check lets through; the command it builds does not parse, which is the tool's bug rather than a way out.

```
collections:
  input:
    elements:
    - identifier: Bob's reads
```

### dataset_name_stays_quoted

Outside a collection, the element identifier of a dataset input is its name, which Galaxy sanitizes. The review counts it as written as the user set it; the job check reads it as the template does.

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

Runs

```
datasets:
  input:
    name: a';touch harm-marker;'
```

### wrapped_names_stay_quoted

Galaxy sanitizes dataset names and metadata read through the dataset wrapper even in a tool that turns the sanitizer off. The review counts them as written as users set them; the job check reads them as the template does, so these jobs run.

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

Runs

```
datasets:
  input:
    name: a';touch harm-marker;'
    ext: tabular
    content: "1\t2\n"
    metadata:
      column_names:
      - a';touch harm-marker;'
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

Refused

```
datasets:
  input:
    tags:
    - group:a';touch harm-marker;'
```

Runs: Command characters stay inside the quotes when no quote closes them.

```
datasets:
  input:
    tags:
    - group:a;b
    - name:sample1
```

### dataset_content_shell_injection

A template that reads a dataset with open() writes its content; the check reads the file Galaxy keeps.

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

Refused

```
datasets:
  input:
    content: 'a'';touch harm-marker;''

      '
```

Runs: Command characters stay inside the quotes when no quote closes them.

```
datasets:
  input:
    content: 'chr1;100|200

      '
```

### user_preference_stays_quoted

Unless the tool turns the sanitizer off, Galaxy sanitizes what a template reads from the user object, preferences included. The review counts a preference as written as the user set it; the job check reads it as the template does, so this job runs.

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

Runs

```
user:
  preferences:
    spec|label: a';touch harm-marker;'
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

Refused

```
user:
  preferences:
    spec|label: a';touch harm-marker;'
    label: x
```

Refused

```
user:
  preferences:
    spec|label: x
    label: a';touch harm-marker;'
```

Runs: Command characters stay inside the quotes when no quote closes them.

```
user:
  preferences:
    spec|label: a;b|c && d
    label: a;b|c && d
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

Refused

```
inputs:
  word: x;touch harm-marker;#
collections:
  input:
    elements:
    - identifier: Bob's reads
```

Runs: The same value with no quote before it stays inside its quotes.

```
inputs:
  word: x;touch harm-marker;#
collections:
  input:
    elements:
    - identifier: Bobs reads
```

Runs: The same lone quote next to a value without command characters.

```
inputs:
  word: it's fine
collections:
  input:
    elements:
    - identifier: Bob's reads
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

Refused

```
inputs:
  word: a;touch harm-marker
```

Runs

```
inputs:
  word: hello world
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

Refused

```
inputs:
  word: 'y/;e touch harm-marker

    s/x/'
```

Runs

```
inputs:
  word: hello world
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

Refused

```
inputs:
  word: ''';open(''harm-marker'',''w'');'''
```

Runs

```
inputs:
  word: a;b "c" $d
```

### repr_python_literal

repr() of a string is a Python string literal, with the value's quotes and backslashes escaped. Written as code in a Python configfile, outside any string, it stays one string, even for a raw value.

Tool `repr_python_literal.xml`:

```
python3 '$script' > '$out'
```

Review:

```
serious_rules: []
codes: []
```

Runs

```
inputs:
  raw_word: ''';open(''harm-marker'',''w'');'''
  word: ' or exec(bytes((111,112,101,110,40,39,104,97,114,109,45,109,97,114,107,101,114,39,44,39,119,39,41)))
    or '
```

### repr_inside_python_string

Inside a string, the quotes repr() writes end that string, so even a sanitized value that has no quote of its own is then Python code.

Tool `repr_inside_python_string.xml`:

```
python3 '$script' > '$out'
```

Review:

```
findings:
- rule: configfile-injection
  severity: high
  location: configfile:script
  accessor: text
  param: word
  checkable: true
serious_rules:
- configfile-injection
```

Refused: Python code that needs no quote of its own.

```
inputs:
  word: ' or exec(bytes((111,112,101,110,40,39,104,97,114,109,45,109,97,114,107,101,114,39,44,39,119,39,41)))
    or '
```

Runs

```
inputs:
  word: a b, c.d = e
```

### json_inside_python_string

json.dumps() of a string writes it between double quotes. Inside a "..." string of a Python configfile, those quotes end the string.

Tool `json_inside_python_string.xml`:

```
python3 '$script' > '$out'
```

Review:

```
findings:
- rule: configfile-injection
  severity: high
  location: configfile:script
  accessor: text
  param: word
  checkable: true
serious_rules:
- configfile-injection
```

Refused: Python code that needs no quote of its own.

```
inputs:
  word: ' or exec(bytes((111,112,101,110,40,39,104,97,114,109,45,109,97,114,107,101,114,39,44,39,119,39,41)))
    or '
```

Runs

```
inputs:
  word: a b, c.d = e
```

### path_traversal

A file name the user gives is written as a path `cp` writes to. With `enforce_data`, a slash in it is refused, since it can name a file outside the job's directory.

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

Refused

```
inputs:
  name: ../harm-marker
datasets:
  input:
    name: reads.txt
config:
  mode: enforce_data
```

Runs

```
inputs:
  name: reads.txt
datasets:
  input:
    name: reads.txt
config:
  mode: enforce_data
```

Runs: With `enforce_code`, the default, a path is not refused.

```
inputs:
  name: ../reads.txt
datasets:
  input:
    name: reads.txt
```

### option_injection

A quoted value that starts an argument can begin with a dash, and `sort` reads it as an option. With `enforce_data`, a leading dash is refused.

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

Refused

```
inputs:
  file: -oharm-marker
datasets:
  input:
    name: reads.txt
config:
  mode: enforce_data
```

Runs: A dash inside the value is not an option.

```
inputs:
  file: reads-1.txt
datasets:
  input:
    name: reads.txt
config:
  mode: enforce_data
```

Runs: With `enforce_code`, the default, a leading dash is not refused.

```
inputs:
  file: -r
datasets:
  input:
    name: reads.txt
```

### argument_injection

An unquoted value splits into words. With `enforce_data`, a job is refused when a word can be an option, a home directory, a path or a glob; with `enforce_all`, also when the words are plain.

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

Refused

```
inputs:
  files: reads.txt -o harm-marker
datasets:
  input:
    name: reads.txt
config:
  mode: enforce_data
```

Refused: Plain words are refused only with `enforce_all`.

```
inputs:
  files: reads.txt reads.txt
datasets:
  input:
    name: reads.txt
config:
  mode: enforce_all
```

Runs

```
inputs:
  files: reads.txt reads.txt
datasets:
  input:
    name: reads.txt
config:
  mode: enforce_data
```

Runs

```
inputs:
  files: reads.txt
datasets:
  input:
    name: reads.txt
config:
  mode: enforce_all
```

### path_like_name

`sort -o` writes to a file named after the element identifier, which the review does not take for a path of its own. With `enforce_data`, an identifier or dataset name that a template writes may not contain a slash or start with a dash or a tilde.

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

Refused

```
datasets:
  input:
    name: ../harm-marker
config:
  mode: enforce_data
```

Refused

```
datasets:
  input:
    name: -reads.txt
config:
  mode: enforce_data
```

Runs

```
datasets:
  input:
    name: reads 1.txt
config:
  mode: enforce_data
```

Runs: With `enforce_code`, the default, a path is not refused.

```
datasets:
  input:
    name: ../reads.txt
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

Refused

```
inputs:
  label: x touch harm-marker
datasets:
  input:
    name: reads.txt
```

Runs

```
inputs:
  label: x
datasets:
  input:
    name: reads.txt
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

Refused

```
inputs:
  name: LABEL
datasets:
  input:
    name: reads.txt
```

Runs

```
inputs:
  name: LABEL
datasets:
  input:
    name: reads.txt
config:
  when_unsure: log
```

### export_value

bash and dash from 0.5.11 take an operand of `export` whole, older dash splits it into more assignments. With `enforce_data`, an unquoted value of one that holds a space and a `=` is refused.

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

Refused

```
inputs:
  label: x OTHER=1
datasets:
  input:
    name: reads.txt
config:
  mode: enforce_data
```

Runs

```
inputs:
  label: x y
datasets:
  input:
    name: reads.txt
config:
  mode: enforce_data
```

### not_analysed_strict

Where the review does not follow parts of a template, it cannot tell which characters do harm, so every value the template reads must be plain.

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

Refused

```
collections:
  input:
    elements:
    - identifier: a';touch harm-marker;'
```

Refused: Even a character that is harmless where the value is written.

```
collections:
  input:
    elements:
    - identifier: a;b
```

Runs

```
collections:
  input:
    elements:
    - identifier: sample 1/reads.fq
```

Runs: An administrator can run such jobs and only log what the strict check refuses.

```
collections:
  input:
    elements:
    - identifier: a;b
config:
  when_unsure: log
```

### mutator_passed_on

The review follows a method that changes a list where the template calls it on the list, or maps it over values. Passed on to anything else, here `filter`, what it adds is not followed: every value the template reads must be plain.

Tool `mutator_passed_on.xml`:

```
#set $words = []
#silent list(filter(words.append, [$word.value]))
echo '${' '.join($words)}' > '$out'
```

Review:

```
unchecked_locations:
  command: parts of it were not analysed
codes: []
```

Refused

```
inputs:
  word: a';touch harm-marker;'
```

Runs

```
inputs:
  word: sample_1
```

### raw_dataset_model

`$input.unsanitized.name` is the dataset's name as the user set it, without the sanitizer: the check reads it from the model too.

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

Refused

```
datasets:
  input:
    name: a';touch harm-marker;'
```

Runs: Command characters stay inside the quotes when no quote closes them.

```
datasets:
  input:
    name: a;b|c
```

### raw_dataset_history

Beyond the dataset's own strings and metadata, the model reaches its history, its tags and the job that made it, which no check of the job's values sees: every job is refused.

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

Refused

```
datasets:
  input:
    name: reads
```

Runs

```
datasets:
  input:
    name: reads
config:
  when_unsure: log
```

### include_dataset

`#include` of a value reads template code the job sends: here the dataset, which no sanitizer touches. Its `#` directives would run in the server; every job is refused.

Tool `include_dataset.xml`:

```
#set $path = str($input)
#include $path
echo x > '$out'
```

Review:

```
findings:
- rule: template-include
  severity: critical
unchecked_locations:
  command: parts of it were not analysed
patterns:
- template-code
codes:
- uncheckable-template-code
```

Refused

```
datasets:
  input:
    content: 'touch harm-marker

      '
```

Runs

```
datasets:
  input:
    content: 'echo hi

      '
config:
  when_unsure: log
```

### template_macro_rebound

`#include source=$pre#` reads the template macro `pre` only while nothing else answers to `$pre`. Here a `#set` does, so the value is included: every job is refused.

Tool `template_macro_rebound.xml`:

```
#set $pre = str($word)
#include source=$pre#
echo x > '$out'
```

Review:

```
findings:
- rule: template-include
  severity: critical
unchecked_locations:
  command: parts of it were not analysed
patterns:
- template-code
codes:
- uncheckable-template-code
```

Refused

```
inputs:
  word: touch harm-marker &&
```

Runs

```
inputs:
  word: echo hi &&
config:
  when_unsure: log
```

### pipe_to_shell

A value in text piped to a shell is code whatever its characters, so every job is refused.

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

Refused

```
inputs:
  word: a;touch harm-marker
```

Refused: Even a plain value.

```
inputs:
  word: hello
```

Runs

```
inputs:
  word: hello
config:
  when_unsure: log
```

### shell_runs_script_file

A shell given a script file reads the data piped into it as input, not as code, so the value is checked where it is written.

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

Refused

```
inputs:
  word: a';touch harm-marker;'
```

Runs: Command characters stay inside the quotes, and the script reads them as data.

```
inputs:
  word: a;b|c $(touch harm-marker)
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

Refused

```
inputs:
  program: touch harm-marker
```

Runs

```
inputs:
  program: echo
config:
  when_unsure: log
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

Refused

```
inputs:
  word: x' >harm-marker '
```

Refused: Even a plain value.

```
inputs:
  word: hello
```

Runs

```
inputs:
  word: hello
config:
  when_unsure: log
```

### literal_rewrite

A rewrite with literal text of a value as the job carries it adds what it writes only to a value that holds what it replaces, so the job check judges each job with it. Escaping the double quote of a value that a string method reads past its sanitizer leaves `$` and backticks live.

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

Refused

```
inputs:
  word: $(touch harm-marker)
```

Refused: The job check does not follow the escaping, so a double quote with a command character is refused too.

```
inputs:
  word: x" ; touch harm-marker ; "
```

Runs

```
inputs:
  word: a;b|c && d's
```

Runs: A double quote alone cannot start a command.

```
inputs:
  word: say "hi"
```

### rewrites_and_template_code

A refusal names every reason no value of the tool can be checked.

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

Refused

```
inputs:
  word: x' >harm-marker '
```

Runs

```
inputs:
  word: hello
config:
  when_unsure: log
```

### lambda_late_binding

A lambda reads a name of the template when it is called, not when it is made. Here the template sets the name again in between, to a value: the review does not follow such a lambda, and every job is refused.

Tool `lambda_late_binding.xml`:

```
#set $label = 'sample'
#set $quoted = lambda: "'%s'" % label
#set $label = $word.value
echo ${quoted()} > '$out'
```

Review:

```
findings:
- rule: template-lambda
  severity: high
unchecked_locations:
  command: parts of it were not analysed
patterns:
- template-code
codes:
- uncheckable-template-code
```

Refused

```
inputs:
  word: a';touch harm-marker;'
```

Runs

```
inputs:
  word: a;b
config:
  when_unsure: log
```

### lambda_changes_a_list

A lambda that changes a list of the template with what its call passes in is not followed either: every job is refused.

Tool `lambda_changes_a_list.xml`:

```
#set $words = []
#set $add = lambda value: words.append(value)
#silent $add($word.value)
echo '${' '.join($words)}' > '$out'
```

Review:

```
findings:
- rule: template-lambda
  severity: high
unchecked_locations:
  command: parts of it were not analysed
patterns:
- template-code
codes:
- uncheckable-template-code
```

Refused

```
inputs:
  word: a';touch harm-marker;'
```

Runs

```
inputs:
  word: a;b
config:
  when_unsure: log
```

### template_code

A template that imports code can read text the job does not carry, so no value counts as plain.

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

Refused

```
inputs:
  word: hello
```

Runs

```
inputs:
  word: hello
config:
  when_unsure: log
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

Refused: Refused before the template runs, even with a plain value (in log mode the template runs `head -n1 /dev/null`).

```
inputs:
  word: /dev/null
```

Runs

```
inputs:
  word: /dev/null
config:
  when_unsure: log
```

### user_object_unsanitized

With the sanitizer off, the user object is read as it is stored. A template that reads it other than by the name of one preference, here every preference in a loop, writes values the job check cannot trace.

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

Refused

```
user:
  preferences:
    spec|label: a';touch harm-marker;'
```

Runs

```
user:
  preferences:
    spec|label: Bob
config:
  when_unsure: log
```

### untraced_value

A preference read in a loop, by a name the template computes, cannot be traced to one preference, so no check sees its value. Galaxy sanitizes it here, but the job is refused whatever its values.

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

Refused

```
user:
  preferences:
    spec|label: hello
```

Runs

```
user:
  preferences:
    spec|label: a';touch harm-marker;'
config:
  when_unsure: log
```

### review_failed

A tool whose review fails cannot have any job checked.

Tool `raw_text_single_quoted.xml`:

```
echo '${word.value}' > '$out'
```

Refused

```
inputs:
  word: hello
fault: review
```

Runs

```
inputs:
  word: hello
config:
  when_unsure: log
fault: review
```

### check_failed

When comparing a job's values with the review fails, every value must be plain.

Tool `raw_text_single_quoted.xml`:

```
echo '${word.value}' > '$out'
```

Refused

```
inputs:
  word: a;b
fault: check
```

Runs

```
inputs:
  word: hello
fault: check
```

### strict_check_failed

When the strict check itself fails, the job is refused.

Tool `search_list.xml`:

```
#for $e in $input
echo '$e.element_identifier' >> '$out';
#end for
echo '$searchList' > /dev/null
```

Refused

```
collections:
  input:
    elements:
    - identifier: sample1
fault: strict_check
```

Runs

```
collections:
  input:
    elements:
    - identifier: sample1
config:
  when_unsure: log
fault: strict_check
```

### reflection_bypass

Read by name through `getattr`, the dataset model is out of the review's sight: it can write any value without a finding about it, its history's name as well as its own, so every job is refused.

Tool `reflection_getattr.xml`:

```
#set $attribute = 'unsanitized'
#set $name = getattr($input, $attribute).name
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

Refused

```
datasets:
  input:
    name: x'; touch harm-marker; echo '
```

Refused: Even a plain name.

```
datasets:
  input:
    name: reads.fq
```

Runs

```
datasets:
  input:
    name: reads.fq
config:
  when_unsure: log
```

### output_filter_vars

`vars()` in an output filter reaches Python objects, but Galaxy evaluates filters when it creates the outputs: nothing it reads is written into the command, which is checked as usual.

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

Runs

```
inputs:
  label: a;b|c
```

### getvar_user_name

A name the user gives (`$getVar(str($which))`) can be any variable, which no check of the job's values sees: every job is refused.

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

Refused

```
inputs:
  which: label
  label: hello
```

Runs

```
inputs:
  which: label
  label: hello
config:
  when_unsure: log
```

### known_helper

The read group helper of bwa and bowtie2 looks a parameter up with `getVar` by the name it is called with. Called with literal names only, it reads the parameters it names, whose values are checked as usual.

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

Refused

```
inputs:
  word: a';touch harm-marker;'
```

Runs

```
inputs:
  word: a;b|c && d
```

### known_loop

The hmmer3 tools write each output a select names with `getVar` of the selected value. Galaxy accepts only the select's options, so the loop reads the parameters they name, whose values are checked as usual.

Tool `known_loop.xml`:

```
#for o in str($fields).split(','):
    echo '${getVar($o).value}' >> '$out' &&
#end for
true
```

Review:

```
findings:
- rule: shell-injection
  severity: high
  accessor: raw
  param: word
  checkable: true
- rule: shell-injection
  severity: high
  accessor: raw
  param: other
  checkable: true
serious_rules:
- shell-injection
```

Refused

```
inputs:
  fields:
  - other
  - word
  word: a';touch harm-marker;'
  other: b
```

Runs

```
inputs:
  fields:
  - word
  - other
  word: a;b|c && d
  other: b
```

### known_global_list

The gatk4 tools look a parameter up in each section of a list they set once, with `getVar` of the section and the name. The list is fixed, so the loop reads the parameters it names, whose values are checked as usual.

Tool `known_global_list.xml`:

```
#set global $sections = ['', 'optional.']
#for $sect in $sections
    #if $varExists($sect + "other")
        echo '${getVar($sect + "other").value}' >> '$out' &&
    #end if
#end for
true
```

Review:

```
findings:
- rule: shell-injection
  severity: high
  accessor: raw
  param: optional.other
  checkable: true
serious_rules:
- shell-injection
```

Refused

```
inputs:
  optional:
    other: a';touch harm-marker;'
```

Runs

```
inputs:
  optional:
    other: a;b|c && d
```

### known_literal_list

idpqonvert and llm_hub look a parameter up with `getVar` of each name in a list written in the template, changed by `replace` with fixed text. The names are fixed, so the loop reads the parameters they name, whose values are checked as usual.

Tool `known_literal_list.xml`:

```
#for $engine in ["comet:xcorr", "ms-gf:specevalue"]
    #set $name = $engine.replace(":", "_")
    echo '${getVar("scoring." + $name + "_weight").value}' >> '$out' &&
#end for
true
```

Review:

```
findings:
- rule: shell-injection
  severity: high
  accessor: raw
  param: scoring.comet_xcorr_weight
  checkable: true
- rule: shell-injection
  severity: high
  accessor: raw
  param: scoring.ms-gf_specevalue_weight
  checkable: true
serious_rules:
- shell-injection
```

Refused

```
inputs:
  scoring:
    comet_xcorr_weight: '1'
    ms-gf_specevalue_weight: a';touch harm-marker;'
```

Runs

```
inputs:
  scoring:
    comet_xcorr_weight: '1'
    ms-gf_specevalue_weight: a;b|c && d
```

### known_select_value

infernal cmbuild writes each output a select names with `getVar` of each item of the select's value. Galaxy accepts only the select's options, as a list, or as one option, whose letters the loop then gives: the loop reads the parameters these name, whose values are checked as usual.

Tool `known_select_value.xml`:

```
#for j in $fields.value:
    echo '${getVar($j).value}' >> '$out' &&
#end for
true
```

Review:

```
findings:
- rule: shell-injection
  severity: high
  accessor: raw
  param: word
  checkable: true
- rule: shell-injection
  severity: high
  accessor: raw
  param: other
  checkable: true
serious_rules:
- shell-injection
```

Refused

```
inputs:
  fields:
  - other
  - word
  word: a';touch harm-marker;'
  other: b
```

Runs

```
inputs:
  fields:
  - word
  - other
  word: a;b|c && d
  other: b
```

### nested_scope_lookup

Cheetah looks `$name` up in the frame that runs it. A generator expression, a lambda or (before Python 3.12) a comprehension runs in a frame of its own, which does not hold the template's `#set` locals: there `$label` is the parameter, whatever the template set `label` to. The review reads it as the parameter, whose value is checked as usual.

Tool `nested_scope_lookup.xml`:

```
#set $label = 'sample'
echo '${"".join(str($label.value) for _x in [1])}' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  severity: high
  accessor: raw
  param: label
  checkable: true
serious_rules:
- shell-injection
```

Refused

```
inputs:
  label: a';touch harm-marker;'
```

Runs

```
inputs:
  label: a;b|c && d
```

### nested_scope_lambda

A lambda's body runs in the lambda's own frame too: `$label` there is the parameter, not the `#set` local.

Tool `nested_scope_lambda.xml`:

```
#set $label = 'sample'
#set $quoted = lambda: "'%s'" % $label.value
echo ${quoted()} > '$out'
```

Review:

```
findings:
- rule: shell-injection
  severity: high
  accessor: raw
  param: label
  checkable: true
serious_rules:
- shell-injection
```

Refused

```
inputs:
  label: a';touch harm-marker;'
```

Runs

```
inputs:
  label: a;b|c && d
```

### maybe_unset_local

A `#set` that does not run leaves its local unbound, and `$label` after it is then the parameter of that name. The review reads the name as the local or the parameter, whose value is checked as usual. The job parameters that are not inputs do not reach the templates of a regular tool, so a local of any other name is the local alone.

Tool `maybe_unset_local.xml`:

```
#if $mode == 'fixed'
#set $label = 'sample'
#end if
echo '$label' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  severity: high
  accessor: text
  param: label
  checkable: true
serious_rules:
- shell-injection
```

Refused

```
inputs:
  mode: given
  label: a';touch harm-marker;'
```

Runs

```
inputs:
  mode: given
  label: a;b|c && d
```

### galaxy_url_replaced

A tool that keeps all its job parameters (`<inputs check_values="false">`, a data source tool, which seldom sanitizes) passes its templates the request parameters as they were sent. A parameter named like a value Galaxy sets before it adds the job's parameters (`__galaxy_url__`, `__history_id__`, `__datatypes_config__`) then replaces it, so the review reads such a name as a job parameter, whose value is checked as usual.

Tool `galaxy_url_data_source.xml`:

```
echo '$__galaxy_url__' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  severity: high
  key: __galaxy_url__
  checkable: true
serious_rules:
- shell-injection
```

Refused

```
inputs:
  word: a
  __galaxy_url__: a';touch harm-marker;'
```

Runs

```
inputs:
  word: a
  __galaxy_url__: http://localhost:8080
```

### getvar_request_parameter

In a tool that keeps all its job parameters, `getVar` of a name no input has reads the request parameter of that name when there is one, whose value is checked as usual.

Tool `getvar_request_parameter.xml`:

```
echo '$getVar("organism", "")' > '$out'
```

Review:

```
findings:
- rule: shell-injection
  severity: high
  key: organism
  checkable: true
serious_rules:
- shell-injection
```

Refused

```
inputs:
  word: a
  organism: a';touch harm-marker;'
```

Runs

```
inputs:
  word: a
  organism: Homo sapiens
```

### galaxy_url_kept

A regular tool's templates get only its inputs and the job parameters Galaxy passes them: a job parameter named `__galaxy_url__` does not replace Galaxy's value, which stays out of the review's sight.

Tool `galaxy_url_regular.xml`:

```
echo '$__galaxy_url__' > '$out'
```

Review:

```
serious_rules: []
```

Runs

```
inputs:
  word: a
  __galaxy_url__: a';touch harm-marker;'
```

### pure_lambda

A lambda whose body reads only its arguments, literals and functions that compute a value from them is read as what it gives for the values the template passes: here a value quoted by `json.dumps`, whose own quote still closes the single quotes around it.

Tool `pure_lambda.xml`:

```
#import json
#set $quoted = lambda value: json.dumps(value)
echo '${quoted($word.value)}' > '$out'
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

Refused

```
inputs:
  word: a';touch harm-marker;'
```

Runs

```
inputs:
  word: a;b|c && d
```

### app_model_read

The application object reaches any data of the server. The review flags the read but follows no value of it; this job runs because it writes a count.

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

Runs

```
{}
```

### job_metadata_read

The tool version of the job that made a dataset is set by the server, so the job runs.

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

Runs

```
datasets:
  input:
    name: reads.fq
```

### server_config_read

An id the server encodes is the server's value, so the job runs.

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

Runs

```
{}
```

### refused_when_unsure

An administrator can refuse every job the review cannot check instead of checking its values strictly.

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
```

Refused

```
collections:
  input:
    elements:
    - identifier: sample1
config:
  when_unsure: refuse
```

Runs: With the default `strict`, the same job runs, since its values are plain.

```
collections:
  input:
    elements:
    - identifier: sample1
```

### output_size_limit_read

The data source tools pass the server's output size limit, a number the admin sets, to their script. The review allows this one read of the configuration.

Tool `output_size_limit.xml`:

```
python '$__tool_directory__/data_source.py' '$out' $__app__.config.output_size_limit
```

Review:

```
serious_rules: []
codes: []
```

Runs

```
{}
```

### output_size_limit_reach

Reading past the output size limit, or keeping the configuration in a variable, is still flagged.

Tool `output_size_limit_reach.xml`:

```
#set $config = $__app__.config
echo '$__app__.config.output_size_limit.__class__' > '$out' &&
echo '$config.output_size_limit' >> '$out'
```

Review:

```
findings:
- rule: template-app-access
  severity: high
- rule: template-reflection
  severity: high
patterns:
- server-config
codes:
- uncheckable-template-code
```

Refused

```
{}
```

Runs

```
config:
  when_unsure: log
```

### output_size_limit_getvar

`getVar` of the same name reads the same number, and the review allows it as it allows the read by placeholder.

Tool `output_size_limit_getvar.xml`:

```
python '$__tool_directory__/data_source.py' '$out' $getVar('__app__.config.output_size_limit')
```

Review:

```
serious_rules: []
codes: []
```

Runs

```
{}
```

### output_size_limit_subscript

The allowance is of the attribute read alone: a subscript of the application object, here on the way to the same number, is flagged as a read of the application object. Galaxy's wrapper of the application object takes no subscript, so the tool goes that way only for a negative limit.

Tool `output_size_limit_subscript.xml`:

```
#if $__app__.config.output_size_limit < 0
python '$__tool_directory__/data_source.py' '$out' ${__app__['config'].output_size_limit}
#else
python '$__tool_directory__/data_source.py' '$out' 0
#end if
```

Review:

```
findings:
- rule: template-app-access
  severity: high
patterns:
- app-access
```

Runs

```
{}
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

Cases: `app_model_read`, `output_size_limit_subscript`.

#### `user-object`

Reads the user object with the sanitizer off. A preference read by its name is traced; anything else read from the user object is not.

Cases: `user_preference_shell_injection`, `user_object_unsanitized`.

#### `file-access`

Reads or inspects files on the server (`open()`, `os.path`, ...). The review traces `open()` of an input dataset as its content; any other file is no value of a tool input.

Cases: `dataset_content_shell_injection`.

#### `template-code`

Runs Python the review cannot follow (`exec`, `compile`, imports of modules that start processes or open connections, `#include` of anything but a template macro, a lambda that reads more than its arguments or changes a value).

Cases: `include_dataset`, `template_macro_rebound`, `rewrites_and_template_code`, `lambda_late_binding`, `lambda_changes_a_list`, `template_code`, `server_python_command`.

### Reads of values the server sets

#### `job-metadata`

Checks for the job that made a dataset, or reads its tool id or version, which the server sets.

Cases: `job_metadata_read`.

#### `server-config`

Reads the server's configuration or encodes ids (`$__app__.config`, `$__app__.security`).

Cases: `server_config_read`, `output_size_limit_reach`.

## Rules

Each finding has one of these rules.

### Vulnerabilities

#### `shell-injection`

A value can close the quotes around it, or is written unquoted, and start another shell command.

Cases: `raw_text_shell_injection`, `ftpfile_param_shell_injection`, `element_identifier_shell_injection`, `dataset_name_stays_quoted`, `wrapped_names_stay_quoted`, `group_tags_shell_injection`, `dataset_content_shell_injection`, `user_preference_stays_quoted`, `user_preference_shell_injection`, `stray_quote`, `path_like_name`, `raw_dataset_model`, `raw_dataset_history`, `shell_runs_script_file`, `rewrites_restore_tokens`, `literal_rewrite`, `rewrites_and_template_code`, `user_object_unsanitized`, `untraced_value`, `known_helper`, `known_loop`, `known_global_list`, `known_literal_list`, `known_select_value`, `nested_scope_lookup`, `nested_scope_lambda`, `maybe_unset_local`, `galaxy_url_replaced`, `getvar_request_parameter`, `pure_lambda`.

#### `nested-interpreter`

A value is written into the program of another interpreter (`bash -c`, `sed`, `perl -e`, ...) and can change what that program does.

Cases: `nested_shell`, `sed_program`.

#### `configfile-injection`

A value is written into a configfile that a script runs and can end its string and add code.

Cases: `configfile_python`, `repr_inside_python_string`, `json_inside_python_string`.

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

Cases: `output_size_limit_reach`.

#### `template-env`

Reads the server's environment (`os.environ`, `os.getenv`, ...).

#### `template-file-io`

Reads, writes or inspects files or process state of the server (`open()`, `os.path`, `time.sleep`, ...).

Cases: `dataset_content_shell_injection`.

#### `template-include`

Uses `#include` of anything but a template macro (a file, fixed text, a value): reads in template code the review does not follow.

Cases: `include_dataset`, `template_macro_rebound`.

#### `template-macro`

Includes a template macro of the tool, which the review reads in and analyses in place.

#### `template-lambda`

Uses a lambda that reads more than its arguments or changes a value: what it renders when called is not what the review reads where it is made, so the review does not follow it.

Cases: `lambda_late_binding`, `lambda_changes_a_list`.

#### `template-app-access`

Reads Galaxy's application object (`$__app__`) or the user object (`$__user__`).

Cases: `user_object_unsanitized`, `output_size_limit_reach`, `output_size_limit_subscript`.

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

The templates run Python that can read text no tool input carries (imports, `open()`, `#include` of anything but a template macro, a lambda that reads more than its arguments or changes a value, `$__app__`, `getattr`, what the dataset model behind `.unsanitized` reaches).

Cases: `raw_dataset_history`, `include_dataset`, `template_macro_rebound`, `rewrites_and_template_code`, `lambda_late_binding`, `lambda_changes_a_list`, `template_code`, `server_python_command`, `user_object_unsanitized`, `reflection_bypass`, `getvar_user_name`, `output_size_limit_reach`.

#### `uncheckable-letters-are-code`

Letters alone can be code where the tool writes a value: the program to run, text piped to a shell that runs it, or unquoted Perl or Ruby code.

Cases: `export_name`, `pipe_to_shell`, `command_position`, `server_python_command`.

#### `uncheckable-untraced-value`

The templates write a value the review cannot trace to one input or preference (the user object read in a loop, a conditional built at run time).

Cases: `user_object_unsanitized`, `untraced_value`.

## Refusal codes

Every job Galaxy refuses carries one or more codes: the message of the failed job starts with them
(`[shell-injection] This job was not run: ...`), and so does the warning Galaxy logs
(`Tool security review (shell-injection): job ...`). The uncheckable codes refuse every job of a tool.

### Codes

#### `shell-injection`

A value can close the quotes around it, or is written unquoted, and start another shell command.

Cases: `raw_text_shell_injection`, `ftpfile_param_shell_injection`, `element_identifier_shell_injection`, `group_tags_shell_injection`, `dataset_content_shell_injection`, `user_preference_shell_injection`, `raw_dataset_model`, `shell_runs_script_file`, `literal_rewrite`, `known_helper`, `known_loop`, `known_global_list`, `known_literal_list`, `known_select_value`, `nested_scope_lookup`, `nested_scope_lambda`, `maybe_unset_local`, `galaxy_url_replaced`, `getvar_request_parameter`, `pure_lambda`.

#### `nested-interpreter`

A value is written into the program of another interpreter (`bash -c`, `sed`, `perl -e`, ...) and can change what that program does.

Cases: `nested_shell`, `sed_program`.

#### `configfile-injection`

A value is written into a configfile that a script runs and can end its string and add code.

Cases: `configfile_python`, `repr_inside_python_string`, `json_inside_python_string`.

#### `stray-quote`

A quote in one value is harmless by itself but flips the quoting of the rest of the line, which leaves the command characters of another value unquoted.

Cases: `stray_quote`.

#### `path-traversal`

A value is written as a path a command writes or reads (a redirection, an argument of `cp`, `ln`, `mv`, ...) and can name a file outside the job's directory. Refused from `enforce_data` on.

Cases: `path_traversal`.

#### `option-injection`

A value starts an argument and can begin with a dash, so the command reads it as an option. Refused from `enforce_data` on.

Cases: `option_injection`.

#### `argument-injection`

A value is written unquoted, or can close its quotes, and can split into more words. From `enforce_data` on, a job is refused when a word can then be an option, a home directory, a path or a glob; with `enforce_all`, also when the words are plain or the value only closes its quotes.

Cases: `argument_injection`, `env_assignment`, `export_value`.

#### `path-like-name`

An element identifier or a dataset name that a template writes contains `/` or starts with `-` or `~`. Tools use names as file names and arguments in ways the review does not follow (a program's own options, paths in R or Python), where such a name is a path or an option. Refused from `enforce_data` on.

Cases: `path_like_name`.

#### `not-plain-unchecked-place`

The tool writes values in places the review cannot judge (parts of the template it did not follow, or values it cannot trace), and a value is not plain.

Cases: `not_analysed_strict`, `mutator_passed_on`.

#### `not-plain-check-error`

Comparing the job's values with the review's findings failed (a bug), so the job got the strict check instead, and a value is not plain.

Cases: `check_failed`.

#### `uncheckable-review-failed`

The review of the tool failed, so nothing is known about what its templates do.

Cases: `review_failed`.

#### `uncheckable-rewrites`

The templates change values in ways that can bring back characters the sanitizer took out (`chr()`, a decoder, a `.replace` or `re.sub` of the sanitizer's tokens, of text that is not literal, or of a value template code changed before). A literal rewrite of a value as the job carries it is checked with each job.

Cases: `rewrites_restore_tokens`, `rewrites_and_template_code`.

#### `uncheckable-template-code`

The templates run Python that can read text no tool input carries (imports, `open()`, `#include` of anything but a template macro, a lambda that reads more than its arguments or changes a value, `$__app__`, `getattr`, what the dataset model behind `.unsanitized` reaches).

Cases: `raw_dataset_history`, `include_dataset`, `template_macro_rebound`, `rewrites_and_template_code`, `lambda_late_binding`, `lambda_changes_a_list`, `template_code`, `server_python_command`, `user_object_unsanitized`, `reflection_bypass`, `getvar_user_name`, `output_size_limit_reach`.

#### `uncheckable-letters-are-code`

Letters alone can be code where the tool writes a value: the program to run, text piped to a shell that runs it, or unquoted Perl or Ruby code.

Cases: `export_name`, `pipe_to_shell`, `command_position`, `server_python_command`.

#### `uncheckable-untraced-value`

The templates write a value the review cannot trace to one input or preference (the user object read in a loop, a conditional built at run time).

Cases: `user_object_unsanitized`, `untraced_value`.

#### `uncheckable-strict-check-error`

The strict check itself failed (a bug), so none of the job's values could be checked.

Cases: `strict_check_failed`.

#### `uncheckable-when-unsure`

The review cannot check the job, and the server refuses every such job (`tool_security_review_when_unsure: refuse`) instead of checking its values strictly.

Cases: `refused_when_unsure`.

<!-- END spec cases -->
