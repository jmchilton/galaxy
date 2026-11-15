"""Build the GA4GH TES task of a TES-native job (``galaxy.jobs.runners.tes``).

Pure functions of paths on Galaxy's disk: which files the task stages in and
out, the signed job files API URL of each, the executor's wrapper script around
Galaxy's job script, and the task document itself. Every path is the same
inside the task as on Galaxy's disk.
"""

import logging
import os
import re
import shlex
from collections.abc import (
    Callable,
    Iterable,
    Iterator,
)
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from pydantictes.models import (
    TesExecutor,
    TesFileType,
    TesInput,
    TesOutput,
    TesResources,
    TesTask,
)

from galaxy.security.job_files_tokens import (
    JOB_FILES_DIRECTORY_WRITE,
    JOB_FILES_READ,
    job_files_token,
    JOB_FILES_WRITE,
    JobFilesScope,
)
from galaxy.util import in_directory

if TYPE_CHECKING:
    from galaxy.security.idencoding import IdEncodingHelper

log = logging.getLogger(__name__)

TES_WRAPPER_SCRIPT = "tes_job_wrapper.sh"
# Job directory files at most this large are searched for tool directory paths.
MAX_SCANNED_FILE_SIZE = 1024 * 1024
# Tool directories with at most this many files, test data excluded, are staged whole, so a
# tool script finds the modules and data next to it. Larger ones stage only referenced files.
MAX_TOOL_DIRECTORY_FILES = 200
UrlFor = Callable[[str, JobFilesScope], str]
# Run by find with the job directory as $0 and symlinks as arguments: a link to a file
# in the job directory becomes a copy of it, any other link is removed.
REPLACE_LINKS = (
    'for l; do t=$(readlink -f "$l") || t=; case "$t" in "$0"/*) '
    'if [ -f "$t" ] && cp "$t" "$l.galaxy_copy" && mv -f "$l.galaxy_copy" "$l"; then continue; fi;; esac; '
    'rm -f "$l" "$l.galaxy_copy"; done'
)


def job_files_url(galaxy_url: str, encoded_job_id: str, path: str, job_token: str) -> str:
    """URL of ``path`` in Galaxy's job files API, authorized by ``job_token``."""
    query = urlencode({"path": path, "job_token": job_token})
    return f"{galaxy_url.rstrip('/')}/api/jobs/{encoded_job_id}/files?{query}"


def signed_job_files_url_for(galaxy_url: str, security: "IdEncodingHelper", job_id: int, expires: int) -> UrlFor:
    """A ``UrlFor`` whose URLs each carry a token for one path and one direction, valid until ``expires``."""
    encoded_job_id = security.encode_id(job_id)

    def url_for(path: str, scope: JobFilesScope) -> str:
        return job_files_url(galaxy_url, encoded_job_id, path, job_files_token(security, job_id, path, scope, expires))

    return url_for


def expand_paths(paths: Iterable[str]) -> list[str]:
    """Files at ``paths``, with directories walked into their files. Missing paths are skipped."""
    files: list[str] = []
    for path in paths:
        if os.path.isdir(path):
            for root, _, names in os.walk(path):
                files.extend(os.path.join(root, name) for name in sorted(names))
        elif os.path.isfile(path):
            files.append(path)
        else:
            log.debug("Not staging missing input path %s", path)
    return files


def directory_output_paths(job_directory: str, extra_files_paths: Iterable[str]) -> list[str]:
    """Directories the task sends back whole: the tool working directory and the outputs' extra files directories."""
    paths: dict[str, None] = {os.path.join(job_directory, "working"): None}
    for path in extra_files_paths:
        if not in_directory(path, job_directory):
            raise Exception(f"Job output {path} is outside the job directory, which the TES runner can't stage.")
        paths[os.path.abspath(path)] = None
    return list(paths)


def referenced_tool_files(tool_directory: str | None, texts: Iterable[str]) -> list[str]:
    """Files under ``tool_directory`` named in ``texts`` (job script, tool script, config files)."""
    if not tool_directory:
        return []
    tool_directory = os.path.abspath(tool_directory)
    pattern = re.compile(re.escape(tool_directory) + r"/[^\s'\"`<>|;&()]+")
    referenced = {match.rstrip(".,") for text in texts for match in pattern.findall(text)}
    return [path for path in expand_paths(sorted(referenced)) if in_directory(path, tool_directory)]


def tool_directory_files(tool_directory: str | None) -> list[str]:
    """Every file under ``tool_directory`` outside ``test-data`` and hidden directories, or none if there are too many."""
    if not tool_directory:
        return []
    files: list[str] = []
    for root, dirs, names in os.walk(tool_directory):
        dirs[:] = sorted(name for name in dirs if name != "test-data" and not name.startswith("."))
        files.extend(os.path.join(root, name) for name in sorted(names))
        if len(files) > MAX_TOOL_DIRECTORY_FILES:
            log.debug("Tool directory %s is too large to stage whole, staging the files the job names", tool_directory)
            return []
    return files


def staged_input_paths(
    job_directory: str,
    input_paths: Iterable[str],
    tool_directory: str | None,
    exclude: Iterable[str] = (),
) -> list[str]:
    """Every file the job may read, as absolute paths on Galaxy's disk, without duplicates."""
    excluded = {os.path.abspath(path) for path in exclude}
    job_files = [path for path in expand_paths([job_directory]) if os.path.abspath(path) not in excluded]
    staged: dict[str, None] = {}
    tool_files = [
        *referenced_tool_files(tool_directory, _scanned_texts(job_files)),
        *tool_directory_files(tool_directory),
    ]
    for path in [*expand_paths(input_paths), *job_files, *tool_files]:
        staged[os.path.abspath(path)] = None
    return list(staged)


def _scanned_texts(paths: Iterable[str]) -> Iterator[str]:
    """Contents of each file at ``paths`` no larger than ``MAX_SCANNED_FILE_SIZE``, read one at a time."""
    for path in paths:
        if os.path.getsize(path) <= MAX_SCANNED_FILE_SIZE:
            with open(path, errors="replace") as fh:
                yield fh.read()


def wrapper_script(
    job_directory: str,
    job_script: str,
    exit_code_file: str,
    stdout_file: str,
    stderr_file: str,
    outputs: Iterable[str],
    precreated: Iterable[str] = (),
    directories: Iterable[str] = (),
) -> str:
    """The executor's script: run Galaxy's job script, keep its exit code in a file, exit 0.

    ``precreated`` are the empty output files Galaxy created on its disk while
    preparing the job; they are created in the task too, because the job script's
    ``from_work_dir`` copies only write to outputs that exist.

    TESK and tesp-api skip stage-out after a failed executor, so the script always
    exits 0 and Galaxy reads the tool's exit code from the uploaded file. Funnel and
    TESK fail a task whose FILE output is missing, so every declared output is
    created, empty, after the job script if the job didn't write it.

    ``directories`` (TES ``DIRECTORY`` outputs) are created before the job script
    and lose their symlinks after it: TESK refuses a directory output with any
    symlink in it, and Funnel one whose links leave the task. A link to a file
    in the job directory is replaced by a copy of that file, so its contents
    still go back; any other link is removed.
    """
    q = shlex.quote
    directories = list(directories)
    lines = [
        "#!/bin/sh",
        "# Written by Galaxy's TES runner. Runs Galaxy's job script, then always exits 0.",
        f"cd {q(job_directory)} || exit 0",
        # TES creates no empty directories; the job script creates working, outputs and configs itself.
        "mkdir -p home tmp metadata",
        *([f"mkdir -p {' '.join(q(d) for d in directories)}"] if directories else []),
        *_touch_loop(precreated),
        f"/bin/bash {q(job_script)} > {q(stdout_file)} 2> {q(stderr_file)}",
        "rc=$?",
        f"[ -s {q(exit_code_file)} ] || echo $rc > {q(exit_code_file)}",
        *_touch_loop(outputs),
        *(
            [
                f"find {' '.join(q(d) for d in directories)} -type l -exec sh -c {q(REPLACE_LINKS)} {q(job_directory)} {{}} +"
            ]
            if directories
            else []
        ),
        "exit 0",
        "",
    ]
    return "\n".join(lines)


def _touch_loop(paths: Iterable[str]) -> list[str]:
    """Shell lines that create each of ``paths`` as an empty file unless it exists."""
    quoted = [shlex.quote(path) for path in paths]
    if not quoted:
        return []
    return [
        "for f in \\",
        *(f"    {path} \\" for path in quoted),
        "    ; do",
        '    [ -e "$f" ] || { mkdir -p "$(dirname "$f")" && : > "$f"; }',
        "done",
    ]


def build_tes_task(
    name: str,
    image: str,
    job_directory: str,
    input_paths: Iterable[str],
    output_paths: Iterable[str],
    wrapper: str,
    url_for: UrlFor,
    resources: TesResources | None = None,
    env: dict[str, str] | None = None,
    directory_paths: Iterable[str] = (),
) -> TesTask:
    """A TES task that stages ``input_paths`` in, runs ``wrapper`` in ``image`` and stages ``output_paths`` out.

    Every path is the same inside the task as on Galaxy's disk.
    """
    wrapper_path = os.path.join(job_directory, TES_WRAPPER_SCRIPT)
    inputs = [TesInput(url=url_for(path, JOB_FILES_READ), path=path, type=TesFileType.FILE) for path in input_paths]
    inputs.append(TesInput(content=wrapper, path=wrapper_path, type=TesFileType.FILE))
    outputs = [TesOutput(url=url_for(path, JOB_FILES_WRITE), path=path, type=TesFileType.FILE) for path in output_paths]
    outputs.extend(
        TesOutput(url=url_for(path, JOB_FILES_DIRECTORY_WRITE), path=path, type=TesFileType.DIRECTORY)
        for path in directory_paths
    )
    executor = TesExecutor(image=image, command=["/bin/sh", wrapper_path], workdir=job_directory, env=env or None)
    return TesTask(
        name=name,
        inputs=inputs,
        outputs=outputs,
        executors=[executor],
        # Shared by the executor and stage-out, writable; inputs land inside it.
        volumes=[job_directory],
        resources=resources,
    )


def executor_env(resources: TesResources) -> dict[str, str]:
    """``GALAXY_SLOTS`` and ``GALAXY_MEMORY_MB`` for the job script, from the TES resources."""
    env = {}
    if resources.cpu_cores:
        env["GALAXY_SLOTS"] = str(resources.cpu_cores)
    if resources.ram_gb:
        env["GALAXY_MEMORY_MB"] = str(int(resources.ram_gb * 1024))
    return env
