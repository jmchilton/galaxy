from pathlib import Path
from unittest import mock

import pytest

from galaxy.exceptions import MalformedContents
from tool_shed.context import ProvidesRepositoriesContext
from tool_shed.util import shed_util_common
from tool_shed.webapp.model import Repository
from ._util import (
    TEST_DATA_FILES,
    upload,
)


def _upload_revision(
    provides_repositories: ProvidesRepositoriesContext, repository: Repository, test_data_path: str, revision: str
):
    path = Path(str(TEST_DATA_FILES.joinpath(f"repos/{test_data_path}/{revision}")))
    return upload(provides_repositories, repository, path, arcname=test_data_path)


def _metadata_rows(repository: Repository) -> dict[str, list[tuple[str, str]]]:
    return {
        str(rm.changeset_revision): sorted((t["id"], t["version"]) for t in (rm.metadata or {}).get("tools", []))
        for rm in repository.metadata_revisions
    }


def test_bumped_tool_version_creates_new_installable_revision(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository
):
    _upload_revision(provides_repositories, new_repository, "column_maker", "1")
    first_tip = new_repository.tip()
    _upload_revision(provides_repositories, new_repository, "column_maker", "2")
    assert _metadata_rows(new_repository) == {
        first_tip: [("Add_a_column1", "1.1.0")],
        new_repository.tip(): [("Add_a_column1", "1.2.0")],
    }


def test_new_tool_id_creates_new_installable_revision(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository
):
    _upload_revision(provides_repositories, new_repository, "column_maker_subset", "1")
    first_tip = new_repository.tip()
    _upload_revision(provides_repositories, new_repository, "column_maker_subset", "2")
    rows = _metadata_rows(new_repository)
    assert set(rows) == {first_tip, new_repository.tip()}
    assert len(rows[new_repository.tip()]) == 2


def test_unchanged_tool_version_overwrites_latest_installable_revision(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository
):
    _upload_revision(provides_repositories, new_repository, "column_maker_unchanged", "1")
    first_tip = new_repository.tip()
    _upload_revision(provides_repositories, new_repository, "column_maker_unchanged", "2")
    assert new_repository.tip() != first_tip
    assert _metadata_rows(new_repository) == {new_repository.tip(): [("Add_a_column1", "1.0.0")]}


def test_identical_upload_reports_no_changes(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository
):
    _upload_revision(provides_repositories, new_repository, "column_maker", "1")
    with pytest.raises(MalformedContents, match="No changes to repository"):
        _upload_revision(provides_repositories, new_repository, "column_maker", "1")


def test_first_upload_sends_upload_and_new_repository_alerts(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository
):
    with mock.patch.object(shed_util_common, "handle_email_alerts") as handle_email_alerts:
        _upload_revision(provides_repositories, new_repository, "column_maker", "1")
    assert [c.kwargs["new_repo_alert"] for c in handle_email_alerts.call_args_list] == [False, True]
