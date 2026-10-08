"""Conservative opt-in CI selection for expensive integration test groups.

Only tests with a ci_integration_family marker can be deselected. General integration coverage and
new, unclassified tests always run. Keep source mappings together
so that adding a family is a reviewable change to this one policy.

This module intentionally uses only the standard library: CI runs the classifier
before installing Galaxy or its test dependencies.
"""

import json
from collections.abc import Mapping
from dataclasses import (
    dataclass,
    field,
)

SELECTION_ENV = "GALAXY_TEST_CI_SELECTION"
# Test edits select their marked families. Mixed modules may need several.
TEST_PATHS: dict[str, tuple[str, ...]] = {
    "test_kubernetes_runner.py": ("kubernetes",),
    "test_htcondor_runner.py": ("htcondor",),
    "test_pulsar_embedded.py": ("pulsar",),
    "test_pulsar_embedded_containers.py": ("pulsar",),
    "test_pulsar_embedded_copy_working.py": ("pulsar",),
    "test_pulsar_embedded_extended_metadata.py": ("pulsar",),
    "test_pulsar_embedded_mq.py": ("pulsar",),
    "test_pulsar_embedded_none.py": ("pulsar",),
    "test_pulsar_embedded_relay.py": ("pulsar",),
    "test_pulsar_embedded_remote_metadata.py": ("pulsar",),
    "test_containerized_jobs.py": ("containers", "kubernetes", "pulsar"),
    "test_container_resolution.py": ("containers",),
    "test_container_resolvers.py": ("containers",),
    "test_metadata_containerized.py": ("containers",),
    "objectstore/test_cloud_objectstore.py": ("cloud",),
    "objectstore/test_swift_objectstore.py": ("s3",),
    "objectstore/test_remote_objectstore_cache_operations.py": ("s3",),
    "objectstore/test_onedata_objectstore.py": ("onedata",),
    "objectstore/test_rucio_objectstore.py": ("rucio",),
    "objectstore/test_azure.py": ("azure",),
    "objectstore/test_objectstore_datatype_upload.py": ("irods",),
    "objectstore/test_tee_streaming.py": ("cloud", "s3"),
    "objectstore/test_direct_download_redirect.py": ("cloud", "s3"),
}
FAMILIES = frozenset(family for families in TEST_PATHS.values() for family in families)

# Match specific plugins before shared directories. Unlisted plugins conservatively
# select all families; shared job/objectstore code can affect both subsystems.
PLUGIN_PATHS = {
    "lib/galaxy/jobs/runners/kubernetes.py": {"kubernetes"},
    "lib/galaxy/jobs/runners/util/pykube_util.py": {"kubernetes"},
    "lib/galaxy/jobs/runners/condor.py": {"htcondor"},
    "lib/galaxy/jobs/runners/util/condor/": {"htcondor"},
    "lib/galaxy/jobs/runners/pulsar.py": {"pulsar"},
    "lib/galaxy/objectstore/cloud.py": {"cloud"},
    "lib/galaxy/objectstore/s3.py": {"s3", "cloud"},
    "lib/galaxy/objectstore/s3_boto3.py": {"s3"},
    "lib/galaxy/objectstore/s3_multipart_upload.py": {"s3", "cloud"},
    "lib/galaxy/objectstore/azure_blob.py": {"azure"},
    "lib/galaxy/objectstore/onedata.py": {"onedata"},
    "lib/galaxy/objectstore/rucio.py": {"rucio"},
    "lib/galaxy/objectstore/irods.py": {"irods"},
}
FULL_PATHS = (
    ".github/",
    ".ci/",
    "scripts/",
    "config/",
    "test/",
    "test-data/",
    "tools/",
    "lib/galaxy_test/",
    "lib/galaxy/app.py",
    "lib/galaxy/structured_app.py",
    "lib/galaxy/exceptions/",
    "lib/galaxy/celery/",
    "lib/galaxy/managers/datasets.py",
    "lib/galaxy/managers/hdas.py",
    "lib/galaxy/managers/history_contents.py",
    "lib/galaxy/managers/collections.py",
    "lib/galaxy/managers/collections_util.py",
    "lib/galaxy/managers/dataset_storage_operations.py",
    "lib/galaxy/managers/tools.py",
    "lib/galaxy/files/",
    "lib/galaxy/web/",
    "lib/galaxy/webapps/base/",
    "lib/galaxy/schema/schema.py",
    "lib/galaxy/webapps/galaxy/api/jobs.py",
    "lib/galaxy/webapps/galaxy/api/datasets.py",
    "lib/galaxy/webapps/galaxy/api/history_contents.py",
    "lib/galaxy/webapps/galaxy/api/tools.py",
    "lib/galaxy/webapps/galaxy/services/datasets.py",
    "lib/galaxy/webapps/galaxy/services/history_contents.py",
    "lib/galaxy/webapps/galaxy/services/dataset_collections.py",
    "lib/galaxy/webapps/galaxy/services/tools.py",
    "lib/galaxy/webapps/galaxy/controllers/dataset.py",
    "lib/galaxy/webapps/galaxy/controllers/tool_runner.py",
    "lib/galaxy/model/",
    "lib/galaxy/config/",
    "lib/galaxy/tools/",
    "lib/galaxy/tool_util/",
    "lib/galaxy/job_execution/",
    "lib/galaxy/metadata/",
    "lib/galaxy/datatypes/",
    "requirements",
    "pyproject.toml",
    "uv.lock",
    "setup.cfg",
    "pytest.ini",
    "run_tests.sh",
    "Makefile",
    "setup.py",
    "lib/galaxy/version/",
    "lib/galaxy/dependencies/",
    "lib/galaxy/job_metrics/",
    "lib/galaxy/security/",
    "lib/galaxy/managers/jobs.py",
    "lib/galaxy/webapps/galaxy/services/jobs.py",
    "lib/galaxy/schema/jobs.py",
)


def matches(path: str, rule: str) -> bool:
    return path.startswith(rule) if rule.endswith("/") or rule == "requirements" else path == rule


@dataclass
class Selection:
    families: set[str] = field(default_factory=set)
    utils_changed: bool = False
    jobs_changed: bool = False
    objectstore_changed: bool = False
    full: bool = False
    reason: str = "changed-path selection"

    @classmethod
    def all(cls, reason: str) -> "Selection":
        return cls(set(FAMILIES), True, True, True, True, reason)

    def environment(self) -> dict[str, str]:
        return {
            SELECTION_ENV: json.dumps({"version": 1, "families": sorted(self.families)}),
            "GALAXY_TEST_CI_UTILS_CHANGED": str(int(self.utils_changed)),
            "GALAXY_TEST_CI_JOBS_PLUMBING_CHANGED": str(int(self.jobs_changed)),
            "GALAXY_TEST_CI_OBJECTSTORE_PLUMBING_CHANGED": str(int(self.objectstore_changed)),
        }


def classify_paths(paths: list[str]) -> Selection:
    selection = Selection()
    for path in paths:
        # Editing a listed test selects its family, without affecting others.
        relative_test = path.removeprefix("test/integration/")
        if path.startswith("test/integration/") and relative_test in TEST_PATHS:
            selection.families.update(TEST_PATHS[relative_test])
            continue
        plugin = next((families for rule, families in PLUGIN_PATHS.items() if matches(path, rule)), None)
        if plugin is not None:
            selection.families.update(plugin)
            continue
        if path.startswith("lib/galaxy/util/"):
            selection.utils_changed = True
            selection.families.update(FAMILIES)
        elif path.startswith("lib/galaxy/jobs/"):
            selection.jobs_changed = True
            selection.families.update(FAMILIES)
        elif path.startswith("lib/galaxy/objectstore/"):
            selection.objectstore_changed = True
            selection.families.update(FAMILIES)
        elif any(matches(path, rule) for rule in FULL_PATHS):
            return Selection.all(f"shared infrastructure or dependency changed: {path}")
    return selection


def selected_families(environment: Mapping[str, str]) -> set[str] | None:
    """Absent, malformed, or incompatible input always means the full suite."""
    try:
        selection = json.loads(environment[SELECTION_ENV])
        families = selection["families"]
        if (
            selection["version"] == 1
            and isinstance(families, list)
            and all(isinstance(family, str) and family in FAMILIES for family in families)
        ):
            return set(families)
    except (KeyError, ValueError, TypeError):
        pass
    return None
