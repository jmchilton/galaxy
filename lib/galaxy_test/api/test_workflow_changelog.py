from galaxy_test.base.populators import WorkflowPopulator
from ._framework import ApiTestCase

CHANGELOG_SIMPLE_WF = """
class: GalaxyWorkflow
inputs:
  test_input: data
outputs:
  wf_out:
    outputSource: first_cat/out_file1
steps:
  first_cat:
    tool_id: cat
    in:
      input1: test_input
"""


class TestWorkflowChangelogApi(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.workflow_populator = WorkflowPopulator(self.galaxy_interactor)

    def test_refactor_with_title_creates_journal_entry(self):
        workflow_id = self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_WF)
        actions = [{"action_type": "update_name", "name": "renamed workflow"}]
        response = self.workflow_populator.refactor_workflow(
            workflow_id,
            actions,
            title="Rename workflow",
            source_action_type="UpdateNameAction",
        )
        response.raise_for_status()

        changelog = self._get_changelog(workflow_id)
        assert len(changelog) == 1
        assert changelog[0]["title"] == "Rename workflow"
        assert changelog[0]["source_action_type"] == "UpdateNameAction"
        assert changelog[0]["is_revert"] is False

    def test_refactor_without_title_no_journal_entry(self):
        workflow_id = self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_WF)
        actions = [{"action_type": "update_name", "name": "renamed"}]
        response = self.workflow_populator.refactor_workflow(workflow_id, actions)
        response.raise_for_status()

        changelog = self._get_changelog(workflow_id)
        assert len(changelog) == 0

    def test_dry_run_no_journal_entry(self):
        workflow_id = self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_WF)
        actions = [{"action_type": "update_name", "name": "renamed"}]
        response = self.workflow_populator.refactor_workflow(
            workflow_id,
            actions,
            title="Should not journal",
            dry_run=True,
        )
        response.raise_for_status()

        changelog = self._get_changelog(workflow_id)
        assert len(changelog) == 0

    def test_changelog_list_pagination(self):
        workflow_id = self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_WF)

        for i in range(3):
            actions = [{"action_type": "update_name", "name": f"name {i}"}]
            self.workflow_populator.refactor_workflow(
                workflow_id,
                actions,
                title=f"Change {i}",
            ).raise_for_status()

        changelog, headers = self._get_changelog(workflow_id, limit=2, offset=0)
        assert len(changelog) == 2
        assert headers["total_matches"] == "3"

        changelog, headers = self._get_changelog(workflow_id, limit=2, offset=2)
        assert len(changelog) == 1
        assert headers["total_matches"] == "3"

    def test_changelog_ordering_newest_first(self):
        workflow_id = self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_WF)

        for i in range(3):
            actions = [{"action_type": "update_name", "name": f"name {i}"}]
            self.workflow_populator.refactor_workflow(
                workflow_id,
                actions,
                title=f"Change {i}",
            ).raise_for_status()

        changelog = self._get_changelog(workflow_id)
        assert changelog[0]["title"] == "Change 2"
        assert changelog[1]["title"] == "Change 1"
        assert changelog[2]["title"] == "Change 0"

    def test_revert_creates_new_version_and_journal_entry(self):
        workflow_id = self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_WF)

        versions_before = self._get(f"workflows/{workflow_id}/versions")
        versions_before.raise_for_status()
        original_version_count = len(versions_before.json())

        # Create second version with title so we get a changelog entry with workflow IDs
        actions = [{"action_type": "update_name", "name": "version 2"}]
        self.workflow_populator.refactor_workflow(
            workflow_id,
            actions,
            title="Create v2",
        ).raise_for_status()

        # Get the original workflow's internal ID from the changelog entry
        changelog = self._get_changelog(workflow_id)
        assert len(changelog) == 1
        original_workflow_instance_id = changelog[0]["workflow_id_before"]

        # Revert to original
        revert_response = self.workflow_populator.revert_workflow(
            workflow_id,
            original_workflow_instance_id,
        )
        self._assert_status_code_is(revert_response, 200)

        # New version created
        versions_after = self._get(f"workflows/{workflow_id}/versions")
        versions_after.raise_for_status()
        assert len(versions_after.json()) == original_version_count + 2  # +1 refactor, +1 revert

        # Revert journal entry recorded (newest first, so index 0)
        changelog = self._get_changelog(workflow_id)
        assert len(changelog) == 2
        assert changelog[0]["is_revert"] is True
        assert "Reverted to version" in changelog[0]["title"]

    def test_revert_to_current_version_rejected(self):
        workflow_id = self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_WF)

        # Create a refactor with title to get the after-workflow ID (which is current)
        actions = [{"action_type": "update_name", "name": "renamed"}]
        self.workflow_populator.refactor_workflow(
            workflow_id,
            actions,
            title="Create v1",
        ).raise_for_status()

        changelog = self._get_changelog(workflow_id)
        current_workflow_id = changelog[0]["workflow_id_after"]

        revert_response = self.workflow_populator.revert_workflow(workflow_id, current_workflow_id)
        self._assert_status_code_is(revert_response, 400)

    def test_multi_action_execution_messages(self):
        workflow_id = self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_WF)
        actions = [
            {"action_type": "update_name", "name": "new name"},
            {"action_type": "update_annotation", "annotation": "new annotation"},
        ]
        self.workflow_populator.refactor_workflow(
            workflow_id,
            actions,
            title="Multi-action",
        ).raise_for_status()

        changelog = self._get_changelog(workflow_id)
        assert len(changelog) == 1
        messages = changelog[0]["execution_messages"]
        assert isinstance(messages, list)
        # One message group per action executed
        assert len(messages) == 2

    def test_empty_changelog_on_fresh_workflow(self):
        workflow_id = self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_WF)
        changelog = self._get_changelog(workflow_id)
        assert len(changelog) == 0

    def test_revert_entry_has_null_reverted_entry_id(self):
        workflow_id = self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_WF)

        actions = [{"action_type": "update_name", "name": "v2"}]
        self.workflow_populator.refactor_workflow(
            workflow_id,
            actions,
            title="Create v2",
        ).raise_for_status()

        changelog = self._get_changelog(workflow_id)
        original_workflow_id = changelog[0]["workflow_id_before"]

        self.workflow_populator.revert_workflow(
            workflow_id,
            original_workflow_id,
        ).raise_for_status()

        changelog = self._get_changelog(workflow_id)
        revert_entry = changelog[0]
        assert revert_entry["is_revert"] is True
        # reverted_entry_id not yet wired in create_revert_entry
        assert revert_entry["reverted_entry_id"] is None
        # Non-revert entry should also be None
        refactor_entry = changelog[1]
        assert refactor_entry["reverted_entry_id"] is None

    def test_revert_with_invalid_target_workflow_id(self):
        workflow_id = self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_WF)

        # Bogus encoded ID that doesn't correspond to any workflow
        revert_response = self.workflow_populator.revert_workflow(workflow_id, "invalid_id_xyz")
        assert revert_response.status_code >= 400

        # ID from a different stored workflow
        other_workflow_id = self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_WF)
        actions = [{"action_type": "update_name", "name": "other"}]
        self.workflow_populator.refactor_workflow(
            other_workflow_id,
            actions,
            title="Other change",
        ).raise_for_status()
        other_changelog = self._get_changelog(other_workflow_id)
        other_internal_id = other_changelog[0]["workflow_id_before"]

        revert_response = self.workflow_populator.revert_workflow(workflow_id, other_internal_id)
        assert revert_response.status_code >= 400

    def test_refactor_failure_no_journal_entry(self):
        workflow_id = self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_WF)
        actions = [{"action_type": "update_step_label", "label": "x", "step": {"order_index": 999}}]
        response = self.workflow_populator.refactor_workflow(
            workflow_id,
            actions,
            title="Should not persist",
        )
        self._assert_status_code_is(response, 400)

        changelog = self._get_changelog(workflow_id)
        assert len(changelog) == 0

    # --- Helpers ---

    def _get_changelog(self, workflow_id, **kwargs):
        response = self.workflow_populator.get_workflow_changelog(workflow_id, **kwargs)
        response.raise_for_status()
        if kwargs:
            return response.json(), response.headers
        return response.json()
