import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from galaxy import model
from galaxy_test.base.populators import (
    DatasetCollectionPopulator,
    DatasetPopulator,
)
from galaxy_test.driver.integration_util import (
    IntegrationTestCase,
    skip_unless_postgres,
)


@skip_unless_postgres()
class TestCollectionUpdateTimeLockingIntegration(IntegrationTestCase):
    dataset_populator: DatasetPopulator

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)
        self.dataset_collection_populator = DatasetCollectionPopulator(self.galaxy_interactor)

    def test_touch_collection_update_time_allows_foreign_key_checks(self):
        with self.dataset_populator.test_history() as history_id:
            fetch_response = self.dataset_collection_populator.create_list_in_history(
                history_id, contents=["1 2 3"], wait=True
            ).json()
            hdca = self.dataset_collection_populator.wait_for_fetched_collection(fetch_response)
            hdca_id = self._app.security.decode_id(hdca["id"])
            hda_id = self._app.security.decode_id(hdca["elements"][0]["object"]["id"])

            engine = self._app.model.engine
            lock_hdca = "SELECT 1 FROM history_dataset_collection_association WHERE id = :id FOR {} NOWAIT"
            with Session(engine) as session:
                hda = session.get(model.HistoryDatasetAssociation, hda_id)
                assert hda and hda.dataset
                hda.dataset.touch_collection_update_time(supports_skip_locked=True)
                # HDCA stays locked until rollback; FK checks on referencing inserts take FOR KEY SHARE.
                with engine.connect() as conn:
                    conn.execute(text(lock_hdca.format("KEY SHARE")), {"id": hdca_id})
                # Guards against the touch silently locking nothing.
                with (
                    engine.connect() as conn,
                    pytest.raises(OperationalError, match="could not obtain lock"),
                ):
                    conn.execute(text(lock_hdca.format("UPDATE")), {"id": hdca_id})
                session.rollback()
