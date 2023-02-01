from galaxy.tool_util.verify.interactor import (
    ToolTestDescription,
    ValidToolTestDict,
)


def test_valid_tool_test_description():
    valid_dict = ValidToolTestDict(
        inputs={},
        outputs=[],
        output_collections=[],
        error=False,
        tool_id="cat1",
        tool_version="1.0.0",
        test_index=0,
    )
    ttd = ToolTestDescription(valid_dict)
    assert ttd.maxseconds == 86400
    assert ttd.tool_id == "cat1"
    assert ttd.tool_version == "1.0.0"
    assert ttd.test_index == 0
    assert ttd.name == "Test-1"


def test_valid_to_model():
    valid_dict = ValidToolTestDict(
        inputs={},
        outputs=[],
        output_collections=[],
        error=False,
        tool_id="cat1",
        tool_version="1.0.0",
        test_index=0,
    )
    ttd = ToolTestDescription(valid_dict)
    model = ttd.to_model()
    as_dict = model.dict()
    assert as_dict["inputs"] == {}
    assert as_dict["outputs"] == []
    assert as_dict["error"] is False
    assert as_dict["tool_id"] == "cat1"
    assert as_dict["tool_version"] == "1.0.0"
    assert as_dict["test_index"] == 0
    assert as_dict["maxseconds"] == 86400
    assert as_dict["name"] == "Test-1"
