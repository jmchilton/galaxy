import json
import shutil
import tarfile
from pathlib import Path
from unittest import mock

import pytest

from galaxy.exceptions import (
    InternalServerError,
    MalformedContents,
)
from tool_shed.context import ProvidesRepositoriesContext
from tool_shed.managers.repositories import upload_tar_dry_run
from tool_shed.repository_types import util as rt_util
from tool_shed.util import shed_util_common
from tool_shed.webapp.model import (
    Repository,
    User,
)
from tool_shed_client.schema import RepositoryUpdateDryRun
from ._util import (
    metadata_rows,
    random_name,
    repository_fixture,
    revision_path,
    tar_path,
    TEST_COMMIT_MESSAGE,
    TEST_DATA_FILES,
    upload,
)

TOOL_DEPENDENCIES_XML = """<?xml version="1.0"?>
<tool_dependency>
    <package name="samtools" version="{version}">
        <install version="1.0">
            <actions>
                <action type="shell_command">true</action>
            </actions>
        </install>
    </package>
</tool_dependency>
"""


def _upload_revision(
    provides_repositories: ProvidesRepositoriesContext, repository: Repository, test_data_path: str, revision: str
):
    return upload(provides_repositories, repository, revision_path(test_data_path, revision), arcname=test_data_path)


def _dry_run_revision(
    provides_repositories: ProvidesRepositoriesContext, repository: Repository, test_data_path: str, revision: str
) -> RepositoryUpdateDryRun:
    path = tar_path(revision_path(test_data_path, revision), test_data_path)
    return upload_tar_dry_run(provides_repositories, repository, path, TEST_COMMIT_MESSAGE)


def _persisted_rows(provides_repositories: ProvidesRepositoriesContext, repository: Repository) -> list[tuple]:
    session = provides_repositories.app.model.session
    session.commit()
    session.expire_all()
    return sorted(
        (rm.id, str(rm.changeset_revision), rm.downloadable, json.dumps(rm.metadata, sort_keys=True))
        for rm in repository.metadata_revisions
    )


def test_bumped_tool_version_creates_new_installable_revision(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository
):
    _upload_revision(provides_repositories, new_repository, "column_maker", "1")
    first_tip = new_repository.tip()
    _upload_revision(provides_repositories, new_repository, "column_maker", "2")
    assert metadata_rows(new_repository) == {
        first_tip: [("Add_a_column1", "1.1.0")],
        new_repository.tip(): [("Add_a_column1", "1.2.0")],
    }


def test_new_tool_id_creates_new_installable_revision(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository
):
    _upload_revision(provides_repositories, new_repository, "column_maker_subset", "1")
    first_tip = new_repository.tip()
    _upload_revision(provides_repositories, new_repository, "column_maker_subset", "2")
    rows = metadata_rows(new_repository)
    assert set(rows) == {first_tip, new_repository.tip()}
    assert len(rows[new_repository.tip()]) == 2


def test_unchanged_tool_version_overwrites_latest_installable_revision(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository
):
    _upload_revision(provides_repositories, new_repository, "column_maker_unchanged", "1")
    first_tip = new_repository.tip()
    _upload_revision(provides_repositories, new_repository, "column_maker_unchanged", "2")
    assert new_repository.tip() != first_tip
    assert metadata_rows(new_repository) == {new_repository.tip(): [("Add_a_column1", "1.0.0")]}


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


@pytest.mark.parametrize(
    "test_data_path,creates_new_revision",
    [("column_maker", True), ("column_maker_subset", True), ("column_maker_unchanged", False)],
)
def test_dry_run_predicts_upload_and_changes_nothing(
    provides_repositories: ProvidesRepositoriesContext,
    new_repository: Repository,
    test_data_path: str,
    creates_new_revision: bool,
):
    _upload_revision(provides_repositories, new_repository, test_data_path, "1")
    first_tip = new_repository.tip()
    rows_before = _persisted_rows(provides_repositories, new_repository)

    dry_run = _dry_run_revision(provides_repositories, new_repository, test_data_path, "2")

    assert new_repository.tip() == first_tip
    assert _persisted_rows(provides_repositories, new_repository) == rows_before
    assert not dry_run.no_changes
    assert dry_run.creates_new_installable_revision is creates_new_revision
    assert dry_run.overwrites_changeset_revision == (None if creates_new_revision else first_tip)

    _upload_revision(provides_repositories, new_repository, test_data_path, "2")
    rows_after = metadata_rows(new_repository)
    assert (len(rows_after) == 2) is creates_new_revision
    assert sorted((t.id, t.new_version) for t in dry_run.tools) == rows_after[new_repository.tip()]
    (tip_row,) = (rm for rm in new_repository.metadata_revisions if rm.changeset_revision == new_repository.tip())
    assert dry_run.installable is tip_row.downloadable is True


def test_dry_run_rejects_invalid_archive(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository
):
    path = str(TEST_DATA_FILES.joinpath("safetar_with_symlink.tar"))
    with pytest.raises(InternalServerError, match="Invalid paths"):
        upload_tar_dry_run(provides_repositories, new_repository, path, TEST_COMMIT_MESSAGE)


def test_dry_run_removes_temporary_files(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository, isolated_tempdir: Path
):
    _upload_revision(provides_repositories, new_repository, "column_maker", "1")
    path = tar_path(revision_path("column_maker", "2"), "column_maker")
    before = set(isolated_tempdir.iterdir())
    upload_tar_dry_run(provides_repositories, new_repository, path, TEST_COMMIT_MESSAGE)
    assert set(isolated_tempdir.iterdir()) == before


def test_dry_run_predicts_tip_only_repository_upload(
    provides_repositories: ProvidesRepositoriesContext, new_user: User, tmp_path: Path
):
    shed_app = provides_repositories.app
    repository = repository_fixture(shed_app, new_user, random_name(), type=rt_util.TOOL_DEPENDENCY_DEFINITION)

    def tool_dependencies_tar(version: str) -> str:
        definition = tmp_path / version / "tool_dependencies.xml"
        definition.parent.mkdir(exist_ok=True)
        definition.write_text(TOOL_DEPENDENCIES_XML.format(version=version))
        path = tmp_path / f"{version}.tar"
        with tarfile.open(path, "w") as tar:
            tar.add(definition, arcname="tool_dependencies.xml")
        return str(path)

    first = upload_tar_dry_run(provides_repositories, repository, tool_dependencies_tar("0.1.18"), TEST_COMMIT_MESSAGE)
    assert first.creates_new_installable_revision is True
    assert first.overwrites_changeset_revision is None
    upload(provides_repositories, repository, Path(tool_dependencies_tar("0.1.18")))
    first_tip = repository.tip()
    assert list(metadata_rows(repository)) == [first_tip]

    second = upload_tar_dry_run(provides_repositories, repository, tool_dependencies_tar("0.1.19"), TEST_COMMIT_MESSAGE)
    assert second.creates_new_installable_revision is False
    assert second.overwrites_changeset_revision == first_tip
    upload(provides_repositories, repository, Path(tool_dependencies_tar("0.1.19")))
    assert list(metadata_rows(repository)) == [repository.tip()]


def test_dry_run_reports_metadata_errors_with_its_plan(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository
):
    dry_run = _dry_run_revision(provides_repositories, new_repository, "bismark", "0")
    assert dry_run.ok is False
    assert "bowtie_indices.loc" in dry_run.message
    assert new_repository.tip() not in dry_run.message
    assert dry_run.creates_new_installable_revision is True
    with pytest.raises(InternalServerError, match="bowtie_indices.loc"):
        _upload_revision(provides_repositories, new_repository, "bismark", "0")
    (tools,) = metadata_rows(new_repository).values()
    assert sorted((t.id, t.new_version) for t in dry_run.tools) == tools


def test_dry_run_leaves_app_tool_data_tables_alone(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository
):
    tool_data_tables = provides_repositories.app.tool_data_tables
    tables_before = set(tool_data_tables.data_tables)
    _dry_run_revision(provides_repositories, new_repository, "bismark", "0")
    assert set(tool_data_tables.data_tables) == tables_before
    with pytest.raises(InternalServerError):
        _upload_revision(provides_repositories, new_repository, "bismark", "0")
    assert set(tool_data_tables.data_tables) - tables_before == {"bowtie_indexes", "bowtie2_indexes"}


def test_dry_run_reads_uploaded_sample_files(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository, tmp_path: Path
):
    with pytest.raises(InternalServerError, match="bowtie2_indices.loc"):
        _upload_revision(provides_repositories, new_repository, "bismark", "1")
    revision = tmp_path / "bismark"
    shutil.copytree(revision_path("bismark", "1"), revision)
    (revision / "tool_data_table_conf.xml.sample").write_text("<tables>\n</tables>\n")

    dry_run = upload_tar_dry_run(
        provides_repositories, new_repository, tar_path(revision, "bismark"), TEST_COMMIT_MESSAGE
    )

    assert dry_run.ok, dry_run.message
    upload(provides_repositories, new_repository, revision)
    tools = metadata_rows(new_repository)[new_repository.tip()]
    assert sorted((t.id, t.new_version) for t in dry_run.tools) == tools


def test_dry_run_ignores_tools_shipped_only_as_samples(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository, tmp_path: Path
):
    revision = tmp_path / "sample_tool"
    revision.mkdir()
    shutil.copy(revision_path("column_maker", "1") / "column_maker.xml", revision / "column_maker.xml.sample")
    dry_run = upload_tar_dry_run(
        provides_repositories, new_repository, tar_path(revision, "sample_tool"), TEST_COMMIT_MESSAGE
    )
    assert dry_run.tools == []
    assert dry_run.installable is False
    assert dry_run.creates_new_installable_revision is False
    upload(provides_repositories, new_repository, revision, arcname="sample_tool")
    assert list(metadata_rows(new_repository).values()) == [[]]
    assert [rm.downloadable for rm in new_repository.metadata_revisions] == [False]


def test_dry_run_reports_overwrite_that_is_no_longer_installable(
    provides_repositories: ProvidesRepositoriesContext, new_repository: Repository, tmp_path: Path
):
    _upload_revision(provides_repositories, new_repository, "column_maker", "1")
    first_tip = new_repository.tip()
    revision = tmp_path / "column_maker"
    revision.mkdir()
    shutil.copy(revision_path("column_maker", "1") / "column_maker.xml", revision / "column_maker.xml.sample")
    dry_run = upload_tar_dry_run(
        provides_repositories, new_repository, tar_path(revision, "column_maker"), TEST_COMMIT_MESSAGE
    )
    assert dry_run.installable is False
    assert dry_run.creates_new_installable_revision is False
    assert dry_run.overwrites_changeset_revision == first_tip
    upload(provides_repositories, new_repository, revision, arcname="column_maker")
    assert [(rm.changeset_revision, rm.downloadable) for rm in new_repository.metadata_revisions] == [
        (new_repository.tip(), False)
    ]
