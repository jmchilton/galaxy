import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from galaxy import model
from galaxy.app_unittest_utils import tools_support
from galaxy.job_execution.datasets import DatasetPath
from galaxy.job_execution.metadata_constants import LAZY_IMPORTS_ENV
from galaxy.metadata import get_metadata_compute_strategy
from galaxy.metadata.set_metadata import load_job_metadata
from galaxy.model.store.discover import InvalidDiscoveredFilePathError
from galaxy.objectstore import ObjectStorePopulator
from galaxy.objectstore._caching_base import CachingConcreteObjectStore
from galaxy.objectstore.caching import (
    CacheShard,
    CacheShardManager,
)
from galaxy.tool_util.parser.yaml import YamlToolSource
from galaxy.tool_util.provided_metadata import NullToolProvidedMetadata
from galaxy.tool_util_models import UserToolSource
from galaxy.tools import create_tool_from_source
from galaxy.util import (
    galaxy_directory,
    safe_makedirs,
)
from galaxy.util.unittest import TestCase


class MissingRemoteCachingObjectStore(CachingConcreteObjectStore):
    def __init__(self, cache_path):
        self._cache_shards = CacheShardManager([CacheShard(path=cache_path, weight=1, size=-1)])
        self.config = SimpleNamespace(umask=0o002, gid=-1)
        self.cache_updated_data = True
        self.store_by = "id"
        self.extra_dirs = {}

    def _get_remote_size(self, rel_path):
        return 0

    def _exists_remotely(self, rel_path):
        return False

    def _download(self, rel_path, *, cache_path, cache_target):
        return False

    def _push_string_to_path(self, rel_path, from_string):
        return True

    def _push_file_to_path(self, rel_path, source_file):
        return True

    def _delete_existing_remote(self, rel_path):
        return True

    def _delete_remote_all(self, rel_path):
        return True


def test_extended_metadata_rejects_metadata_file_symlink_outside_working_directory(
    tmp_path,
):
    working_directory = tmp_path / "working"
    working_directory.mkdir()
    outside_metadata = tmp_path / "outside.json"
    outside_metadata.write_text("{}")
    metadata_symlink = working_directory / "galaxy.json"
    metadata_symlink.symlink_to(outside_metadata)

    with pytest.raises(InvalidDiscoveredFilePathError):
        load_job_metadata(
            metadata_symlink,
            "default",
            uses_tool_provided_metadata=True,
            job_working_directory=working_directory,
        )


class TestMetadata(TestCase, tools_support.UsesTools):
    @pytest.fixture(autouse=True, params=["normal", "all"] if hasattr(sys, "set_lazy_imports") else ["normal"])
    def configure_metadata_import_mode(self, request):
        self.metadata_import_mode = request.param

    def setUp(self):
        super().setUp()
        self.setup_app()
        model.Dataset.object_store = self.app.object_store
        job = model.Job()
        sa_session = self.app.model.session
        sa_session.add(job)
        history = model.History()
        job.history = history
        sa_session.commit()
        self.job = job
        self.history = history
        self.job_working_directory = os.path.join(self.test_directory, "job_working")
        self.tool_working_directory = os.path.join(self.job_working_directory, "working")
        os.mkdir(self.job_working_directory)
        os.mkdir(self.tool_working_directory)

    def tearDown(self):
        super().tearDown()
        self.metadata_compute_strategy = None

    def test_simple_output_directory(self):
        self.app.config.metadata_strategy = "directory"
        self._test_simple_output()

    def test_simple_output_extended(self):
        self.app.config.metadata_strategy = "extended"
        self._test_simple_output()

    def test_setup_does_not_sync_empty_job_output(self):
        self.app.config.metadata_strategy = "directory"
        source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/for_workflows/cat.xml")
        self._init_tool_for_path(source_file_name)
        output_dataset = self._create_output_dataset(extension="txt")
        object_store = MissingRemoteCachingObjectStore(os.path.join(self.test_directory, "remote_cache"))
        object_store.create(output_dataset.dataset)
        output_path = object_store.get_filename(output_dataset.dataset, sync_cache=False)

        output_dataset.dataset.object_store = object_store
        self.metadata_command({"out_file1": output_dataset})

        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) == 0
        with open(os.path.join(self.job_working_directory, "metadata", "params.json")) as f:
            metadata_params = json.load(f)
        assert metadata_params["outputs"]["out_file1"]["filename_override"] == output_path

    def test_file_metadata_extended(self):
        self.app.config.metadata_strategy = "extended"
        source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/for_workflows/cat.xml")
        self._init_tool_for_path(source_file_name)
        output_dataset = self._create_output_dataset(extension="bam")
        self.app.model.session.commit()
        command = self.metadata_command({"out_file1": output_dataset})
        Path(output_dataset.dataset.get_file_name()).write_bytes(
            Path(galaxy_directory(), "test-data", "1.bam").read_bytes()
        )
        self._write_job_files()

        self.exec_metadata_command(command)

        export_directory = Path(self.job_working_directory) / "metadata" / "outputs_populated"
        dataset_attributes = json.loads((export_directory / "datasets_attrs.txt").read_text())[0]
        serialized_index = dataset_attributes["metadata"]["bam_index"]
        assert serialized_index["model_class"] == "MetadataFile"
        if "file_name" in serialized_index:
            assert (export_directory / serialized_index["file_name"]).stat().st_size > 0

        assert self.metadata_compute_strategy
        self.metadata_compute_strategy.load_metadata(
            output_dataset,
            "out_file1",
            self.app.model.session,
            working_directory=self.job_working_directory,
        )
        assert output_dataset.metadata.bam_index.name == "bam_index"
        assert Path(output_dataset.metadata.bam_index.get_file_name()).stat().st_size > 0

    def test_sniffed_output_extended(self):
        self.app.config.metadata_strategy = "extended"
        source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/for_workflows/cat.xml")
        self._init_tool_for_path(source_file_name)
        output_dataset = self._create_output_dataset(extension="data")
        self.app.model.session.commit()
        command = self.metadata_command({"out_file1": output_dataset})
        self._write_galaxy_json(f'{{"type": "dataset", "dataset_id": "{output_dataset.dataset.id}", "ext": "_sniff_"}}')
        self._write_output_dataset_contents(output_dataset, ">seq1\nGCTGCATG\n")
        self._write_job_files()

        self.exec_metadata_command(command)

        export_directory = Path(self.job_working_directory) / "metadata" / "outputs_populated"
        dataset_attributes = json.loads((export_directory / "datasets_attrs.txt").read_text())[0]
        assert dataset_attributes["extension"] == "fasta"
        assert dataset_attributes["metadata"]["sequences"] == 1

        assert self.metadata_compute_strategy
        output_dataset.extension = dataset_attributes["extension"]
        self.metadata_compute_strategy.load_metadata(
            output_dataset,
            "out_file1",
            self.app.model.session,
            working_directory=self.job_working_directory,
        )
        assert output_dataset.metadata.sequences == 1

    def _test_simple_output(self):
        source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/for_workflows/cat.xml")
        self._init_tool_for_path(source_file_name)
        output_dataset = self._create_output_dataset(
            extension="fasta",
        )
        sa_session = self.app.model.session
        sa_session.commit()
        output_datasets = {
            "out_file1": output_dataset,
        }
        command = self.metadata_command(output_datasets)
        self._write_output_dataset_contents(output_dataset, ">seq1\nGCTGCATG\n")
        self._write_job_files()
        self.exec_metadata_command(command)
        assert self.metadata_compute_strategy
        metadata_set_successfully = self.metadata_compute_strategy.external_metadata_set_successfully(
            output_dataset,
            "out_file1",
            sa_session,
            working_directory=self.job_working_directory,
        )
        assert metadata_set_successfully
        self.metadata_compute_strategy.load_metadata(
            output_dataset,
            "out_file1",
            sa_session,
            working_directory=self.job_working_directory,
        )
        assert output_dataset.metadata.data_lines == 2
        assert output_dataset.metadata.sequences == 1

    def test_primary_dataset_output_extension_directory(self):
        self.app.config.metadata_strategy = "directory"
        self._test_primary_dataset_output_extension()

    def _test_primary_dataset_output_extension(self):
        source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/for_workflows/cat.xml")
        self._init_tool_for_path(source_file_name)
        self.tool.uses_tool_provided_metadata = True
        # setting extension to 'auto' here, results in the extension specified in
        # galaxy.json (below) being respected.
        output_dataset = self._create_output_dataset(
            extension="auto",
        )
        sa_session = self.app.model.session
        sa_session.commit()
        output_datasets = {
            "out_file1": output_dataset,
        }
        command = self.metadata_command(output_datasets)
        self._write_galaxy_json(
            f"""{{"type": "dataset", "dataset_id": "{output_dataset.dataset.id}", "name": "my dynamic name", "ext": "fasta", "info": "my dynamic info"}}"""
        )
        self._write_output_dataset_contents(output_dataset, ">seq1\nGCTGCATG\n")
        self._write_job_files()
        self.exec_metadata_command(command)
        assert self.metadata_compute_strategy
        metadata_set_successfully = self.metadata_compute_strategy.external_metadata_set_successfully(
            output_dataset,
            "out_file1",
            sa_session,
            working_directory=self.job_working_directory,
        )
        assert metadata_set_successfully
        output_dataset.extension = "fasta"  # gets done in job finish...
        self.metadata_compute_strategy.load_metadata(
            output_dataset,
            "out_file1",
            sa_session,
            working_directory=self.job_working_directory,
        )
        assert output_dataset.metadata.data_lines == 2
        assert output_dataset.metadata.sequences == 1

    def test_primary_dataset_output_metadata_override_directory(self):
        self.app.config.metadata_strategy = "directory"
        self._test_primary_dataset_output_metadata_override()

    def test_primary_dataset_output_metadata_override_extended(self):
        self.app.config.metadata_strategy = "extended"
        self._test_primary_dataset_output_metadata_override()

    def test_primary_dataset_discovery_extended(self):
        self.app.config.metadata_strategy = "extended"
        self._init_tool(tool_contents="""
<tool id="discover_primary" name="discover_primary" version="1.0">
  <command>echo unused</command>
  <inputs />
  <outputs>
    <data name="report" format="tabular">
      <discover_datasets pattern="(?P&lt;designation&gt;.+)\\.part\\.tabular" ext="tabular" visible="true" />
    </data>
  </outputs>
</tool>
""")
        output_dataset = self._create_output_dataset(extension="tabular")
        self.app.model.session.commit()
        command = self.metadata_command({"report": output_dataset})
        self._write_output_dataset_contents(output_dataset, "fixed\n")
        self._write_work_dir_file("one.part.tabular", "one\ntwo\n")
        self._write_galaxy_json(
            json.dumps(
                {
                    "report": {
                        "datasets": [
                            {
                                "filename": "one.part.tabular",
                                "name": "custom name",
                                "ext": "tabular",
                                "info": "custom info",
                                "dbkey": "hg19",
                                "metadata": {"data_lines": 10},
                            }
                        ]
                    }
                }
            )
        )
        self._write_job_files()
        self.exec_metadata_command(command)

        export_directory = Path(self.job_working_directory) / "metadata" / "outputs_populated"
        datasets = json.loads((export_directory / "datasets_attrs.txt").read_text())
        assert len(datasets) == 2
        discovered_dataset = next(dataset for dataset in datasets if dataset["designation"] == "one")
        assert discovered_dataset["name"] == "custom name"
        assert discovered_dataset["info"] == "custom info"
        assert discovered_dataset["designation"] == "one"
        assert discovered_dataset["metadata"]["data_lines"] == 10

        import_options = model.store.ImportOptions(allow_dataset_object_edit=True, allow_edit=True)
        import_store = model.store.get_import_model_store_for_directory(
            export_directory,
            app=self.app,
            import_options=import_options,
            user=self.job.user,
            tag_handler=self.app.tag_handler.create_tag_handler_session(self.job.galaxy_session),
        )
        import_store.perform_import(history=self.history, job=self.job)
        discovered_hda = next(dataset for dataset in self.history.datasets if dataset.designation == "one")
        assert discovered_hda.name == "custom name"
        assert discovered_hda.metadata.data_lines == 10

    def test_primary_dataset_discovery_with_file_metadata_extended(self):
        self.app.config.metadata_strategy = "extended"
        self._init_tool(tool_contents="""
<tool id="discover_primary_bam" name="discover_primary_bam" version="1.0">
  <command>echo unused</command>
  <inputs />
  <outputs>
    <data name="report" format="txt">
      <discover_datasets pattern="(?P&lt;designation&gt;.+)\\.part\\.bam" ext="bam" visible="true" />
    </data>
  </outputs>
</tool>
""")
        output_dataset = self._create_output_dataset(extension="txt")
        self.app.model.session.commit()
        command = self.metadata_command({"report": output_dataset})
        self._write_output_dataset_contents(output_dataset, "fixed\n")
        Path(self.tool_working_directory, "one.part.bam").write_bytes(
            Path(galaxy_directory(), "test-data", "1.bam").read_bytes()
        )
        self._write_job_files()

        self.exec_metadata_command(command)

        export_directory = Path(self.job_working_directory) / "metadata" / "outputs_populated"
        datasets = json.loads((export_directory / "datasets_attrs.txt").read_text())
        discovered_dataset = next(dataset for dataset in datasets if dataset["designation"] == "one")
        serialized_index = discovered_dataset["metadata"]["bam_index"]
        assert serialized_index["model_class"] == "MetadataFile"
        if "file_name" in serialized_index:
            assert (export_directory / serialized_index["file_name"]).stat().st_size > 0

        import_options = model.store.ImportOptions(allow_dataset_object_edit=True, allow_edit=True)
        import_store = model.store.get_import_model_store_for_directory(
            export_directory,
            app=self.app,
            import_options=import_options,
            user=self.job.user,
            tag_handler=self.app.tag_handler.create_tag_handler_session(self.job.galaxy_session),
        )
        import_store.perform_import(history=self.history, job=self.job)
        discovered_hda = next(dataset for dataset in self.history.datasets if dataset.designation == "one")
        assert discovered_hda.metadata.bam_index.name == "bam_index"
        assert Path(discovered_hda.metadata.bam_index.get_file_name()).stat().st_size > 0

    def test_assign_primary_dataset_discovery_extended(self):
        self.app.config.metadata_strategy = "extended"
        source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/multi_output_assign_primary.xml")
        self._init_tool_for_path(source_file_name)
        sample = self._create_output_dataset(extension="tabular")
        other = self._create_output_dataset(extension="txt")
        self.app.model.session.commit()
        command = self.metadata_command({"sample": sample, "other": other})
        self._write_output_dataset_contents(sample, "original\n")
        self._write_output_dataset_contents(other, "other\n")
        for index in (1, 2, 3):
            self._write_work_dir_file(f"sample{index}.report.tsv", f"{index}\n")
        self._write_job_files()
        self.exec_metadata_command(command)

        export_directory = Path(self.job_working_directory) / "metadata" / "outputs_populated"
        datasets = json.loads((export_directory / "datasets_attrs.txt").read_text())
        assert [dataset["designation"] for dataset in datasets if "encoded_id" in dataset] == ["sample2", "sample3"]
        sample_attributes = next(dataset for dataset in datasets if dataset.get("id") == sample.id)
        assert sample_attributes["name"].endswith("(sample1)")
        assert sample_attributes["metadata"]["data_lines"] == 1

    def _test_primary_dataset_output_metadata_override(self):
        source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/for_workflows/cat.xml")
        self._init_tool_for_path(source_file_name)
        self.tool.uses_tool_provided_metadata = True
        output_dataset = self._create_output_dataset(
            extension="auto",
        )
        sa_session = self.app.model.session
        sa_session.commit()
        output_datasets = {
            "out_file1": output_dataset,
        }
        command = self.metadata_command(output_datasets)
        self._write_galaxy_json(
            f"""{{"type": "dataset", "dataset_id": "{output_dataset.dataset.id}", "name": "my dynamic name", "ext": "fasta", "info": "my dynamic info", "metadata": {{"sequences": 42}}}}"""
        )
        self._write_output_dataset_contents(output_dataset, ">seq1\nGCTGCATG\n")
        self._write_job_files()
        self.exec_metadata_command(command)
        assert self.metadata_compute_strategy
        metadata_set_successfully = self.metadata_compute_strategy.external_metadata_set_successfully(
            output_dataset,
            "out_file1",
            sa_session,
            working_directory=self.job_working_directory,
        )
        assert metadata_set_successfully
        output_dataset.extension = "fasta"  # get done in job finish...
        self.metadata_compute_strategy.load_metadata(
            output_dataset,
            "out_file1",
            sa_session,
            working_directory=self.job_working_directory,
        )
        assert output_dataset.metadata.data_lines == 2
        assert output_dataset.metadata.sequences == 42

    def test_extended_metadata_ignores_metadata_file_when_disabled(self):
        self.app.config.metadata_strategy = "extended"
        source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/for_workflows/cat.xml")
        self._init_tool_for_path(source_file_name)
        self.tool.uses_tool_provided_metadata = False
        output_dataset = self._create_output_dataset(extension="fasta")
        self.app.model.session.commit()
        command = self.metadata_command({"out_file1": output_dataset})
        self._write_galaxy_json(
            f"""{{"type": "dataset", "dataset_id": "{output_dataset.dataset.id}", "metadata": {{"sequences": 42}}}}"""
        )
        self._write_output_dataset_contents(output_dataset, ">seq1\nGCTGCATG\n")
        self._write_job_files()

        self.exec_metadata_command(command)

        assert self.metadata_compute_strategy
        assert self.metadata_compute_strategy.external_metadata_set_successfully(
            output_dataset,
            "out_file1",
            self.app.model.session,
            working_directory=self.job_working_directory,
        )
        self.metadata_compute_strategy.load_metadata(
            output_dataset,
            "out_file1",
            self.app.model.session,
            working_directory=self.job_working_directory,
        )
        assert output_dataset.metadata.sequences == 1

    def test_list_discovery_extended(self):
        self.app.config.metadata_strategy = "extended"
        source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/collection_split_on_column.xml")
        self._init_tool_for_path(source_file_name)
        collection = model.DatasetCollection(populated=False)
        collection.collection_type = "list"
        output_dataset_collection = self._create_output_dataset_collection(
            collection=collection,
        )
        assert output_dataset_collection.collection
        command = self.metadata_command({}, {"split_output": output_dataset_collection})
        outputs_directory = Path(self.tool_working_directory) / "outputs"
        outputs_directory.mkdir()
        (outputs_directory / "1.tabular").write_text("1\n2\n3")
        (outputs_directory / "2.tabular").write_text("4\n5\n6")
        self._write_job_files()
        self.exec_metadata_command(command)

        export_directory = Path(self.job_working_directory) / "metadata" / "outputs_populated"
        datasets = json.loads((export_directory / "datasets_attrs.txt").read_text())
        collections = json.loads((export_directory / "collections_attrs.txt").read_text())
        assert [(dataset["name"], dataset["extension"]) for dataset in datasets] == [
            ("1", "tabular"),
            ("2", "tabular"),
        ]
        assert [dataset["metadata"]["data_lines"] for dataset in datasets] == [3, 3]
        elements = collections[0]["collection"]["elements"]
        assert [element["element_identifier"] for element in elements] == ["1", "2"]
        assert [element["hda"]["encoded_id"] for element in elements] == [dataset["encoded_id"] for dataset in datasets]

        import_options = model.store.ImportOptions(allow_dataset_object_edit=True, allow_edit=True)
        import_store = model.store.get_import_model_store_for_directory(
            export_directory,
            app=self.app,
            import_options=import_options,
            user=self.job.user,
            tag_handler=self.app.tag_handler.create_tag_handler_session(self.job.galaxy_session),
        )
        import_store.perform_import(history=self.history, job=self.job)
        self.app.model.session.refresh(output_dataset_collection)
        assert [element.element_identifier for element in output_dataset_collection.collection.elements] == ["1", "2"]
        assert [dataset.metadata.data_lines for dataset in output_dataset_collection.dataset_instances] == [3, 3]

    def test_list_discovery_with_sniffed_elements_extended(self):
        self.app.config.metadata_strategy = "extended"
        self._init_tool(tool_contents="""
<tool id="discover_sniffed_collection" name="discover_sniffed_collection" version="1.0">
  <command>echo unused</command>
  <inputs />
  <outputs>
    <collection name="sniffed" type="list">
      <discover_datasets pattern="__name__" ext="_sniff_" directory="outputs" />
    </collection>
  </outputs>
</tool>
""")
        collection = model.DatasetCollection(collection_type="list", populated=False)
        output_dataset_collection = self._create_output_dataset_collection(collection=collection)
        command = self.metadata_command({}, {"sniffed": output_dataset_collection})
        outputs_directory = Path(self.tool_working_directory) / "outputs"
        outputs_directory.mkdir()
        (outputs_directory / "one").write_text(">seq1\nGCTGCATG\n")
        (outputs_directory / "two").write_text(">seq2\nGCTG\n")
        self._write_job_files()

        self.exec_metadata_command(command)

        export_directory = Path(self.job_working_directory) / "metadata" / "outputs_populated"
        datasets = json.loads((export_directory / "datasets_attrs.txt").read_text())
        assert [dataset["extension"] for dataset in datasets] == ["fasta", "fasta"]
        assert [dataset["metadata"]["sequences"] for dataset in datasets] == [1, 1]

        import_options = model.store.ImportOptions(allow_dataset_object_edit=True, allow_edit=True)
        import_store = model.store.get_import_model_store_for_directory(
            export_directory,
            app=self.app,
            import_options=import_options,
            user=self.job.user,
            tag_handler=self.app.tag_handler.create_tag_handler_session(self.job.galaxy_session),
        )
        import_store.perform_import(history=self.history, job=self.job)
        self.app.model.session.refresh(output_dataset_collection)
        assert [dataset.extension for dataset in output_dataset_collection.dataset_instances] == ["fasta", "fasta"]
        assert [dataset.metadata.sequences for dataset in output_dataset_collection.dataset_instances] == [1, 1]

    def test_list_discovery_into_bare_dataset_collection_extended(self):
        self.app.config.metadata_strategy = "extended"
        source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/collection_split_on_column.xml")
        self._init_tool_for_path(source_file_name)
        collection = model.DatasetCollection(collection_type="list", populated=False)
        self.app.model.session.add(collection)
        self.app.model.session.commit()
        command = self.metadata_command({}, {"split_output": collection})
        outputs_directory = Path(self.tool_working_directory) / "outputs"
        outputs_directory.mkdir()
        (outputs_directory / "1.tabular").write_text("1\n2\n3")
        (outputs_directory / "2.tabular").write_text("4\n5\n6")
        self._write_job_files()

        self.exec_metadata_command(command)

        export_directory = Path(self.job_working_directory) / "metadata" / "outputs_populated"
        datasets = json.loads((export_directory / "datasets_attrs.txt").read_text())
        exported_collection = json.loads((export_directory / "collections_attrs.txt").read_text())[0]
        assert exported_collection["model_class"] == "DatasetCollection"
        assert "collection" not in exported_collection
        assert [element["element_identifier"] for element in exported_collection["elements"]] == ["1", "2"]
        assert [dataset["metadata"]["data_lines"] for dataset in datasets] == [3, 3]

        import_options = model.store.ImportOptions(allow_dataset_object_edit=True, allow_edit=True)
        import_store = model.store.get_import_model_store_for_directory(
            export_directory,
            app=self.app,
            import_options=import_options,
            user=self.job.user,
            tag_handler=self.app.tag_handler.create_tag_handler_session(self.job.galaxy_session),
        )
        import_store.perform_import(history=self.history, job=self.job)
        self.app.model.session.refresh(collection)
        assert [element.element_identifier for element in collection.elements] == ["1", "2"]
        assert [dataset.metadata.data_lines for dataset in collection.dataset_instances] == [3, 3]

    def test_nested_collection_discovery_extended(self):
        self.app.config.metadata_strategy = "extended"
        source_file_name = os.path.join(
            galaxy_directory(), "test/functional/tools/collection_creates_dynamic_list_of_pairs.xml"
        )
        self._init_tool_for_path(source_file_name)
        collection = model.DatasetCollection(populated=False)
        collection.collection_type = "list:paired"
        output_dataset_collection = self._create_output_dataset_collection(collection=collection)
        command = self.metadata_command({}, {"list_output": output_dataset_collection})
        for sample, contents in (("samp1", ("A", "B")), ("samp2", ("C", "D"))):
            self._write_work_dir_file(f"{sample}_forward.fq", f"{contents[0]}\n")
            self._write_work_dir_file(f"{sample}_reverse.fq", f"{contents[1]}\n")
        self._write_job_files()
        self.exec_metadata_command(command)

        export_directory = Path(self.job_working_directory) / "metadata" / "outputs_populated"
        collections = json.loads((export_directory / "collections_attrs.txt").read_text())
        outer_elements = collections[0]["collection"]["elements"]
        assert [element["element_identifier"] for element in outer_elements] == ["samp1", "samp2"]
        assert [
            [element["element_identifier"] for element in outer_element["child_collection"]["elements"]]
            for outer_element in outer_elements
        ] == [["forward", "reverse"], ["forward", "reverse"]]

        import_options = model.store.ImportOptions(allow_dataset_object_edit=True, allow_edit=True)
        import_store = model.store.get_import_model_store_for_directory(
            export_directory,
            app=self.app,
            import_options=import_options,
            user=self.job.user,
            tag_handler=self.app.tag_handler.create_tag_handler_session(self.job.galaxy_session),
        )
        import_store.perform_import(history=self.history, job=self.job)
        self.app.model.session.refresh(output_dataset_collection)
        assert [element.element_identifier for element in output_dataset_collection.collection.elements] == [
            "samp1",
            "samp2",
        ]
        assert all(
            [element.element_identifier for element in outer_element.child_collection.elements]
            == ["forward", "reverse"]
            for outer_element in output_dataset_collection.collection.elements
        )

    @pytest.mark.parametrize("strategy", ["directory", "extended"])
    def test_collection_input_sources(self, strategy):
        self.app.config.metadata_strategy = strategy
        source = UserToolSource.model_validate(
            {
                "class": "GalaxyUserTool",
                "id": "collection_sources",
                "name": "Collection sources",
                "version": "1.0",
                "container": "busybox",
                "shell_command": "true",
                "inputs": [{"name": "input", "type": "data", "format": ["interval"]}],
                "outputs": [
                    {
                        "name": "output",
                        "type": "collection",
                        "collection_type": "list",
                        "format": "txt",
                        "format_source": "input",
                        "metadata_source": "input",
                        "discover_datasets": [
                            {"pattern": "(?P<name>inherited)"},
                            {"pattern": "(?P<name>explicit)", "format": "tabular"},
                            {"pattern": r"(?P<name>captured)\.(?P<ext>txt)", "format": "tabular"},
                        ],
                    }
                ],
            }
        )
        self.tool = create_tool_from_source(self.app, YamlToolSource(source.model_dump(by_alias=True)))
        input_dataset = self._create_output_dataset(extension="interval")
        input_dataset.init_meta()
        input_dataset.metadata.chromCol = 3
        input_dataset.metadata.startCol = 1
        input_dataset.metadata.endCol = 2
        input_dataset.metadata.data_lines = 42
        self._write_output_dataset_contents(input_dataset, "10\t20\tchr1\n")
        self.job.add_input_dataset("input", input_dataset)
        hdca = self._create_output_dataset_collection(
            collection=model.DatasetCollection(collection_type="list", populated=False)
        )
        for filename in ("inherited", "explicit", "captured.txt"):
            self._write_work_dir_file(filename, "10\t20\tchr1\n")
        if strategy == "extended":
            command = self.metadata_command({}, {"output": hdca})
            self._write_job_files()
            self.exec_metadata_command(command)
            populated_path = os.path.join(self.job_working_directory, "metadata", "outputs_populated")
            with open(os.path.join(populated_path, "datasets_attrs.txt")) as f:
                datasets = json.load(f)
            extensions = {dataset["extension"] for dataset in datasets}
            metadata = next(dataset["metadata"] for dataset in datasets if dataset["extension"] == "interval")
        else:
            self.tool.discover_outputs(
                {},
                {"output": hdca},
                NullToolProvidedMetadata(),
                self.tool_working_directory,
                self.job,
                input_ext="interval",
                input_dbkey="?",
                inp_data={"input": input_dataset},
            )
            self.app.model.session.flush()
            assert hdca.collection.populated
            datasets = hdca.collection.dataset_instances
            extensions = {dataset.extension for dataset in datasets}
            metadata = next(dataset.metadata for dataset in datasets if dataset.extension == "interval")
        assert len(datasets) == 3
        assert extensions == {"interval", "tabular", "txt"}
        assert (metadata["chromCol"], metadata["startCol"], metadata["endCol"]) == (3, 1, 2)
        assert metadata["data_lines"] == 1

    def test_extended_metadata_rejects_unprivileged_tool_unnamed_outputs(self):
        self.app.config.metadata_strategy = "extended"
        source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/for_workflows/cat.xml")
        self._init_tool_for_path(source_file_name)
        self.tool.uses_tool_provided_metadata = True
        self.tool.allows_unnamed_outputs = False
        output_dataset = self._create_output_dataset(extension="txt")
        self.app.model.session.commit()
        command = self.metadata_command({"out_file1": output_dataset})
        replacement_name = "replacement.txt"
        self._write_work_dir_file(replacement_name, "replacement")
        self._write_galaxy_json(
            json.dumps(
                {
                    "__unnamed_outputs": [
                        {
                            "destination": {"type": "hdas"},
                            "elements": [{"filename": replacement_name, "name": "replacement"}],
                        }
                    ]
                }
            )
        )
        self._write_output_dataset_contents(output_dataset, "original")
        self._write_job_files()

        self.exec_metadata_command(command)

        self._assert_extended_metadata_security_failure(
            output_dataset, "This tool is not permitted to create unnamed outputs."
        )

    def test_extended_metadata_reports_invalid_unnamed_output(self):
        self.app.config.metadata_strategy = "extended"
        source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/for_workflows/cat.xml")
        self._init_tool_for_path(source_file_name)
        self.tool.uses_tool_provided_metadata = True
        self.tool.allows_unnamed_outputs = True
        output_dataset = self._create_output_dataset(extension="txt")
        self.app.model.session.commit()
        command = self.metadata_command({"out_file1": output_dataset})
        self._write_galaxy_json(
            json.dumps(
                {
                    "__unnamed_outputs": [
                        {
                            "destination": {"type": "hdca"},
                            "elements": [],
                            "name": "missing collection type",
                        }
                    ]
                }
            )
        )
        self._write_output_dataset_contents(output_dataset, "original")
        self._write_job_files()

        self.exec_metadata_command(command)

        jobs_attrs_path = os.path.join(
            self.job_working_directory,
            "metadata",
            "outputs_populated",
            "jobs_attrs.txt",
        )
        with open(jobs_attrs_path) as jobs_attrs_file:
            jobs_attrs = json.load(jobs_attrs_file)
        assert len(jobs_attrs) == 1
        assert jobs_attrs[0]["state"] == model.Job.states.ERROR
        discovery_messages = [
            message for message in jobs_attrs[0]["job_messages"] if message["type"] == "output_discovery"
        ]
        assert len(discovery_messages) == 1
        assert discovery_messages[0]["desc"] == "Failed to collect job outputs: Must specify an HDCA collection_type"

    def test_extended_metadata_rejects_dynamic_tool_spoofing_data_fetch(self):
        self.app.config.metadata_strategy = "extended"
        source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/for_workflows/cat.xml")
        self._init_tool_for_path(source_file_name)
        self.tool.uses_tool_provided_metadata = True
        self.tool.old_id = "__DATA_FETCH__"
        self.tool.dynamic_tool_id = 1
        self.job.tool_id = "__DATA_FETCH__"
        self.job.dynamic_tool_id = 1
        output_dataset = self._create_output_dataset(extension="txt")
        self.app.model.session.commit()
        command = self.metadata_command({"out_file1": output_dataset})
        outside_path = os.path.join(self.test_directory, "outside.txt")
        with open(outside_path, "w") as outside_file:
            outside_file.write("outside")
        self._write_galaxy_json(
            json.dumps(
                {
                    "__unnamed_outputs": [
                        {
                            "destination": {"type": "hdas"},
                            "elements": [
                                {
                                    "filename": outside_path,
                                    "link_data_only": True,
                                    "name": "external link",
                                }
                            ],
                        }
                    ]
                }
            )
        )
        self._write_output_dataset_contents(output_dataset, "original")
        self._write_job_files()

        self.exec_metadata_command(command)

        self._assert_extended_metadata_security_failure(
            output_dataset,
            "This tool is not permitted to collect output files from outside its working directory.",
            metadata_set_successfully=True,
        )

    def _assert_extended_metadata_security_failure(
        self, output_dataset, expected_message, metadata_set_successfully=False
    ):
        assert self.metadata_compute_strategy
        assert metadata_set_successfully is self.metadata_compute_strategy.external_metadata_set_successfully(
            output_dataset,
            "out_file1",
            self.app.model.session,
            working_directory=self.job_working_directory,
        )
        jobs_attrs_path = os.path.join(
            self.job_working_directory,
            "metadata",
            "outputs_populated",
            "jobs_attrs.txt",
        )
        with open(jobs_attrs_path) as jobs_attrs_file:
            jobs_attrs = json.load(jobs_attrs_file)
        assert len(jobs_attrs) == 1
        assert jobs_attrs[0]["state"] == model.Job.states.ERROR
        security_messages = [
            message for message in jobs_attrs[0]["job_messages"] if message["type"] == "output_collection_security"
        ]
        assert len(security_messages) == 1
        assert security_messages[0]["desc"] == expected_message

    def test_unnamed_outputs_extended(self):
        self.app.config.metadata_strategy = "extended"
        source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/for_workflows/cat.xml")
        self._init_tool_for_path(source_file_name)
        self.tool.uses_tool_provided_metadata = True
        self.tool.allows_unnamed_outputs = True
        command = self.metadata_command({})
        self._write_work_dir_file("standalone.txt", "standalone\n")
        self._write_work_dir_file("first.txt", "first\n")
        self._write_work_dir_file("second.txt", "second\n")
        self._write_galaxy_json(
            json.dumps(
                {
                    "__unnamed_outputs": [
                        {
                            "destination": {"type": "hdas"},
                            "elements": [
                                {
                                    "filename": "standalone.txt",
                                    "ext": "txt",
                                    "name": "standalone",
                                }
                            ],
                        },
                        {
                            "destination": {"type": "hdca"},
                            "name": "unnamed list",
                            "collection_type": "sample_sheet",
                            "column_definitions": [
                                {
                                    "type": "int",
                                    "name": "replicate number",
                                    "optional": False,
                                    "default_value": 0,
                                }
                            ],
                            "rows": {"first": [1], "second": [2]},
                            "elements": [
                                {"filename": "first.txt", "ext": "txt", "name": "first"},
                                {"filename": "second.txt", "ext": "txt", "name": "second"},
                            ],
                        },
                    ]
                }
            )
        )
        self._write_job_files()
        self.exec_metadata_command(command)

        export_directory = Path(self.job_working_directory) / "metadata" / "outputs_populated"
        datasets = json.loads((export_directory / "datasets_attrs.txt").read_text())
        collections = json.loads((export_directory / "collections_attrs.txt").read_text())
        assert [dataset["name"] for dataset in datasets] == ["standalone", "first", "second"]
        assert collections[0]["display_name"] == "unnamed list"
        assert [element["element_identifier"] for element in collections[0]["collection"]["elements"]] == [
            "first",
            "second",
        ]
        assert [element["columns"] for element in collections[0]["collection"]["elements"]] == [[1], [2]]

        import_options = model.store.ImportOptions(allow_dataset_object_edit=True, allow_edit=True)
        import_store = model.store.get_import_model_store_for_directory(
            export_directory,
            app=self.app,
            import_options=import_options,
            user=self.job.user,
            tag_handler=self.app.tag_handler.create_tag_handler_session(self.job.galaxy_session),
        )
        import_store.perform_import(history=self.history, job=self.job)
        assert [dataset.name for dataset in self.history.datasets] == ["standalone", "first", "second"]
        assert [collection.name for collection in self.history.dataset_collections] == ["unnamed list"]

    def _create_output_dataset_collection(self, **kwd):
        output_dataset_collection = model.HistoryDatasetCollectionAssociation(**kwd)
        self.history.add_dataset_collection(output_dataset_collection)
        assert output_dataset_collection.collection
        session = self.app.model.session
        session.add(output_dataset_collection)
        session.commit()
        return output_dataset_collection

    def _create_output_dataset(self, **kwd):
        output_dataset = model.HistoryDatasetAssociation(
            sa_session=self.app.model.session, create_dataset=True, flush=True, **kwd
        )
        self.history.add_dataset(output_dataset)
        ObjectStorePopulator(self.app, user=self.job.user).set_object_store_id(output_dataset)
        return output_dataset

    def _write_work_dir_file(self, filename, contents):
        with open(os.path.join(self.tool_working_directory, filename), "w") as f:
            f.write(contents)

    def _write_output_dataset_contents(self, output_dataset, contents):
        with open(output_dataset.dataset.get_file_name(), "w") as f:
            f.write(contents)

    def _write_galaxy_json(self, contents):
        job_metadata = os.path.join(self.tool_working_directory, self.tool.provided_metadata_file)
        with open(job_metadata, "w") as f:
            f.write(contents)

    def _write_job_files(self, stdout="tool stdout", stderr="tool stderr"):
        with open(os.path.join(self.job_working_directory, "tool_script.sh"), "w") as f:
            f.write("echo hi")
        with open(os.path.join(self.job_working_directory, "tool_stdout"), "w") as f:
            f.write(stdout)
        with open(os.path.join(self.job_working_directory, "tool_stderr"), "w") as f:
            f.write(stderr)

    def metadata_command(self, output_datasets, output_collections=None):
        output_collections = output_collections or {}
        metadata_compute_strategy = get_metadata_compute_strategy(self.app.config, self.job.id)
        self.metadata_compute_strategy = metadata_compute_strategy

        exec_dir = None
        dataset_files_path = model.Dataset.file_path
        config_root = self.app.config.root
        config_file = None
        datatypes_config = os.path.join(self.job_working_directory, "metadata", "registry.xml")
        safe_makedirs(os.path.join(self.job_working_directory, "metadata"))
        self.app.datatypes_registry.to_xml_file(path=datatypes_config)
        job_metadata = os.path.join(self.tool_working_directory, self.tool.provided_metadata_file)
        output_fnames = [
            DatasetPath(o.dataset.id, o.dataset.get_file_name(sync_cache=False), None) for o in output_datasets.values()
        ]
        command = metadata_compute_strategy.setup_external_metadata(
            output_datasets,
            output_collections,
            self.app.model.session,
            uses_tool_provided_metadata=self.tool.uses_tool_provided_metadata,
            allows_unnamed_outputs=self.tool.allows_unnamed_outputs,
            allows_external_output_paths=self.tool.allows_external_output_paths,
            exec_dir=exec_dir,
            tmp_dir=self.job_working_directory,  # set in jobs/runners.py - better if was default.
            dataset_files_path=dataset_files_path,
            config_root=config_root,
            config_file=config_file,
            datatypes_config=datatypes_config,
            job_metadata=job_metadata,
            output_fnames=output_fnames,
            tool=self.tool,
            job=self.job,
            object_store_conf=self.app.object_store.to_dict(),
            max_metadata_value_size=10000,
        )
        return command

    def exec_metadata_command(self, command):
        with (
            open(self.stdout_path, "wb") as stdout_file,
            open(self.stderr_path, "wb") as stderr_file,
        ):
            _environ = os.environ.copy()
            _environ["PYTHONPATH"] = os.path.abspath("lib")
            _environ["PATH"] = os.pathsep.join((str(Path(sys.executable).parent), _environ.get("PATH", "")))
            _environ[LAZY_IMPORTS_ENV] = self.metadata_import_mode
            proc = subprocess.Popen(
                args=command,
                shell=True,
                cwd=self.job_working_directory,
                env=_environ,
                stdout=stdout_file,
                stderr=stderr_file,
            )
            ret = proc.wait()
        self.print_command_output()
        assert ret == 0
        return ret

    def print_command_output(self):
        print(">unit test of external metadata setting (command standard output)")
        print(open(self.stdout_path).read())
        print(">unit test of external metadata setting (command standard error)")
        print(open(self.stderr_path).read())

    @property
    def stdout_path(self):
        return os.path.join(self.test_directory, "stdout")

    @property
    def stderr_path(self):
        return os.path.join(self.test_directory, "stderr")
