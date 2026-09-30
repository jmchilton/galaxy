import string

from sqlalchemy import (
    select,
    text,
)

from galaxy.model import ToolLicenseAcceptanceEvent
from galaxy_test.base.api_util import random_name
from galaxy_test.base.populators import (
    LicenseAgreementsPopulator,
    skip_without_tool,
)
from galaxy_test.driver import integration_util
from .test_scripts import BaseScriptsIntegrationTestCase

DISTRIBUTED_OBJECT_STORE_CONFIG_TEMPLATE = string.Template("""
type: distributed
backends:
  - type: disk
    id: default
    weight: 1
    name: Default Store
    files_dir: "${temp_directory}/files_default"
    extra_dirs:
      - type: temp
        path: "${temp_directory}/tmp_default"
      - type: job_work
        path: "${temp_directory}/job_working_directory_default"
""")

USER_OBJECT_STORE_CATALOG = """
- id: general_disk
  name: General Disk
  description: General Disk Bound to You
  configuration:
    type: disk
    files_dir: '/data/general/{{ user.username }}'
"""

SCRIPT = "cleanup_datasets/pgcleanup.py"
USER_BOUND_LICENSE_TOOL = "license_agreement_variant_tool"
USER_BOUND_LICENSE_ID = "license_agreement_path"


class TestScriptsPgCleanupIntegration(BaseScriptsIntegrationTestCase):
    def test_help(self):
        self._skip_unless_postgres()
        self._scripts_check_argparse_help(SCRIPT)

    def test_purge_deleted_histories(self):
        self._skip_unless_postgres()

        history_id = self.dataset_populator.new_history()
        delete_response = self.dataset_populator._delete(f"histories/{history_id}")
        assert delete_response.status_code == 200
        assert delete_response.json()["purged"] is False
        self._pgcleanup_check_output(["--older-than", "0", "--sequence", "purge_deleted_histories"])
        history_response = self.dataset_populator._get(f"histories/{history_id}")
        assert history_response.status_code == 200
        assert history_response.json()["purged"] is True, history_response.json()

    def test_purge_old_hdas(self):
        self._skip_unless_postgres()

        history_id = self.dataset_populator.new_history()
        hda = self.dataset_populator.new_dataset(history_id, wait=True)
        assert not self.is_purged(history_id, hda)

        # filtering on a date too old - shouldn't purge the dataset
        self._pgcleanup_check_output(
            [
                "--older-than",
                "1",
                "--sequence",
                "purge_old_hdas",
            ]
        )
        assert not self.is_purged(history_id, hda)

        # filtering on invalid object store - shouldn't purge the dataset
        self._pgcleanup_check_output(
            [
                "--older-than",
                "0",
                "--object-store-id",
                "myfakeobjectstore",
                "--sequence",
                "purge_old_hdas",
            ]
        )
        assert not self.is_purged(history_id, hda)

        self._pgcleanup_check_output(["--older-than", "0", "--sequence", "purge_old_hdas"])

        assert self.is_purged(history_id, hda)

    @skip_without_tool("test_data_source")
    def test_purge_errored_hdas(self):
        self._skip_unless_postgres()
        history_id = self.dataset_populator.new_history()
        error_dataset = self.dataset_populator.new_error_dataset(history_id)
        assert not self.is_purged(history_id, error_dataset)

        # dataset not old enough, shouldn't be purged
        self._pgcleanup_check_output(
            [
                "--older-than",
                "1",
                "--sequence",
                "purge_error_hdas",
            ]
        )
        assert not self.is_purged(history_id, error_dataset)

        # dataset not in target object store, shouldn't be purged
        self._pgcleanup_check_output(
            [
                "--older-than",
                "0",
                "--object-store-id",
                "myfakeobjectstore",
                "--sequence",
                "purge_error_hdas",
            ]
        )
        assert not self.is_purged(history_id, error_dataset)

        # okay though, this should purge the dataset
        self._pgcleanup_check_output(
            [
                "--older-than",
                "0",
                "--sequence",
                "purge_error_hdas",
            ]
        )
        assert self.is_purged(history_id, error_dataset)

    def test_purge_datasets(self):
        self._skip_unless_postgres()

        history_id = self.dataset_populator.new_history()
        hda = self.dataset_populator.new_dataset(history_id, wait=True)
        self.dataset_populator.delete_dataset(history_id, hda["id"])
        assert not self.is_purged(history_id, hda)

        self._pgcleanup_check_output(
            [
                "--older-than",
                "1",
                "--sequence",
                "purge_datasets",
            ]
        )
        assert not self.is_purged(history_id, hda)

        self._pgcleanup_check_output(
            [
                "--older-than",
                "0",
                "--object-store-id",
                "myfakeobjectstore",
                "--sequence",
                "purge_datasets",
            ]
        )
        assert not self.is_purged(history_id, hda)

        self._pgcleanup_check_output(
            [
                "--older-than",
                "0",
                "--sequence",
                "purge_datasets",
            ]
        )
        self._pgcleanup_check_output(
            [
                "--older-than",
                "0",
                "--sequence",
                "purge_datasets",
            ]
        )

        # why is this not purged?
        # test or functionality seem broken but better to run through it and ensure
        # it isn't breaking anything and everything is syntactically correct than not
        # assert self.is_purged(history_id, hda)

    def test_delete_datasets(self):
        # this walks through the code to ensure no SQL or Python errors but
        # I think we would need to talk to the model layer from the test directly
        # to actually produce datasets of the target type for purging and to verify
        # they were purged (certainly a possibility)
        self._skip_unless_postgres()

        history_id = self.dataset_populator.new_history()
        hda = self.dataset_populator.new_dataset(history_id, wait=True)

        assert not self.is_purged(history_id, hda)

        self._pgcleanup_check_output(
            [
                "--older-than",
                "0",
                "--sequence",
                "delete_datasets",
            ]
        )
        self._pgcleanup_check_output(
            [
                "--older-than",
                "0",
                "--object-store-id",
                "myfakeobjectstore",
                "--sequence",
                "delete_datasets",
            ]
        )

        assert not self.is_purged(history_id, hda)

    def test_purge_historyless_hdas(self):
        # same as above - this is just a negative test for things being broken
        # we could access the model layer to write a test to verify the positive
        # behavior actually occurs
        self._skip_unless_postgres()

        history_id = self.dataset_populator.new_history()
        hda = self.dataset_populator.new_dataset(history_id, wait=True)

        assert not self.is_purged(history_id, hda)
        self._pgcleanup_check_output(
            [
                "--older-than",
                "0",
                "--sequence",
                "purge_historyless_hdas",
            ]
        )
        self._pgcleanup_check_output(
            [
                "--older-than",
                "0",
                "--object-store-id",
                "myfakeobjectstore",
                "--sequence",
                "purge_historyless_hdas",
            ]
        )

        assert not self.is_purged(history_id, hda)

    @skip_without_tool(USER_BOUND_LICENSE_TOOL)
    def test_purge_deleted_users_removes_license_acceptance_events(self):
        self._skip_unless_postgres()
        self._assert_purge_removes_license_acceptance_events("purge_deleted_users")

    @skip_without_tool(USER_BOUND_LICENSE_TOOL)
    def test_purge_deleted_users_gdpr_removes_license_acceptance_events(self):
        self._skip_unless_postgres()
        # The GDPR action obfuscates emails with pgcrypto's digest().
        session = self._app.model.session
        session.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        session.commit()
        self._assert_purge_removes_license_acceptance_events("purge_deleted_users_gdpr")

    def _assert_purge_removes_license_acceptance_events(self, action: str) -> None:
        purged_email = f"{random_name()}@galaxy.org"
        purged_user_id = self._setup_user(purged_email)["id"]
        with self._different_user(purged_email):
            LicenseAgreementsPopulator(self.galaxy_interactor).accept_license_agreement(
                USER_BOUND_LICENSE_TOOL, USER_BOUND_LICENSE_ID
            )
        survivor_email = f"{random_name()}@galaxy.org"
        survivor_id = self._app.security.decode_id(self._setup_user(survivor_email)["id"])
        with self._different_user(survivor_email):
            survivor_populator = LicenseAgreementsPopulator(self.galaxy_interactor)
            survivor_populator.accept_license_agreement(USER_BOUND_LICENSE_TOOL, USER_BOUND_LICENSE_ID)
        decoded_purged_user_id = self._app.security.decode_id(purged_user_id)
        (granted,) = self._license_acceptance_events(survivor_id)
        # No API grants an acceptance on another user's behalf yet.
        granted.granted_by = ToolLicenseAcceptanceEvent.granted_by_types.ADMIN
        granted.granted_by_user_id = decoded_purged_user_id
        granted_id = granted.id
        self._app.model.session.commit()
        assert self._license_acceptance_events(decoded_purged_user_id)

        delete_response = self._delete(f"users/{purged_user_id}", admin=True)
        assert delete_response.status_code == 200
        self._pgcleanup_check_output(["--older-than", "0", "--sequence", action])

        assert self._license_acceptance_events(decoded_purged_user_id) == []
        (retained,) = self._license_acceptance_events(survivor_id)
        assert retained.id == granted_id
        assert retained.granted_by == ToolLicenseAcceptanceEvent.granted_by_types.ADMIN
        assert retained.granted_by_user_id is None
        with self._different_user(survivor_email):
            (agreement,) = survivor_populator.tool_license_agreements(USER_BOUND_LICENSE_TOOL)
            assert agreement["accepted"] is True

    def _license_acceptance_events(self, user_id: int) -> list[ToolLicenseAcceptanceEvent]:
        session = self._app.model.session
        session.expire_all()
        stmt = select(ToolLicenseAcceptanceEvent).where(ToolLicenseAcceptanceEvent.user_id == user_id)
        return list(session.scalars(stmt))


class TestPgCleanupUserObjectStoreIntegration(
    BaseScriptsIntegrationTestCase,
    integration_util.ConfiguresObjectStores,
):
    """Test that pgcleanup handles datasets in user-defined object stores gracefully.

    When a dataset is stored in a user-defined object store (object_store_id starting
    with "user_objects://"), the pgcleanup script cannot resolve the object store backend
    since it doesn't have access to the UserObjectStoreResolver. The script should skip
    physical file removal for such objects while still updating the database records.
    """

    framework_tool_and_types = True

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        cls._configure_object_store(DISTRIBUTED_OBJECT_STORE_CONFIG_TEMPLATE, config, format="yml")
        config["object_store_store_by"] = "uuid"
        cls._configure_object_store_template_catalog(USER_OBJECT_STORE_CATALOG, config)

    def _create_user_object_store(self) -> str:
        """Create a user-defined object store via the API and return its object_store_id."""
        body = {
            "name": "My Test Disk",
            "template_id": "general_disk",
            "template_version": 0,
            "secrets": {},
            "variables": {},
        }
        object_store_json = self.dataset_populator.create_object_store(body)
        object_store_id = object_store_json["object_store_id"]
        assert object_store_id.startswith("user_objects://")
        return object_store_id

    def test_purge_deleted_histories_with_user_object_store_dataset(self):
        """Test that purging histories containing datasets in user object stores doesn't crash.

        This verifies the fix for the KeyError that occurred when pgcleanup tried to call
        get_store_by() on objects stored in user-defined object stores, which cannot be
        resolved without a UserObjectStoreResolver (not available in the cleanup script).
        """
        self._skip_unless_postgres()

        # Create a user-defined object store
        object_store_id = self._create_user_object_store()

        # Set the user's preferred object store to the user-defined one
        self.dataset_populator.set_user_preferred_object_store_id(object_store_id)

        # Create a history and upload a dataset (it should go to the user object store)
        history_id = self.dataset_populator.new_history()
        hda = self.dataset_populator.new_dataset(history_id, content="test data for user object store", wait=True)

        # Verify the dataset is in the user object store
        storage_info = self.dataset_populator.dataset_storage_info(hda["id"])
        assert (
            storage_info["object_store_id"] == object_store_id
        ), f"Expected dataset in user object store {object_store_id}, but got {storage_info['object_store_id']}"

        # Reset user preference so subsequent datasets don't use it
        self.dataset_populator.set_user_preferred_object_store_id(None)

        # Delete the history
        delete_response = self.dataset_populator._delete(f"histories/{history_id}")
        assert delete_response.status_code == 200
        assert delete_response.json()["purged"] is False

        # Run pgcleanup - this should NOT crash with a KeyError
        # Before the fix, this would raise:
        #   KeyError: 'user_objects://...' in _resolve_backend
        self._pgcleanup_check_output(["--older-than", "0", "--sequence", "purge_deleted_histories"])

        # The history should be purged in the database even though the physical
        # file in the user object store could not be removed
        history_response = self.dataset_populator._get(f"histories/{history_id}")
        assert history_response.status_code == 200
        assert history_response.json()["purged"] is True, history_response.json()

    def test_purge_old_hdas_with_user_object_store_dataset(self):
        """Test that purging HDAs in user object stores doesn't crash pgcleanup."""
        self._skip_unless_postgres()

        object_store_id = self._create_user_object_store()
        self.dataset_populator.set_user_preferred_object_store_id(object_store_id)

        history_id = self.dataset_populator.new_history()
        hda = self.dataset_populator.new_dataset(history_id, content="test data", wait=True)

        # Verify the dataset is in the user object store
        storage_info = self.dataset_populator.dataset_storage_info(hda["id"])
        assert storage_info["object_store_id"] == object_store_id

        self.dataset_populator.set_user_preferred_object_store_id(None)

        # Run pgcleanup - should not crash
        self._pgcleanup_check_output(["--older-than", "0", "--sequence", "purge_old_hdas"])

        # The HDA should be purged in the database
        assert self.is_purged(history_id, hda)
