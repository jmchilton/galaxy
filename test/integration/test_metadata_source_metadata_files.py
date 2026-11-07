"""Discovered outputs with metadata_source must not share metadata files with their input."""

from typing import Any

from sqlalchemy import select

from galaxy import model
from galaxy_test.base.populators import DatasetPopulator
from galaxy_test.driver import integration_util

SENTINEL = b"sentinel index bytes"


class MetadataSourceDiscoveredTestCase(integration_util.IntegrationTestCase):
    dataset_populator: DatasetPopulator
    framework_tool_and_types = True
    metadata_strategy: str
    store_by = "uuid"

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        config["metadata_strategy"] = cls.metadata_strategy
        config["object_store_store_by"] = cls.store_by

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)

    def _hda(self, encoded_id: str) -> model.HistoryDatasetAssociation:
        session = self._app.model.session
        session.rollback()
        session.expire_all()
        hda = session.get(model.HistoryDatasetAssociation, self._app.security.decode_id(encoded_id))
        assert hda is not None
        return hda

    def _run_tool(self) -> dict[str, Any]:
        """Run the tool with 1.bam as metadata source and 3.bam as the output's data."""
        history_id = self.dataset_populator.new_history()
        metadata_input = self.dataset_populator.new_dataset_from_test_data(
            history_id, self.test_data_resolver, "1.bam", "bam"
        )
        data_source = self.dataset_populator.new_dataset_from_test_data(
            history_id, self.test_data_resolver, "3.bam", "bam"
        )
        self.dataset_populator.wait_for_history(history_id, assert_ok=True)
        input_index = self._read_index(metadata_input["id"])
        data_source_index = self._read_index(data_source["id"])
        assert input_index != data_source_index
        response = self.dataset_populator.run_tool(
            "metadata_source_discovered",
            {
                "metadata_input": {"src": "hda", "id": metadata_input["id"]},
                "data_source": {"src": "hda", "id": data_source["id"]},
            },
            history_id,
        )
        self.dataset_populator.wait_for_job(response["jobs"][0]["id"], assert_ok=True)
        self.dataset_populator.wait_for_history(history_id, assert_ok=True)
        hdca = self.dataset_populator.get_history_collection_details(
            history_id, hid=response["output_collections"][0]["hid"]
        )
        return {
            "history_id": history_id,
            "input_id": metadata_input["id"],
            "output_id": hdca["elements"][0]["object"]["id"],
            "input_index": input_index,
            "data_source_index": data_source_index,
        }

    def _index_path(self, encoded_id: str) -> str:
        # keeps the HDA referenced, metadata only holds it weakly
        hda = self._hda(encoded_id)
        return hda.metadata.bam_index.get_file_name()

    def _read_index(self, encoded_id: str) -> bytes:
        with open(self._index_path(encoded_id), "rb") as f:
            return f.read()

    def _owned_row(self, encoded_id: str) -> model.MetadataFile:
        hda = self._hda(encoded_id)
        rows = self._app.model.session.scalars(select(model.MetadataFile).filter_by(hda_id=hda.id)).all()
        assert len(rows) == 1, rows
        return rows[0]

    def test_output_row_has_own_uuid(self):
        run = self._run_tool()
        assert self._owned_row(run["output_id"]).uuid != self._owned_row(run["input_id"]).uuid

    def test_output_metadata_resolves_to_its_own_row(self):
        run = self._run_tool()
        output_hda = self._hda(run["output_id"])
        assert output_hda.metadata.bam_index.hda_id == output_hda.id

    def test_output_and_input_index_paths_differ(self):
        run = self._run_tool()
        assert self._index_path(run["output_id"]) != self._index_path(run["input_id"])

    def test_tool_job_keeps_input_index(self):
        run = self._run_tool()
        assert self._read_index(run["input_id"]) == run["input_index"]

    def test_output_index_matches_output_data(self):
        run = self._run_tool()
        assert self._read_index(run["output_id"]) == run["data_source_index"]

    def test_set_metadata_on_output_keeps_input_index(self):
        run = self._run_tool()
        input_path = self._index_path(run["input_id"])
        with open(input_path, "wb") as f:
            f.write(SENTINEL)
        response = self._put(f"histories/{run['history_id']}/contents/{run['output_id']}/validate")
        self._assert_status_code_is_ok(response)
        # the set metadata job only shows in the dataset's state
        self.dataset_populator.wait_for_dataset(run["history_id"], run["output_id"], assert_ok=True)
        assert self._hda(run["output_id"]).state == "ok"
        with open(input_path, "rb") as f:
            assert f.read() == SENTINEL


class TestMetadataSourceDiscoveredExtendedUuid(MetadataSourceDiscoveredTestCase):
    """Expected red until discovered outputs get their own metadata files."""

    metadata_strategy = "extended"


class TestMetadataSourceDiscoveredDirectoryUuid(MetadataSourceDiscoveredTestCase):
    """Control: the directory strategy copies the metadata file."""

    metadata_strategy = "directory"
