"""Integration tests for reading the start of an object from SeaweedFS-backed object stores."""

import os
from typing import cast

import boto3
import pytest

from galaxy.exceptions import ObjectNotFound
from galaxy.model import (
    Dataset,
    HistoryDatasetAssociation,
)
from galaxy.objectstore import (
    BaseObjectStore,
    HierarchicalObjectStore,
)
from ._base import (
    BaseCloudObjectStoreIntegrationTestCase,
    BaseSeaweedFSObjectStoreIntegrationTestCase,
    OBJECT_STORE_ACCESS_KEY,
    OBJECT_STORE_HOST,
    OBJECT_STORE_PORT,
    OBJECT_STORE_SECRET_KEY,
)


class GetDataHeadTests(BaseSeaweedFSObjectStoreIntegrationTestCase):
    def _concrete_store(self) -> BaseObjectStore:
        return self._app.object_store

    def _upload(self, content: str):
        history_id = self.dataset_populator.new_history()
        hda = self.upload_dataset_and_wait_for_hash(history_id, content=content)
        hda_model = self._app.model.session.get(HistoryDatasetAssociation, self._app.security.decode_id(hda["id"]))
        assert hda_model
        return hda_model.dataset

    def _bucket_client(self):
        return boto3.client(
            "s3",
            endpoint_url=f"http://{OBJECT_STORE_HOST}:{OBJECT_STORE_PORT}",
            aws_access_key_id=OBJECT_STORE_ACCESS_KEY,
            aws_secret_access_key=OBJECT_STORE_SECRET_KEY,
            region_name="us-east-1",
        )

    def _key(self, dataset) -> str:
        return self._app.object_store.construct_path(dataset)

    def test_reads_the_backend_instead_of_a_stale_empty_cached_copy(self):
        dataset = self._upload("head-me")
        cache_path = self._app.object_store.get_filename(dataset, sync_cache=False)
        # As left by creating the dataset on a host that did not write its data.
        open(cache_path, "wb").close()

        assert self._app.object_store.get_data_head(dataset, 4) == b"head"
        assert self._app.object_store.get_data_head(dataset, 100) == b"head-me\n"
        assert os.path.getsize(cache_path) == 0

    def test_reads_nothing_from_an_empty_object(self):
        dataset = self._upload("replace-me")
        # Caching stores skip pushing empty files, so write the empty object straight to the bucket.
        self._bucket_client().put_object(Bucket="galaxy", Key=self._key(dataset), Body=b"")
        open(self._app.object_store.get_filename(dataset, sync_cache=False), "wb").close()

        assert self._app.object_store.get_data_head(dataset, 10) == b""

    def test_missing_object_raises_object_not_found(self):
        never_stored = Dataset()
        with pytest.raises(ObjectNotFound):
            self._concrete_store().get_data_head(never_stored, 10)


class TestBoto3GetDataHeadIntegration(GetDataHeadTests):
    def _concrete_store(self) -> BaseObjectStore:
        return cast(HierarchicalObjectStore, self._app.object_store).backends[0]


class TestCloudGetDataHeadIntegration(GetDataHeadTests, BaseCloudObjectStoreIntegrationTestCase):
    pass
