"""Test selecting an object store with user's preferred object store."""

import os
import string

from galaxy.model import Dataset
from ._base import (
    BaseObjectStoreIntegrationTestCase,
    files_count,
)

SCRIPT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))

DISTRIBUTED_OBJECT_STORE_CONFIG_TEMPLATE = string.Template(
    """<?xml version="1.0"?>
<object_store type="distributed" id="primary" order="0">
    <backends>
        <backend id="default" allow_selection="true" type="disk" weight="1" name="Default Store">
            <description>This is my description of the default store with *markdown*.</description>
            <files_dir path="${temp_directory}/files_default"/>
            <extra_dir type="temp" path="${temp_directory}/tmp_default"/>
            <extra_dir type="job_work" path="${temp_directory}/job_working_directory_default"/>
        </backend>
        <backend id="static" allow_selection="true" type="disk" weight="0" name="Static Storage">
            <files_dir path="${temp_directory}/files_static"/>
            <extra_dir type="temp" path="${temp_directory}/tmp_static"/>
            <extra_dir type="job_work" path="${temp_directory}/job_working_directory_static"/>
        </backend>
        <backend id="dynamic_ebs" allow_selection="true" type="disk" weight="0">
            <quota source="ebs" />
            <files_dir path="${temp_directory}/files_dynamic_ebs"/>
            <extra_dir type="temp" path="${temp_directory}/tmp_dynamic_ebs"/>
            <extra_dir type="job_work" path="${temp_directory}/job_working_directory_dynamic_ebs"/>
        </backend>
        <backend id="dynamic_s3" type="disk" weight="0">
            <quota source="s3" />
            <files_dir path="${temp_directory}/files_dynamic_s3"/>
            <extra_dir type="temp" path="${temp_directory}/tmp_dynamic_s3"/>
            <extra_dir type="job_work" path="${temp_directory}/job_working_directory_dynamic_s3"/>
        </backend>
    </backends>
</object_store>
"""
)


class ObjectStoreSelectionWithResourceParametersIntegrationTestCase(BaseObjectStoreIntegrationTestCase):
    # populated by config_object_store
    files_default_path: str
    files_static_path: str
    files_dynamic_path: str
    files_dynamic_ebs_path: str
    files_dynamic_s3_path: str

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        cls._configure_object_store(DISTRIBUTED_OBJECT_STORE_CONFIG_TEMPLATE, config)
        config["object_store_store_by"] = "uuid"
        config["outputs_to_working_directory"] = True

    def _object_store_counts(self):
        files_default_count = files_count(self.files_default_path)
        files_static_count = files_count(self.files_static_path)
        files_dynamic_count = files_count(self.files_dynamic_path)
        return files_default_count, files_static_count, files_dynamic_count

    def _assert_file_counts(self, default, static, dynamic_ebs, dynamic_s3):
        files_default_count = files_count(self.files_default_path)
        files_static_count = files_count(self.files_static_path)
        files_dynamic_ebs_count = files_count(self.files_dynamic_ebs_path)
        files_dynamic_s3_count = files_count(self.files_dynamic_s3_path)
        assert default == files_default_count
        assert static == files_static_count
        assert dynamic_ebs == files_dynamic_ebs_count
        assert dynamic_s3 == files_dynamic_s3_count

    def _assert_no_external_filename(self):
        # Should maybe be its own test case ...
        for external_filename_tuple in self._app.model.session.query(Dataset.external_filename).all():
            assert external_filename_tuple[0] is None

    def test_setting_unselectable_object_store_id_not_allowed(self):
        response = self.dataset_populator.update_user_raw({"preferred_object_store_id": "dynamic_s3"})
        assert response.status_code == 400

    def test_index_query(self):
        selectable_object_stores_response = self._get("object_store?selectable=true")
        selectable_object_stores_response.raise_for_status()
        selectable_object_stores = selectable_object_stores_response.json()
        selectable_object_store_ids = [s["object_store_id"] for s in selectable_object_stores]
        assert "default" in selectable_object_store_ids
        assert "static" in selectable_object_store_ids
        assert "dynamic_s3" not in selectable_object_store_ids

    def test_objectstore_selection(self):

        with self.dataset_populator.test_history() as history_id:

            def _storage_info(hda):
                return self.dataset_populator.dataset_storage_info(hda["id"])

            def _create_hda_get_storage_info():
                hda1 = self.dataset_populator.new_dataset(history_id, content="1 2 3")
                self.dataset_populator.wait_for_history(history_id)
                return _storage_info(hda1), hda1

            def _run_tool(tool_id, inputs, preferred_object_store_id=None):
                response = self.dataset_populator.run_tool(
                    tool_id,
                    inputs,
                    history_id,
                    preferred_object_store_id=preferred_object_store_id,
                )
                self.dataset_populator.wait_for_history(history_id)
                return response

            user_properties = self.dataset_populator.update_user({"preferred_object_store_id": "static"})
            assert user_properties["preferred_object_store_id"] == "static"

            storage_info, hda1 = _create_hda_get_storage_info()
            assert storage_info["name"] == "Static Storage"

            user_properties = self.dataset_populator.update_user({"preferred_object_store_id": None})

            storage_info, _ = _create_hda_get_storage_info()
            assert storage_info["name"] == "Default Store"

            self.dataset_populator.update_history(history_id, {"preferred_object_store_id": "static"})
            storage_info, _ = _create_hda_get_storage_info()
            assert storage_info["name"] == "Static Storage"

            hda1_input = {"src": "hda", "id": hda1["id"]}
            response = _run_tool("multi_data_param", {"f1": hda1_input, "f2": hda1_input})
            output = response["outputs"][0]
            storage_info = _storage_info(output)
            assert storage_info["name"] == "Static Storage"

            hda1_input = {"src": "hda", "id": hda1["id"]}
            response = _run_tool(
                "multi_data_param", {"f1": hda1_input, "f2": hda1_input}, preferred_object_store_id="default"
            )
            output = response["outputs"][0]
            storage_info = _storage_info(output)
            assert storage_info["name"] == "Default Store"

    @property
    def _latest_dataset(self):
        latest_dataset = self._app.model.session.query(Dataset).order_by(Dataset.table.c.id.desc()).first()
        return latest_dataset
