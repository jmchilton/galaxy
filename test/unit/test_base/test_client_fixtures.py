import json
from pathlib import Path

import pytest

from galaxy_test.base.client_fixtures import (
    captured_fixtures,
    CLIENT_DIR,
    compare,
    Difference,
    fixture_relative_path,
    format_api_path,
    resolve_fixture_dir,
    write_fixture,
)

GENERATOR = Path(__file__).resolve().parents[3] / "test" / "integration" / "test_generate_client_fixtures.py"

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


def test_localhost_must_end_the_host():
    old = {"download_url": "http://localhost.example.org/api/datasets/x/display"}
    new = {"download_url": "http://127.0.0.1.example.org/api/datasets/x/display"}
    assert [d.kind for d in compare(old, new)] == ["value"]


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


def test_ids_beside_different_srcs_may_collide():
    # HDA 1 and HDCA 1 encode to the same id on a fresh database.
    old = {"inputs": [{"id": DATASET_ID, "src": "hda"}, {"id": DATASET_ID, "src": "hdca"}]}
    new = {"inputs": [{"id": OTHER_DATASET_ID, "src": "hda"}, {"id": DATASET_ID, "src": "hdca"}]}
    assert compare(old, new) == []


def test_ids_beside_the_same_src_cross_reference():
    old = {"inputs": [{"id": DATASET_ID, "src": "hda"}], "outputs": [{"id": DATASET_ID, "src": "hda"}]}
    new = {"inputs": [{"id": DATASET_ID, "src": "hda"}], "outputs": [{"id": OTHER_DATASET_ID, "src": "hda"}]}
    differences = compare(old, new)
    assert [(d.path, d.kind) for d in differences] == [("$.outputs[0].id", "id_mapping")]


def test_url_id_cross_references_its_object():
    old = {"model_class": "History", "id": HISTORY_ID, "url": f"/api/histories/{HISTORY_ID}"}
    new = {"model_class": "History", "id": OTHER_HISTORY_ID, "url": f"/api/histories/{DATASET_ID}"}
    differences = compare(old, new)
    assert [(d.path, d.kind) for d in differences] == [("$.url", "id_mapping")]


def test_url_parent_id_cross_references_by_path_segment():
    old = {"history_id": HISTORY_ID, "id": DATASET_ID, "url": f"/api/histories/{HISTORY_ID}/contents/{DATASET_ID}"}
    new = {
        "history_id": OTHER_HISTORY_ID,
        "id": OTHER_DATASET_ID,
        "url": f"/api/histories/{HISTORY_ID}/contents/{OTHER_DATASET_ID}",
    }
    differences = compare(old, new)
    assert [(d.path, d.kind) for d in differences] == [("$.url", "id_mapping")]


def test_url_parent_and_object_ids_may_collide():
    # History 1 and its first dataset encode to the same id on a fresh database.
    old = {
        "model_class": "HistoryDatasetAssociation",
        "history_id": DATASET_ID,
        "id": DATASET_ID,
        "url": f"/api/histories/{DATASET_ID}/contents/{DATASET_ID}",
    }
    new = {
        "model_class": "HistoryDatasetAssociation",
        "history_id": HISTORY_ID,
        "id": OTHER_DATASET_ID,
        "url": f"/api/histories/{HISTORY_ID}/contents/{OTHER_DATASET_ID}",
    }
    assert compare(old, new) == []


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


def test_id_keyed_dict_in_another_order():
    old = {"outputs": {HISTORY_ID: {"state": "ok"}, DATASET_ID: {"state": "error"}}}
    new = {"outputs": {OTHER_DATASET_ID: {"state": "error"}, OTHER_HISTORY_ID: {"state": "ok"}}}
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


def test_fixture_relative_path():
    assert (
        fixture_relative_path("/api/histories/{history_id}", "GET", "view_detailed")
        == "api/histories/{history_id}/get.view_detailed.json"
    )


def test_fixture_relative_path_success_status_omitted():
    assert (
        fixture_relative_path("/api/tools/fetch", "post", "paste_single", status=201)
        == "api/tools/fetch/post.paste_single.json"
    )


def test_fixture_relative_path_error_status():
    assert (
        fixture_relative_path("/api/histories/{history_id}", "get", "missing", status=404)
        == "api/histories/{history_id}/get.404.missing.json"
    )


@pytest.mark.parametrize("scenario", ["View Detailed", "view-detailed", "", "a.b"])
def test_fixture_relative_path_rejects_bad_scenario(scenario):
    with pytest.raises(ValueError):
        fixture_relative_path("/api/histories", "get", scenario)


def test_fixture_relative_path_rejects_unknown_method():
    with pytest.raises(ValueError):
        fixture_relative_path("/api/histories", "fetch", "default")


def test_fixture_relative_path_requires_absolute_template():
    with pytest.raises(ValueError):
        fixture_relative_path("api/histories", "get", "default")


def test_format_api_path():
    assert (
        format_api_path("/api/histories/{history_id}/contents/{id}", {"history_id": "abc", "id": "def"})
        == "/api/histories/abc/contents/def"
    )


def test_format_api_path_missing_param():
    with pytest.raises(ValueError):
        format_api_path("/api/histories/{history_id}", {})


def test_format_api_path_extra_param():
    with pytest.raises(ValueError):
        format_api_path("/api/histories", {"history_id": "abc"})


def _stub_compare(differences):
    return lambda old, new, volatile_paths=(), open_paths=(): differences


DIFFERENT = [Difference("$.state", "value", "ok", "error")]


def _write(tmp_path, mode, response, differences=()):
    return write_fixture(
        mode, tmp_path, "api/x/get.default.json", response, compare_fn=_stub_compare(list(differences))
    )


def _read(tmp_path):
    return json.loads((tmp_path / "api/x/get.default.json").read_text())


def _seed(tmp_path, content):
    target = tmp_path / "api/x/get.default.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(content))


def test_write_fixture_keeps_order_and_indent(tmp_path):
    _write(tmp_path, "rebuild", {"b": 1, "a": ["é"]})
    assert (tmp_path / "api/x/get.default.json").read_text() == '{\n  "b": 1,\n  "a": [\n    "é"\n  ]\n}\n'


def test_unset_mode_writes_nothing(tmp_path):
    assert _write(tmp_path, None, {"state": "ok"}) == "skipped"
    assert list(tmp_path.iterdir()) == []


def test_update_writes_missing_fixture(tmp_path):
    assert _write(tmp_path, "update", {"state": "ok"}) == "written"
    assert _read(tmp_path) == {"state": "ok"}


def test_update_keeps_equivalent_fixture(tmp_path):
    _seed(tmp_path, {"id": "old"})
    assert _write(tmp_path, "update", {"id": "new"}) == "unchanged"
    assert _read(tmp_path) == {"id": "old"}


def test_update_rewrites_changed_fixture(tmp_path, capsys):
    _seed(tmp_path, {"state": "ok"})
    assert _write(tmp_path, "update", {"state": "error"}, DIFFERENT) == "written"
    assert _read(tmp_path) == {"state": "error"}
    assert "$.state" in capsys.readouterr().out


def test_rebuild_rewrites_equivalent_fixture(tmp_path):
    _seed(tmp_path, {"id": "old"})
    assert _write(tmp_path, "rebuild", {"id": "new"}) == "written"
    assert _read(tmp_path) == {"id": "new"}


def test_check_passes_equivalent_fixture(tmp_path):
    _seed(tmp_path, {"id": "old"})
    assert _write(tmp_path, "check", {"id": "new"}) == "unchanged"
    assert _read(tmp_path) == {"id": "old"}


def test_check_fails_changed_fixture(tmp_path):
    _seed(tmp_path, {"state": "ok"})
    with pytest.raises(AssertionError, match=r"api/x/get.default.json(.|\n)*\$\.state"):
        _write(tmp_path, "check", {"state": "error"}, DIFFERENT)
    assert _read(tmp_path) == {"state": "ok"}


def test_check_fails_missing_fixture(tmp_path):
    with pytest.raises(AssertionError, match="api/x/get.default.json"):
        _write(tmp_path, "check", {"state": "ok"})


def test_unknown_mode(tmp_path):
    with pytest.raises(ValueError):
        _write(tmp_path, "overwrite", {"state": "ok"})


def test_resolve_fixture_dir_defaults_to_client(tmp_path):
    client = tmp_path / "client"
    client.mkdir()
    assert resolve_fixture_dir("update", None, client) == client / "src" / "api" / "__fixtures__"


def test_resolve_fixture_dir_explicit(tmp_path):
    assert resolve_fixture_dir("check", str(tmp_path / "out"), tmp_path / "client") == tmp_path / "out"


def test_resolve_fixture_dir_requires_explicit_dir_without_client(tmp_path):
    with pytest.raises(Exception, match="GALAXY_TEST_CLIENT_FIXTURES_DIR"):
        resolve_fixture_dir("update", None, tmp_path / "client")


def test_resolve_fixture_dir_unset_mode_has_no_dir(tmp_path):
    assert resolve_fixture_dir(None, None, tmp_path / "client") is None


def test_captured_fixtures():
    source = """
fixtures.capture("get", "/api/histories/{history_id}", "summary", purpose=check, history_id=history_id)
self.fixtures.capture("post", "/api/jobs", "bad_inputs", purpose=check, status=400, body={})
"""
    assert captured_fixtures(source) == {
        "api/histories/{history_id}/get.summary.json",
        "api/jobs/post.400.bad_inputs.json",
    }


def test_captured_fixtures_requires_literals():
    with pytest.raises(ValueError, match="literal"):
        captured_fixtures('fixtures.capture("get", path, "summary", purpose=check)')


@pytest.mark.skipif(not CLIENT_DIR.is_dir(), reason="needs Galaxy's client/ directory")
def test_every_committed_fixture_is_captured():
    fixture_dir = CLIENT_DIR / "src" / "api" / "__fixtures__"
    committed = {path.relative_to(fixture_dir).as_posix() for path in fixture_dir.glob("api/**/*.json")}
    captured = captured_fixtures(GENERATOR.read_text()) if GENERATOR.exists() else set()
    assert committed - captured == set(), f"Fixtures no capture in {GENERATOR.name} writes"
