"""Record API responses for client tests (``client/src/api/__fixtures__``).

Each class boots its own Galaxy, so responses that need a particular
configuration get a class of their own. Regenerate with
``make update-client-api-fixtures``.
"""

from galaxy_test.base.client_fixtures import ClientFixtures
from galaxy_test.base.populators import DatasetPopulator
from galaxy_test.driver import integration_util
from .objectstore.test_selection_with_resource_parameters import DISTRIBUTED_OBJECT_STORE_CONFIG_TEMPLATE

QUOTA_BYTES = 100_000_000
EBS_QUOTA_BYTES = 10_000_000


class ClientFixturesTestCase(integration_util.IntegrationTestCase):
    dataset_populator: DatasetPopulator

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)
        self.fixtures = ClientFixtures(self.galaxy_interactor)


class TestHistoryFixtures(ClientFixturesTestCase):
    def test_history_summary_extended(self):
        history_id = self.dataset_populator.new_history(name="Client Fixture History")
        self.dataset_populator.new_dataset(history_id, content="1\t2\t3\n", wait=True)

        def purpose(history):
            assert history["name"] == "Client Fixture History"
            assert history["contents_active"] == {"active": 1, "deleted": 0, "hidden": 0}
            assert history["size"] > 0
            assert history["user_id"]

        self.fixtures.capture(
            "get",
            "/api/histories/{history_id}",
            "summary_extended",
            params={"view": "summary", "keys": "size,contents_active,user_id"},
            purpose=purpose,
            history_id=history_id,
        )


class TestQuotaFixtures(ClientFixturesTestCase):
    require_admin_user = True

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        config["enable_quotas"] = True

    def test_user_usage_under_default_quota(self):
        self.dataset_populator.create_quota(
            {
                "name": "client-fixture-default",
                "description": "Default quota for client fixtures",
                "amount": "100MB",
                "operation": "=",
                "default": "registered",
            }
        )
        with self._different_user("client_fixture_quota@bx.psu.edu"):
            user_id = self.dataset_populator.user_id()
            history_id = self.dataset_populator.new_history(name="Client Fixture Quota History")
            self.dataset_populator.new_dataset(history_id, content="1\t2\t3\n", wait=True)

            def user_purpose(user):
                assert user["quota_bytes"] == QUOTA_BYTES
                assert user["quota"] != "unlimited"
                assert 0 < user["total_disk_usage"] < QUOTA_BYTES

            def usage_purpose(usages):
                assert len(usages) == 1
                assert usages[0]["quota_source_label"] is None
                assert usages[0]["quota_bytes"] == QUOTA_BYTES
                assert usages[0]["total_disk_usage"] > 0

            self.fixtures.capture("get", "/api/users/{user_id}", "under_quota", purpose=user_purpose, user_id=user_id)
            first_usage = self.fixtures.capture(
                "get", "/api/users/{user_id}/usage", "under_quota", purpose=usage_purpose, user_id=user_id
            )

            self.dataset_populator.new_dataset(history_id, content="4\t5\t6\n7\t8\t9\n", wait=True)

            def grown_usage_purpose(usages):
                usage_purpose(usages)
                assert usages[0]["total_disk_usage"] > first_usage[0]["total_disk_usage"]

            self.fixtures.capture(
                "get",
                "/api/users/{user_id}/usage",
                "after_second_upload",
                purpose=grown_usage_purpose,
                user_id=user_id,
            )


class TestQuotaSourceFixtures(ClientFixturesTestCase, integration_util.ConfiguresObjectStores):
    require_admin_user = True

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        cls._configure_object_store(DISTRIBUTED_OBJECT_STORE_CONFIG_TEMPLATE, config)
        config["enable_quotas"] = True

    def test_user_usage_per_quota_source(self):
        for name, amount, label in (("default", "100MB", None), ("ebs", "10MB", "ebs")):
            payload = {
                "name": f"client-fixture-{name}",
                "description": f"{name} quota for client fixtures",
                "amount": amount,
                "operation": "=",
                "default": "registered",
            }
            if label:
                payload["quota_source_label"] = label
            self.dataset_populator.create_quota(payload)
        with self._different_user("client_fixture_quota_sources@bx.psu.edu"):
            user_id = self.dataset_populator.user_id()
            history_id = self.dataset_populator.new_history(name="Client Fixture Quota Source History")
            self.dataset_populator.new_dataset(history_id, content="1\t2\t3\n", wait=True)

            def purpose(usages):
                by_label = {usage["quota_source_label"]: usage for usage in usages}
                assert set(by_label) == {None, "ebs", "s3"}
                assert by_label[None]["quota_bytes"] == QUOTA_BYTES
                assert by_label[None]["total_disk_usage"] > 0
                assert by_label["ebs"]["quota_bytes"] == EBS_QUOTA_BYTES
                assert by_label["s3"]["quota_bytes"] is None

            self.fixtures.capture(
                "get", "/api/users/{user_id}/usage", "per_quota_source", purpose=purpose, user_id=user_id
            )
