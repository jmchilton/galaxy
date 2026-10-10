"""Record API responses that need quotas enabled, for client tests (``client/src/api/__fixtures__``).

Regenerate with ``GALAXY_TEST_CLIENT_FIXTURES=update ./run_tests.sh -integration test/integration/test_client_fixtures_quotas.py``.
"""

from galaxy_test.base.client_fixtures import ClientFixtures
from galaxy_test.base.populators import DatasetPopulator
from galaxy_test.driver import integration_util

QUOTA_BYTES = 100_000_000


class TestClientFixturesQuotas(integration_util.IntegrationTestCase):
    dataset_populator: DatasetPopulator
    require_admin_user = True

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        config["enable_quotas"] = True

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)
        self.fixtures = ClientFixtures(self.galaxy_interactor)

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
            user_id = self._get("users/current").json()["id"]
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
