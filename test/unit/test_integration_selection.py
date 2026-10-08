"""Exercise CI selection through real Git comparisons and pytest execution."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))

from integration.integration_selection import (
    FAMILIES,
    SELECTION_ENV,
)

SCRIPT = ROOT / "scripts/select_integration_tests.py"


def run(*args, cwd, env=None):
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repository(tmp_path):
    run("git", "init", "-q", cwd=tmp_path)
    run("git", "config", "user.email", "ci-test@example.org", cwd=tmp_path)
    run("git", "config", "user.name", "CI Test", cwd=tmp_path)
    return tmp_path


def commit(repository, path, content="change"):
    file = repository / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content)
    run("git", "add", "-A", cwd=repository)
    run("git", "commit", "-qm", "test change", cwd=repository)
    return run("git", "rev-parse", "HEAD", cwd=repository).strip()


def select(repository, event_name, event, *, python_flags=()):
    event_path = repository / "event.json"
    env_path = repository / "selection.env"
    event_path.write_text(json.dumps(event))
    env_path.unlink(missing_ok=True)
    output = run(
        sys.executable,
        *python_flags,
        str(SCRIPT),
        "--event-name",
        event_name,
        "--event-path",
        str(event_path),
        "--env-file",
        str(env_path),
        cwd=repository,
    )
    environment = dict(line.split("=", 1) for line in env_path.read_text().splitlines())
    return environment, output


def families(environment):
    return set(json.loads(environment[SELECTION_ENV])["families"])


def test_pr_uses_merge_base_and_all_branch_commits(repository):
    ancestor = commit(repository, "README.md")
    run("git", "checkout", "-qb", "feature", cwd=repository)
    commit(repository, "lib/galaxy/jobs/runners/condor.py")
    head = commit(repository, "lib/galaxy/objectstore/azure_blob.py")
    run("git", "checkout", "-qb", "base", ancestor, cwd=repository)
    base = commit(repository, "lib/galaxy/util/__init__.py")
    environment, output = select(
        repository, "pull_request", {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
    )
    assert families(environment) == {"htcondor", "azure"}
    assert environment["GALAXY_TEST_CI_UTILS_CHANGED"] == "0"
    assert "2 changed paths" in output


def test_push_range_tracks_renamed_and_deleted_paths(repository):
    commit(repository, "lib/galaxy/jobs/runners/pulsar.py")
    base = commit(repository, "lib/galaxy/objectstore/s3_boto3.py")
    run("git", "mv", "lib/galaxy/jobs/runners/pulsar.py", "old_pulsar.py", cwd=repository)
    run("git", "rm", "lib/galaxy/objectstore/s3_boto3.py", cwd=repository)
    head = commit(repository, "doc/new-file.txt")
    environment, output = select(repository, "push", {"before": base, "after": head})
    assert families(environment) == {"pulsar", "s3"}
    assert "4 changed paths" in output


@pytest.mark.parametrize(
    "path, expected, flag",
    [
        ("lib/galaxy/util/path/__init__.py", FAMILIES, "GALAXY_TEST_CI_UTILS_CHANGED"),
        ("lib/galaxy/jobs/handler.py", FAMILIES, "GALAXY_TEST_CI_JOBS_PLUMBING_CHANGED"),
        ("lib/galaxy/objectstore/_caching_base.py", FAMILIES, "GALAXY_TEST_CI_OBJECTSTORE_PLUMBING_CHANGED"),
        ("lib/galaxy/model/__init__.py", FAMILIES, None),
        ("pyproject.toml", FAMILIES, None),
        ("lib/galaxy/dependencies/pinned-requirements.txt", FAMILIES, None),
        ("lib/galaxy/job_metrics/__init__.py", FAMILIES, None),
        ("lib/galaxy/webapps/galaxy/services/datasets.py", FAMILIES, None),
        ("lib/galaxy/managers/hdas.py", FAMILIES, None),
        ("lib/galaxy/webapps/galaxy/api/tools.py", FAMILIES, None),
        ("lib/galaxy/files/sources/__init__.py", FAMILIES, None),
        ("lib/galaxy/webapps/base/api.py", FAMILIES, None),
        ("lib/galaxy/objectstore/s3.py", {"s3", "cloud"}, None),
        ("lib/galaxy/objectstore/s3_multipart_upload.py", {"s3", "cloud"}, None),
        ("test/integration/conftest.py", FAMILIES, None),
        (".github/workflows/integration.yaml", FAMILIES, None),
        ("test/integration/objectstore/test_swift_objectstore.py", {"s3"}, None),
        ("test/integration/test_containerized_jobs.py", {"containers", "kubernetes", "pulsar"}, None),
        ("lib/galaxy/webapps/galaxy/api/histories.py", set(), None),
    ],
)
def test_push_policy_through_git(repository, path, expected, flag):
    base = commit(repository, "README.md")
    head = commit(repository, path)
    environment, _ = select(repository, "push", {"before": base, "after": head})
    assert families(environment) == expected
    if flag:
        assert environment[flag] == "1"


@pytest.mark.parametrize(
    "event_name, event",
    [
        ("push", {"before": "0" * 40, "after": "a" * 40}),
        ("push", {"before": "a" * 40, "after": "b" * 40}),
        ("pull_request", {}),
        ("schedule", {}),
        ("workflow_dispatch", {}),
        ("unknown", {}),
    ],
)
def test_comparison_failures_and_full_run_events(repository, event_name, event):
    commit(repository, "README.md")
    environment, _ = select(repository, event_name, event)
    assert families(environment) == FAMILIES


@pytest.fixture
def suite(tmp_path):
    directory = tmp_path / "test/integration"
    directory.mkdir(parents=True)
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers = ci_integration_family(family): expensive CI integration subsystem\n"
    )
    (tmp_path / "conftest.py").write_text(
        "from integration.integration_selection_pytest import pytest_collection_modifyitems\n"
        "from galaxy_test.shard import pytest_configure\n"
        "def pytest_addoption(parser):\n"
        "    parser.addoption('--num-shards', type=int, default=1)\n"
        "    parser.addoption('--shard-id', type=int, default=0)\n"
    )
    # Real unittest class setup and pytest fixtures record every expensive start.
    (directory / "test_kubernetes_runner.py").write_text(
        "import unittest\nfrom pathlib import Path\nimport pytest\n"
        "@pytest.mark.ci_integration_family('kubernetes')\n"
        "class TestKubernetesIntegration(unittest.TestCase):\n"
        "    @classmethod\n"
        "    def setUpClass(cls): Path('expensive-started').touch()\n"
        "    def test_run(self): pass\n"
        "class TestNewUnclassified(unittest.TestCase):\n"
        "    def test_run(self): Path('unclassified-ran').touch()\n"
    )
    (directory / "objectstore").mkdir()
    (directory / "objectstore/test_objectstore_datatype_upload.py").write_text(
        "import pytest\nfrom pathlib import Path\n"
        "@pytest.fixture\n"
        "def remote(): Path('remote-started').touch()\n"
        "@pytest.mark.ci_integration_family('irods')\n"
        "def test_upload_datatype_irods(remote): pass\n"
        "def test_upload_datatype_dos_disk_and_disk(): Path('disk-ran').touch()\n"
    )
    (directory / "test_general.py").write_text(
        "class TestGeneralA:\n    def test_run(self): pass\nclass TestGeneralB:\n    def test_run(self): pass\n"
    )
    durations = tmp_path / "durations.json"
    durations.write_text(json.dumps({"test_kubernetes_runner::TestKubernetesIntegration": 10000}))
    return tmp_path


def pytest_run(suite, environment, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GALAXY_TEST_CI_")}
    env.update(environment)
    env["PYTHONPATH"] = os.pathsep.join(str(ROOT / directory) for directory in ("test", "lib"))
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["GALAXY_TEST_SHARD_DURATIONS"] = str(suite / "durations.json")
    return run(sys.executable, "-m", "pytest", "-q", "-c", str(suite / "pytest.ini"), *args, cwd=suite, env=env)


def test_selection_prevents_setup_preserves_unclassified_and_disk(suite):
    output = pytest_run(suite, {SELECTION_ENV: json.dumps({"version": 1, "families": []})})
    assert "4 passed, 2 deselected" in output
    assert not (suite / "expensive-started").exists()
    assert not (suite / "remote-started").exists()
    assert (suite / "unclassified-ran").exists()
    assert (suite / "disk-ran").exists()


@pytest.mark.parametrize(
    "selection", [None, "not-json", "[]", "null", '{"version":2,"families":[]}', '{"version":1,"families":["unknown"]}']
)
def test_full_default_and_invalid_selection_run_setups(suite, selection):
    environment = {} if selection is None else {SELECTION_ENV: selection}
    output = pytest_run(suite, environment)
    assert "6 passed" in output
    assert (suite / "expensive-started").exists()
    assert (suite / "remote-started").exists()


def test_selected_plugin_runs_its_setup_only(suite):
    output = pytest_run(suite, {SELECTION_ENV: json.dumps({"version": 1, "families": ["kubernetes"]})})
    assert "5 passed, 1 deselected" in output
    assert (suite / "expensive-started").exists()
    assert not (suite / "remote-started").exists()


def test_sharding_packs_only_selected_groups(suite):
    environment = {SELECTION_ENV: json.dumps({"version": 1, "families": []})}
    for shard in range(2):
        output = pytest_run(suite, environment, "--num-shards=2", f"--shard-id={shard}")
        # Four equal-cost groups should balance 2/2. Sharding first would put
        # the costly excluded Kubernetes class alone on a shard (leaving it empty).
        assert "2 passed, 2 deselected" in output
    assert not (suite / "expensive-started").exists()
    assert not (suite / "remote-started").exists()


def test_module_generated_tests_and_inherited_class_dependencies(suite):
    path = suite / "test/integration/objectstore/test_direct_download_redirect.py"
    path.write_text(
        "import unittest\nfrom pathlib import Path\nimport pytest\n"
        "pytestmark = pytest.mark.ci_integration_family('s3')\n"
        "@pytest.mark.ci_integration_family('s3')\n"
        "class TestS3(unittest.TestCase):\n"
        "    @classmethod\n"
        "    def setUpClass(cls): Path(cls.__name__ + '-started').touch()\n"
        "    def test_run(self): pass\n"
        "@pytest.mark.ci_integration_family('cloud')\n"
        "class TestCloud(TestS3): pass\n"
        "@pytest.fixture\n"
        "def instance(): Path('generated-started').touch()\n"
        "def generated(instance): pass\n"
        "test_tools = generated\n"
    )
    output = pytest_run(suite, {SELECTION_ENV: json.dumps({"version": 1, "families": ["cloud"]})})
    assert "5 passed, 4 deselected" in output
    assert (suite / "TestCloud-started").exists()
    assert not (suite / "TestS3-started").exists()
    assert not (suite / "generated-started").exists()
    output = pytest_run(suite, {SELECTION_ENV: json.dumps({"version": 1, "families": ["s3"]})})
    assert "7 passed, 2 deselected" in output
    assert (suite / "TestS3-started").exists()
    assert (suite / "generated-started").exists()


@pytest.mark.parametrize("argument", ["['s3']", "'future-family'"])
def test_unrecognized_markers_remain_unconditional(suite, argument):
    path = suite / "test/integration/test_new_plugin.py"
    path.write_text(f"import pytest\n@pytest.mark.ci_integration_family({argument})\ndef test_new_plugin(): pass\n")
    output = pytest_run(suite, {SELECTION_ENV: json.dumps({"version": 1, "families": []})})
    assert "5 passed, 2 deselected" in output


def test_changed_paths_drive_pytest_setup_decisions(repository, suite):
    # Exercise the entire CLI -> GITHUB_ENV -> collection boundary with real Git.
    base = commit(repository, "README.md")
    head = commit(repository, "lib/galaxy/jobs/runners/kubernetes.py")
    environment, _ = select(repository, "push", {"before": base, "after": head})
    output = pytest_run(suite, environment)
    assert "5 passed, 1 deselected" in output
    assert (suite / "expensive-started").exists()
    assert not (suite / "remote-started").exists()
    assert (suite / "disk-ran").exists()


def test_pr_without_common_history_runs_full_suite(repository):
    base = commit(repository, "README.md")
    run("git", "checkout", "--orphan", "unrelated", cwd=repository)
    head = commit(repository, "doc/new-file.txt")
    environment, output = select(
        repository, "pull_request", {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
    )
    assert families(environment) == FAMILIES
    assert "could not determine changed paths" in output


@pytest.mark.parametrize("content", [None, "not-json"])
def test_missing_or_invalid_event_file_runs_full_suite(tmp_path, content):
    event_path = tmp_path / "event.json"
    env_path = tmp_path / "selection.env"
    if content is not None:
        event_path.write_text(content)
    output = run(
        sys.executable,
        str(SCRIPT),
        "--event-name",
        "pull_request",
        "--event-path",
        str(event_path),
        "--env-file",
        str(env_path),
        cwd=tmp_path,
    )
    environment = dict(line.split("=", 1) for line in env_path.read_text().splitlines())
    assert families(environment) == FAMILIES
    assert "event data unavailable" in output


def test_cli_reads_relocated_policy_without_site_packages(repository):
    base = commit(repository, "README.md")
    head = commit(repository, "lib/galaxy/objectstore/azure_blob.py")
    environment, output = select(repository, "push", {"before": base, "after": head}, python_flags=("-I", "-S"))
    assert families(environment) == {"azure"}
    assert "1 changed paths" in output
