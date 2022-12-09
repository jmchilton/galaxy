import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from time import gmtime
from typing import List

from galaxy.tool_shed.util import basic_util
from galaxy.tool_shed.util.hg_util import (
    clone_repository,
    copy_file_from_manifest,
    get_changectx_for_changeset,
    get_config_from_disk,
    get_ctx_file_path_from_manifest,
    get_file_context_from_ctx,
    pull_repository,
    reversed_lower_upper_bounded_changelog,
    reversed_upper_bounded_changelog,
    update_repository,
)
from galaxy.util import unicodify

log = logging.getLogger(__name__)

INITIAL_CHANGELOG_HASH = "000000000000"


def debug_hg_diff(cwd: str) -> str:
    return _hg_execute(["diff"], cwd)


def _debug_hg_status(cwd: str) -> str:
    try:
        return _hg_execute_raw(["status"], cwd)
    except subprocess.CalledProcessError as cpe:
        return f"*Failed to execute hg status - output was {unicodify(cpe.output)}"
    except Exception as e:
        return f"*Failed to execute hg status - exception was ({e})"


def _debug_hg_log(cwd: str) -> str:
    try:
        return _hg_execute_raw(["log"], cwd)
    except subprocess.CalledProcessError as cpe:
        return f"*Failed to execute hg log - output was {unicodify(cpe.output)}"
    except Exception as e:
        return f"*Failed to execute hg status - exception was ({e})"


class HgExecutionException(Exception):
    def __init__(self, command: List[str], return_code: int, output: str, status_output: str, log_output: str):
        self.command = command
        self.output = output
        self.status_output = status_output
        self.log_output = log_output
        self.return_code = return_code
        log.warning(f"Raising hg execution exception {self.message}")

    @property
    def nothing_changed_error(self) -> bool:
        return self.return_code == 1 and "nothing changed" in self.output

    @property
    def message(self) -> str:
        return f"mercurial command [{self.command}] failed with return code [{self.return_code}]. output was [{self.output}], hg status is [{self.status_output}], hg log is [{self.log_output}]"


def _hg_execute_raw(args: List[str], cwd: str) -> str:
    hg_cmd = ["hg", "--verbose", *args]
    return unicodify(subprocess.check_output(hg_cmd, stderr=subprocess.STDOUT, cwd=cwd))


def _hg_execute(args: List[str], cwd: str):
    try:
        return _hg_execute_raw(args, cwd)
    except subprocess.CalledProcessError as e:
        raise HgExecutionException(
            ["hg", "--verbose", *args],
            e.returncode,
            unicodify(e.output),
            status_output=_debug_hg_status(cwd),
            log_output=_debug_hg_log(cwd),
        )


def add_changeset(repo_path, path_to_filename_in_archive):
    _hg_execute(["add", path_to_filename_in_archive], repo_path)


def archive_repository_revision(app, repository, archive_dir, changeset_revision):
    """Create an un-versioned archive of a repository."""
    repo_path = repository.repo_path(app)
    _hg_execute(["archive", "-r", str(changeset_revision), archive_dir], repo_path)


def commit_changeset(repo_path, full_path_to_changeset, username, message):
    try:
        log.info(f"about to commit with hg status [{_debug_hg_status(repo_path)}]")
        _hg_execute(["commit", "-u", username, "-m", message, full_path_to_changeset], repo_path)
    except HgExecutionException as e:
        if e.nothing_changed_error:
            return


def get_hgrc_path(repo_path):
    return os.path.join(repo_path, ".hg", "hgrc")


def create_hgrc_file(app, repository):
    # Since we support both http and https, we set `push_ssl` to False to
    # override the default (which is True) in the Mercurial API.
    # The hg purge extension purges all files and directories not being tracked
    # by Mercurial in the current repository. It will remove unknown files and
    # empty directories. This is not currently used because it is not supported
    # in the Mercurial API.
    repo_path = repository.repo_path(app)
    hgrc_path = get_hgrc_path(repo_path)
    with open(hgrc_path, "w") as fp:
        fp.write("[paths]\n")
        fp.write("default = .\n")
        fp.write("default-push = .\n")
        fp.write("[web]\n")
        fp.write(f"allow_push = {repository.user.username}\n")
        fp.write(f"name = {repository.name}\n")
        fp.write("push_ssl = false\n")
        fp.write("[extensions]\n")
        fp.write("hgext.purge=")


def get_named_tmpfile_from_ctx(ctx, filename, dir):
    """
    Return a named temporary file created from a specified file with a given name included in a repository
    changeset revision.
    """
    filename = basic_util.strip_path(filename)
    for ctx_file in ctx.files():
        ctx_file_name = basic_util.strip_path(unicodify(ctx_file))
        if filename == ctx_file_name:
            try:
                # If the file was moved, its destination file contents will be returned here.
                fctx = ctx[ctx_file]
            except LookupError:
                # Continue looking in case the file was moved.
                fctx = None
                continue
            if fctx:
                fh = tempfile.NamedTemporaryFile("wb", prefix="tmp-toolshed-gntfc", dir=dir)
                tmp_filename = fh.name
                fh.close()
                fh = open(tmp_filename, "wb")
                fh.write(fctx.data())
                fh.close()
                return tmp_filename
    return None


def get_readable_ctx_date(ctx):
    """Convert the date of the changeset (the received ctx) to a human-readable date."""
    t, tz = ctx.date()
    date = datetime(*gmtime(float(t) - tz)[:6])
    ctx_date = date.strftime("%Y-%m-%d")
    return ctx_date


def get_repository_heads(repo):
    """Return current repository heads, which are changesets with no child changesets."""
    heads = [repo[h] for h in repo.heads(None)]
    return heads


def get_reversed_changelog_changesets(repo):
    """Return a list of changesets in reverse order from that provided by the repository manifest."""
    reversed_changelog = []
    for changeset in repo.changelog:
        reversed_changelog.insert(0, changeset)
    return reversed_changelog


def get_revision_label(app, repository, changeset_revision, include_date=True, include_hash=True):
    """
    Return a string consisting of the human readable changeset rev and the changeset revision string
    which includes the revision date if the receive include_date is True.
    """
    repo = repository.hg_repo
    ctx = get_changectx_for_changeset(repo, changeset_revision)
    if ctx:
        return get_revision_label_from_ctx(ctx, include_date=include_date, include_hash=include_hash)
    else:
        if include_hash:
            return f"-1:{changeset_revision}"
        else:
            return "-1"


def get_rev_label_changeset_revision_from_repository_metadata(
    app, repository_metadata, repository=None, include_date=True, include_hash=True
):
    if repository is None:
        repository = repository_metadata.repository
    repo = repository.hg_repo
    changeset_revision = repository_metadata.changeset_revision
    ctx = get_changectx_for_changeset(repo, changeset_revision)
    if ctx:
        rev = "%04d" % ctx.rev()
        if include_date:
            changeset_revision_date = get_readable_ctx_date(ctx)
            if include_hash:
                label = f"{ctx.rev()}:{changeset_revision} ({changeset_revision_date})"
            else:
                label = f"{ctx.rev()} ({changeset_revision_date})"
        else:
            if include_hash:
                label = f"{ctx.rev()}:{changeset_revision}"
            else:
                label = f"{ctx.rev()}"
    else:
        rev = "-1"
        if include_hash:
            label = f"-1:{changeset_revision}"
        else:
            label = "-1"
    return rev, label, changeset_revision


def get_revision_label_from_ctx(ctx, include_date=True, include_hash=True):
    if include_date:
        if include_hash:
            return f'{ctx.rev()}:{ctx} <i><font color="#666666">({get_readable_ctx_date(ctx)})</font></i>'
        else:
            return f'{ctx.rev()} <i><font color="#666666">({get_readable_ctx_date(ctx)})</font></i>'
    else:
        if include_hash:
            return f"{ctx.rev()}:{ctx}"
        else:
            return str(ctx.rev())


def get_rev_label_from_changeset_revision(repo, changeset_revision, include_date=True, include_hash=True):
    """
    Given a changeset revision hash, return two strings, the changeset rev and the changeset revision hash
    which includes the revision date if the receive include_date is True.
    """
    ctx = get_changectx_for_changeset(repo, changeset_revision)
    if ctx:
        rev = "%04d" % ctx.rev()
        label = get_revision_label_from_ctx(ctx, include_date=include_date)
    else:
        rev = "-1"
        label = f"-1:{changeset_revision}"
    return rev, label


def remove_path(repo_path, selected_file):
    cmd = ["hg", "remove", "--force", selected_file]
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT, cwd=repo_path)
    except Exception as e:
        error_message = f"Error removing path '{selected_file}': {unicodify(e)}"
        if isinstance(e, subprocess.CalledProcessError):
            output = unicodify(e.output)
            if "is untracked" in output:
                # That's ok, happens if we add a new file or directory via tarball upload,
                # just delete the file or dir on disk
                selected_file_path = os.path.join(repo_path, selected_file)
                if os.path.isdir(selected_file_path):
                    shutil.rmtree(selected_file_path)
                else:
                    os.remove(selected_file_path)
                return
            error_message += f"\nOutput was:\n{output}"
        raise Exception(error_message)


def init_repository(repo_path):
    """
    Create a new Mercurial repository in the given directory.
    """
    _hg_execute(["init"], repo_path)


def changeset2rev(repo_path, changeset_revision):
    """
    Return the revision number (as an int) corresponding to a specified changeset revision.
    """
    rev = _hg_execute(["id", "-r", changeset_revision, "-n"], repo_path)
    return int(rev.strip())


__all__ = (
    "add_changeset",
    "archive_repository_revision",
    "clone_repository",
    "commit_changeset",
    "copy_file_from_manifest",
    "create_hgrc_file",
    "get_changectx_for_changeset",
    "get_config_from_disk",
    "get_ctx_file_path_from_manifest",
    "get_file_context_from_ctx",
    "get_named_tmpfile_from_ctx",
    "get_readable_ctx_date",
    "get_repository_heads",
    "get_reversed_changelog_changesets",
    "get_revision_label",
    "get_rev_label_changeset_revision_from_repository_metadata",
    "get_revision_label_from_ctx",
    "get_rev_label_from_changeset_revision",
    "pull_repository",
    "remove_path",
    "reversed_lower_upper_bounded_changelog",
    "reversed_upper_bounded_changelog",
    "update_repository",
    "init_repository",
    "changeset2rev",
)
