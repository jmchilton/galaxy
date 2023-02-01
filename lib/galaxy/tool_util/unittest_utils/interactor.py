from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from galaxy.tool_util.verify.interactor import (
    ToolTestCase,
    ToolTestCaseList,
)

NEW_HISTORY = object()
NEW_HISTORY_ID = "new"
EXISTING_HISTORY = {"id": "existing"}
EXISTING_SUITE_NAME = "existing suite"
EXISTING_HISTORY_NAME = f"History for {EXISTING_SUITE_NAME}"


class MockGalaxyInteractor:
    def __init__(self):
        self.history_deleted = False
        self.history_created = False
        self.history_name = None
        self.history_id = None

    def get_history(self, history_name=""):
        if history_name == EXISTING_HISTORY_NAME:
            self.history_name = history_name
            self.history_id = EXISTING_HISTORY["id"]
            return EXISTING_HISTORY
        else:
            return None

    def new_history(self, history_name="", publish_history=False):
        self.history_created = True
        self.history_name = history_name
        self.history_id = NEW_HISTORY_ID
        return NEW_HISTORY

    def delete_history(self, history):
        self.history_deleted = True

    def get_tests_summary(self):
        return {
            "cat1": {
                "0.2.0": {
                    "count": 4,
                },
                "0.1.0": {
                    "count": 2,
                },
            },
        }

    def get_tool_tests_model(self, tool_id, tool_version=None) -> ToolTestCaseList:
        tool_dict = self.get_tests_summary().get(tool_id)
        test_defs = []
        for this_tool_version, version_defs in tool_dict.items():
            if tool_version is not None and tool_version != "*" and this_tool_version != tool_version:
                continue

            count = version_defs["count"]
            for index in range(count):
                test_def = {
                    "tool_id": tool_id,
                    "tool_version": this_tool_version or "0.1.1-default",
                    "name": ToolTestCase.get_name_default(index),
                    "test_index": index,
                }
                test_defs.append(ToolTestCase(**test_def))

            if tool_version is None or tool_version != "*":
                break

        return ToolTestCaseList(__root__=test_defs)

    def get_tool_tests(self, tool_id: str, tool_version: Optional[str] = None) -> List[Dict[str, Any]]:
        return [m.dict() for m in self.get_tool_tests_model(tool_id, tool_version).__root__]
