from galaxy_test.base.client_fixtures import compare

HISTORY_ID = "f2db41e1fa331b3e"
OTHER_HISTORY_ID = "1cd8e2f6b131e891"
DATASET_ID = "f597429621d6eb2b"
OTHER_DATASET_ID = "a799d38679e985db"


def test_equal_documents():
    doc = {"name": "test", "count": 3, "deleted": False, "tags": ["a", "b"], "parent": None}
    assert compare(doc, doc) == []


def test_id_swapped_for_another_id():
    assert compare({"id": HISTORY_ID}, {"id": OTHER_HISTORY_ID}) == []


def test_long_encoded_id_and_uuid_swapped():
    old = {"id": HISTORY_ID * 2, "uuid": "2a7c3f9e-5b1d-4c8e-9f0a-6d3b2e1c4a5f"}
    new = {"id": DATASET_ID * 2, "uuid": "9e1d7b3a-2c4f-4a6e-8b0d-1f5c3e7a9b2d"}
    assert compare(old, new) == []


def test_id_inside_string_swapped():
    old = {"url": f"/api/histories/{HISTORY_ID}/contents"}
    new = {"url": f"/api/histories/{OTHER_HISTORY_ID}/contents"}
    assert compare(old, new) == []


def test_datetime_swapped_for_another_datetime():
    old = {"create_time": "2024-01-02T03:04:05.123456", "update_time": "2024-01-02T03:04:05"}
    new = {"create_time": "2026-10-10T11:12:13.654321", "update_time": "2026-10-10 11:12:13+00:00"}
    assert compare(old, new) == []


def test_server_url_and_port_swapped():
    old = {"download_url": "http://localhost:8081/api/datasets/x/display"}
    new = {"download_url": "http://127.0.0.1:9123/api/datasets/x/display"}
    assert compare(old, new) == []


def test_consistent_cross_reference():
    old = {"id": HISTORY_ID, "contents": [{"history_id": HISTORY_ID, "id": DATASET_ID}]}
    new = {"id": OTHER_HISTORY_ID, "contents": [{"history_id": OTHER_HISTORY_ID, "id": OTHER_DATASET_ID}]}
    assert compare(old, new) == []


def test_broken_cross_reference():
    old = {"model_class": "History", "id": HISTORY_ID, "contents": [{"history_id": HISTORY_ID}]}
    new = {"model_class": "History", "id": OTHER_HISTORY_ID, "contents": [{"history_id": DATASET_ID}]}
    differences = compare(old, new)
    assert [d.path for d in differences] == ["$.contents[0].history_id"]
    assert differences[0].kind == "id_mapping"


def test_cross_reference_broken_by_unchanged_id():
    old = {"model_class": "History", "id": HISTORY_ID, "contents": [{"history_id": HISTORY_ID}]}
    new = {"model_class": "History", "id": OTHER_HISTORY_ID, "contents": [{"history_id": HISTORY_ID}]}
    differences = compare(old, new)
    assert [(d.path, d.kind) for d in differences] == [("$.contents[0].history_id", "id_mapping")]


def test_recorded_history_after_other_histories_were_created():
    # The history moved to a later row; its owner didn't.
    old = {"model_class": "History", "id": HISTORY_ID, "url": f"/api/histories/{HISTORY_ID}", "user_id": HISTORY_ID}
    new = {"model_class": "History", "id": DATASET_ID, "url": f"/api/histories/{DATASET_ID}", "user_id": HISTORY_ID}
    assert compare(old, new) == []


def test_two_old_ids_collapsed_into_one():
    old = {"dataset_ids": [HISTORY_ID, DATASET_ID]}
    new = {"dataset_ids": [OTHER_HISTORY_ID, OTHER_HISTORY_ID]}
    differences = compare(old, new)
    assert [d.path for d in differences] == ["$.dataset_ids[1]"]
    assert differences[0].kind == "id_mapping"


def test_ids_of_different_entities_may_collide():
    # On a fresh database a history and its owner are both row 1, so their ids match.
    old = {"model_class": "History", "id": HISTORY_ID, "user_id": HISTORY_ID}
    new = {"model_class": "History", "id": OTHER_HISTORY_ID, "user_id": DATASET_ID}
    assert compare(old, new) == []


def test_ids_of_different_entities_may_stop_colliding():
    old = {"model_class": "History", "id": OTHER_HISTORY_ID, "user_id": DATASET_ID}
    new = {"model_class": "History", "id": HISTORY_ID, "user_id": HISTORY_ID}
    assert compare(old, new) == []


def test_id_without_model_class_is_keyed_by_its_container():
    old = {"jobs": [{"id": HISTORY_ID}], "outputs": [{"id": HISTORY_ID}, {"id": DATASET_ID}]}
    new = {"jobs": [{"id": OTHER_HISTORY_ID}], "outputs": [{"id": OTHER_DATASET_ID}, {"id": OTHER_DATASET_ID}]}
    differences = compare(old, new)
    assert [(d.path, d.kind) for d in differences] == [("$.outputs[1].id", "id_mapping")]


def test_key_added():
    differences = compare({"name": "x"}, {"name": "x", "extra": 1})
    assert [(d.path, d.kind) for d in differences] == [("$.extra", "added")]


def test_key_removed():
    differences = compare({"name": "x", "gone": 1}, {"name": "x"})
    assert [(d.path, d.kind) for d in differences] == [("$.gone", "removed")]


def test_type_change():
    differences = compare({"size": 1}, {"size": "1"})
    assert [(d.path, d.kind) for d in differences] == [("$.size", "type")]


def test_bool_is_not_a_number():
    differences = compare({"deleted": 0}, {"deleted": False})
    assert [(d.path, d.kind) for d in differences] == [("$.deleted", "type")]


def test_null_to_value():
    differences = compare({"parent": None}, {"parent": "x"})
    assert [(d.path, d.kind) for d in differences] == [("$.parent", "type")]


def test_value_to_null():
    differences = compare({"parent": "x"}, {"parent": None})
    assert [(d.path, d.kind) for d in differences] == [("$.parent", "type")]


def test_enum_value_change():
    differences = compare({"state": "ok"}, {"state": "error"})
    assert [(d.path, d.kind) for d in differences] == [("$.state", "value")]
    assert "'ok'" in str(differences[0]) and "'error'" in str(differences[0])


def test_number_change():
    differences = compare({"hid": 1}, {"hid": 2})
    assert [(d.path, d.kind) for d in differences] == [("$.hid", "value")]


def test_list_reorder():
    differences = compare({"tags": ["a", "b"]}, {"tags": ["b", "a"]})
    assert [d.path for d in differences] == ["$.tags[0]", "$.tags[1]"]


def test_list_length():
    differences = compare({"tags": ["a", "b"]}, {"tags": ["a"]})
    assert [(d.path, d.kind) for d in differences] == [("$.tags", "length")]


def test_nested_path():
    old = {"steps": {"0": {"inputs": [{"name": "a"}]}}}
    new = {"steps": {"0": {"inputs": [{"name": "b"}]}}}
    assert [d.path for d in compare(old, new)] == ['$.steps["0"].inputs[0].name']


def test_id_keyed_dict():
    old = {"outputs": {HISTORY_ID: {"state": "ok"}}}
    new = {"outputs": {OTHER_HISTORY_ID: {"state": "ok"}}}
    assert compare(old, new) == []


def test_volatile_path_override():
    old = {"jobs": [{"runtime": 1.5, "state": "ok"}, {"runtime": 2, "state": "ok"}]}
    new = {"jobs": [{"runtime": 3.75, "state": "ok"}, {"runtime": None, "state": "ok"}]}
    assert len(compare(old, new)) == 2
    assert compare(old, new, volatile_paths=["$.jobs[*].runtime"]) == []


def test_volatile_path_override_still_checks_siblings():
    old = {"jobs": [{"runtime": 1.5, "state": "ok"}]}
    new = {"jobs": [{"runtime": 3.75, "state": "error"}]}
    differences = compare(old, new, volatile_paths=["$.jobs[*].runtime"])
    assert [d.path for d in differences] == ["$.jobs[0].state"]


def test_open_dict_tolerates_added_key():
    old = {"brand": "Galaxy", "enable_quotas": False}
    new = {"brand": "Galaxy", "enable_quotas": False, "new_option": True}
    assert compare(old, new, open_paths=["$"]) == []


def test_open_dict_still_flags_removed_key_and_changed_value():
    old = {"brand": "Galaxy", "enable_quotas": False}
    new = {"brand": "Other", "new_option": True}
    differences = compare(old, new, open_paths=["$"])
    assert [(d.path, d.kind) for d in differences] == [("$.brand", "value"), ("$.enable_quotas", "removed")]


def test_open_dict_with_wildcard():
    old = {"ext_to_class_name": {"txt": "Text"}, "class_to_classes": {"Text": {"Data": True}}}
    new = {"ext_to_class_name": {"txt": "Text", "csv": "Csv"}, "class_to_classes": {"Text": {"Data": True}, "Csv": {}}}
    assert compare(old, new, open_paths=["$.*"]) == []
