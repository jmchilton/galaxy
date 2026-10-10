"""Record API responses for client tests (``client/src/api/__fixtures__``).

Each class boots its own Galaxy, so responses that need a particular
configuration get a class of their own. Regenerate with
``make update-client-api-fixtures``.
"""

from galaxy_test.base.client_fixtures import ClientFixtures
from galaxy_test.base.populators import DatasetPopulator
from galaxy_test.driver import integration_util


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
