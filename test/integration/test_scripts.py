"""Integration tests for various scripts in scripts/."""

import json
import os
import subprocess
import tempfile

import yaml

from galaxy import model
from galaxy.util import (
    galaxy_directory,
    unicodify,
)
from galaxy_test.base.populators import DatasetPopulator
from galaxy_test.driver import integration_util


class BaseScriptsIntegrationTestCase(integration_util.IntegrationTestCase):
    dataset_populator: DatasetPopulator

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)
        self.config_dir = tempfile.mkdtemp()

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        cls._raw_config = config

    def _hda(self, dataset) -> model.HistoryDatasetAssociation:
        hda = self._app.model.session.get(model.HistoryDatasetAssociation, self._app.security.decode_id(dataset["id"]))
        assert hda
        return hda

    def _metadata_files_with_same_uuid(self, *datasets) -> tuple[list[int], str]:
        """Give each dataset a metadata file row with the same uuid. Returns their ids and shared path."""
        session = self._app.model.session
        first = model.MetadataFile(dataset=self._hda(datasets[0]), name="bam_index")
        rows = [first] + [
            model.MetadataFile(dataset=self._hda(dataset), name="bam_index", uuid=first.uuid)
            for dataset in datasets[1:]
        ]
        session.add_all(rows)
        session.commit()
        path = first.get_file_name()
        assert all(row.get_file_name() == path for row in rows)
        with open(path, "wb") as f:
            f.write(b"index")
        return [row.id for row in rows], path

    def _metadata_file(self, row_id: int) -> model.MetadataFile:
        session = self._app.model.session
        session.rollback()
        session.expire_all()
        metadata_file = session.get(model.MetadataFile, row_id)
        assert metadata_file
        return metadata_file

    def _scripts_check_argparse_help(self, script):
        # Test imports and argparse response to --help with 0 exit code.
        output = self._scripts_check_output(script, ["--help"])
        # Test -h, --help in printed output message.
        assert "-h, --help" in output

    def _scripts_check_output(self, script, args):
        cwd = galaxy_directory()
        cmd = ["python", os.path.join(cwd, "scripts", script)] + args
        clean_env = {
            "PATH": os.environ.get("PATH", None),
        }  # Don't let testing environment variables interfere with config.
        try:
            return unicodify(subprocess.check_output(cmd, cwd=cwd, env=clean_env))
        except Exception as e:
            if isinstance(e, subprocess.CalledProcessError):
                raise Exception(f"{unicodify(e)}\nOutput was:\n{unicodify(e.output)}")
            raise

    def write_config_file(self):
        config_dir = self.config_dir
        path = os.path.join(config_dir, "galaxy.yml")
        self._test_driver.temp_directories.extend([config_dir])
        config = self._raw_config
        # Update config dict with database_connection, which might be set through env variables
        config["database_connection"] = self._app.config.database_connection
        with open(path, "w") as f:
            yaml.dump({"galaxy": config}, f)

        return path

    def _pgcleanup_check_output(self, extra_args: list[str]) -> str:
        config_file = self.write_config_file()
        output = self._scripts_check_output("cleanup_datasets/pgcleanup.py", ["-c", config_file] + extra_args)
        print(output)
        return output

    def is_purged(self, history_id: str, dataset) -> bool:
        # set wait=False to prevent errored dataset from erroring out
        if isinstance(dataset, str):
            details_response = self.dataset_populator.get_history_dataset_details(
                history_id, dataset_id=dataset, wait=False
            )
        else:
            details_response = self.dataset_populator.get_history_dataset_details(
                history_id, dataset=dataset, wait=False
            )
        return details_response["purged"]


class TestScriptsIntegration(BaseScriptsIntegrationTestCase):
    def test_helper(self):
        script = "helper.py"
        self._scripts_check_argparse_help(script)

        history_id = self.dataset_populator.new_history()
        dataset = self.dataset_populator.new_dataset(history_id, wait=True)
        dataset_id = dataset["id"]
        config_file = self.write_config_file()
        output = self._scripts_check_output(script, ["-c", config_file, "--decode-id", dataset_id])
        assert "Decoded " in output

    def test_cleanup(self):
        script = "cleanup_datasets/cleanup_datasets.py"
        self._scripts_check_argparse_help(script)

        history_id = self.dataset_populator.new_history()
        delete_response = self.dataset_populator._delete(f"histories/{history_id}")
        assert delete_response.status_code == 200
        assert delete_response.json()["purged"] is False
        config_file = self.write_config_file()
        output = self._scripts_check_output(script, ["-c", config_file, "--days", "0", "--purge_histories"])
        print(output)
        history_response = self.dataset_populator._get(f"histories/{history_id}")
        assert history_response.status_code == 200
        assert history_response.json()["purged"] is True, history_response.json()

    def test_cleanup_keeps_metadata_file_a_live_row_names(self):
        history_id = self.dataset_populator.new_history()
        live = self.dataset_populator.new_dataset(history_id, content="live", wait=True)
        duplicate = self.dataset_populator.new_dataset(history_id, content="duplicate", wait=True)
        (live_row_id, duplicate_row_id), path = self._metadata_files_with_same_uuid(live, duplicate)
        args = ["-c", self.write_config_file(), "--days", "0", "--delete_datasets", "--remove_from_disk"]

        self.dataset_populator.delete_dataset(history_id, duplicate["id"])
        self._scripts_check_output("cleanup_datasets/cleanup_datasets.py", args)
        assert self._metadata_file(duplicate_row_id).deleted
        assert not self._metadata_file(live_row_id).deleted
        with open(path, "rb") as f:
            assert f.read() == b"index"

        self.dataset_populator.delete_dataset(history_id, live["id"])
        self._scripts_check_output("cleanup_datasets/cleanup_datasets.py", args)
        assert self._metadata_file(live_row_id).purged
        # The script recreates an empty file after removing it, by logging its name.
        assert not os.path.exists(path) or os.path.getsize(path) == 0

    def test_admin_cleanup_datasets(self):
        script = "cleanup_datasets/admin_cleanup_datasets.py"
        self._scripts_check_argparse_help(script)

    def test_set_user_disk_usage(self):
        script = "set_user_disk_usage.py"
        self._scripts_check_argparse_help(script)

        history_id = self.dataset_populator.new_history()
        self.dataset_populator.new_dataset(history_id, wait=True)
        config_file = self.write_config_file()
        output = self._scripts_check_output(script, ["-c", config_file])
        # verify the script runs to completion without crashing
        assert "100% complete" in output, output

    def test_set_dataset_sizes(self):
        script = "set_dataset_sizes.py"
        self._scripts_check_argparse_help(script)

        # TODO: change the size of the dataset and verify this works.
        history_id = self.dataset_populator.new_history()
        self.dataset_populator.new_dataset(history_id, wait=True)
        config_file = self.write_config_file()
        output = self._scripts_check_output(script, ["-c", config_file])
        # verify the script runs to completion without crashing
        assert "Completed 100%" in output, output

    def test_populate_uuid(self):
        script = "cleanup_datasets/populate_uuid.py"
        self._scripts_check_argparse_help(script)

        history_id = self.dataset_populator.new_history()
        self.dataset_populator.new_dataset(history_id, wait=True)
        config_file = self.write_config_file()
        output = self._scripts_check_output(script, ["-c", config_file])
        assert "Complete" in output

    def test_grt_export(self):
        script = "grt/export.py"
        self._scripts_check_argparse_help(script)

        history_id = self.dataset_populator.new_history()
        self.dataset_populator.new_dataset(history_id, wait=True)
        config_file = self.write_config_file()
        grt_config_file = os.path.join(self.config_dir, "grt.yml")
        with open(grt_config_file, "w") as f:
            yaml.dump({"grt": {"share_toolbox": True}, "sanitization": {"tools": []}, "tool_params": {}}, f)
        self._scripts_check_output(script, ["-c", config_file, "-g", grt_config_file, "-r", self.config_dir])
        report_files = os.listdir(self.config_dir)
        json_files = [j for j in report_files if j.endswith(".json")]
        assert len(json_files) == 1, f"Expected one json report file in [{json_files}]"
        json_file = os.path.join(self.config_dir, json_files[0])
        with open(json_file) as f:
            export = json.load(f)
        assert export["version"] == 3

    def test_secret_decoder_ring(self):
        script = "secret_decoder_ring.py"
        self._scripts_check_argparse_help(script)

        config_file = self.write_config_file()
        output = self._scripts_check_output(script, ["-c", config_file, "encode", "1"])
        encoded_id = output.strip()

        output = self._scripts_check_output(script, ["-c", config_file, "decode", encoded_id])
        assert output.strip() == "1"

    def test_galaxy_main(self):
        self._scripts_check_argparse_help("galaxy-main")

    def test_runtime_stats(self):
        self._skip_unless_postgres()
        self._scripts_check_argparse_help("runtime_stats.py")
