"""Metadata files of outputs copied from a cached job."""

from galaxy import model
from galaxy_test.base.populators import DatasetPopulator
from galaxy_test.driver import integration_util

TOOL_ID = "cat_data_and_sleep"


class RunsCachedBamJob(integration_util.IntegrationTestCase):
    """Base for integration tests that run a BAM job and then hit the job cache with it."""

    dataset_populator: DatasetPopulator
    framework_tool_and_types = True

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)

    def _run_cached_bam_job(self, history_id: str, rename_input: bool = False) -> tuple[str, str]:
        """Run a BAM job, then run it again from the job cache.

        Returns the encoded ids of the source output and the cached output.
        """
        bam = self.dataset_populator.new_bam_dataset(history_id, self.test_data_resolver)
        inputs = {"input1": {"src": "hda", "id": bam["id"]}}
        source_run = self.dataset_populator.run_tool(TOOL_ID, inputs, history_id)
        source_job_id = source_run["jobs"][0]["id"]
        self.dataset_populator.wait_for_job(source_job_id, assert_ok=True)
        if rename_input:
            # The search at submission requires matching input names, the search at job preparation doesn't.
            self.dataset_populator.rename_dataset(bam["id"])
        cached_run = self.dataset_populator.run_tool(TOOL_ID, inputs, history_id, use_cached_job=True)
        cached_job_id = cached_run["jobs"][0]["id"]
        self.dataset_populator.wait_for_job(cached_job_id, assert_ok=True)
        cached_job = self.dataset_populator.get_job_details(cached_job_id, full=True).json()
        assert cached_job["copied_from_job_id"] == source_job_id
        return source_run["outputs"][0]["id"], cached_run["outputs"][0]["id"]

    def _hda(self, encoded_id: str) -> model.HistoryDatasetAssociation:
        session = self._app.model.session
        session.expire_all()
        hda = session.get(model.HistoryDatasetAssociation, self._app.security.decode_id(encoded_id))
        assert hda is not None
        return hda


class TestJobCacheMetadataFiles(RunsCachedBamJob):
    def test_cache_hit_at_submission(self):
        history_id = self.dataset_populator.new_history()
        self._check_cached_output_metadata_file(*self._run_cached_bam_job(history_id))

    def test_cache_hit_at_job_preparation(self):
        history_id = self.dataset_populator.new_history()
        self._check_cached_output_metadata_file(*self._run_cached_bam_job(history_id, rename_input=True))

    def _check_cached_output_metadata_file(self, source_id: str, cached_id: str) -> None:
        # Hold the HDAs: metadata keeps only a weak reference to its parent.
        source = self._hda(source_id)
        cached = self._hda(cached_id)
        source_index = source.metadata.bam_index
        cached_index = cached.metadata.bam_index
        assert isinstance(source_index, model.MetadataFile)
        assert isinstance(cached_index, model.MetadataFile)
        assert source_index.history_dataset is source
        assert cached_index.history_dataset is cached
        assert cached_index.id != source_index.id
        assert cached_index.get_file_name() != source_index.get_file_name()
        with open(source_index.get_file_name(), "rb") as fh:
            source_bytes = fh.read()
        with open(cached_index.get_file_name(), "rb") as fh:
            assert fh.read() == source_bytes
