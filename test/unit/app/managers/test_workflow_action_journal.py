import pytest

from galaxy import exceptions
from galaxy.managers.workflow_action_journal import WorkflowActionJournalManager
from galaxy.model import (
    StoredWorkflow,
    Workflow,
)
from .base import BaseTestCase


class TestWorkflowActionJournalManager(BaseTestCase):
    def set_up_managers(self):
        super().set_up_managers()
        self.journal_manager = WorkflowActionJournalManager()

    def _create_stored_workflow_with_versions(self, num_versions=2):
        sa_session = self.app.model.context
        stored_workflow = StoredWorkflow()
        stored_workflow.user = self.trans.user
        workflows = []
        for _ in range(num_versions):
            workflow = Workflow()
            workflow.stored_workflow = stored_workflow
            sa_session.add(workflow)
            workflows.append(workflow)
        sa_session.add(stored_workflow)
        sa_session.flush()
        return stored_workflow, workflows

    def test_create_entry(self):
        sa_session = self.app.model.context
        stored_workflow, workflows = self._create_stored_workflow_with_versions(2)

        entry = self.journal_manager.create_entry(
            sa_session=sa_session,
            stored_workflow=stored_workflow,
            user=self.trans.user,
            title="Rename step",
            source_action_type="UpdateStepLabelAction",
            action_payloads=[{"action_type": "update_step_label"}],
            workflow_before=workflows[0],
            workflow_after=workflows[1],
            execution_messages=[[{"message": "ok", "message_type": "info"}]],
        )
        sa_session.flush()

        assert entry.id is not None
        assert entry.title == "Rename step"
        assert entry.source_action_type == "UpdateStepLabelAction"
        assert entry.action_payloads == [{"action_type": "update_step_label"}]
        assert entry.workflow_id_before == workflows[0].id
        assert entry.workflow_id_after == workflows[1].id
        assert entry.execution_messages == [[{"message": "ok", "message_type": "info"}]]
        assert entry.is_revert is False
        assert entry.stored_workflow_id == stored_workflow.id
        assert entry.user_id == self.trans.user.id

    def test_list_entries_pagination(self):
        sa_session = self.app.model.context
        stored_workflow, workflows = self._create_stored_workflow_with_versions(2)

        for i in range(5):
            self.journal_manager.create_entry(
                sa_session=sa_session,
                stored_workflow=stored_workflow,
                user=self.trans.user,
                title=f"Action {i}",
                source_action_type=None,
                action_payloads=[],
                workflow_before=workflows[0],
                workflow_after=workflows[1],
                execution_messages=[],
            )
        sa_session.flush()

        entries, total = self.journal_manager.list_entries(sa_session, stored_workflow, limit=2, offset=0)
        assert len(entries) == 2
        assert total == 5

        entries, total = self.journal_manager.list_entries(sa_session, stored_workflow, limit=2, offset=3)
        assert len(entries) == 2
        assert total == 5

        entries, total = self.journal_manager.list_entries(sa_session, stored_workflow, limit=2, offset=4)
        assert len(entries) == 1
        assert total == 5

    def test_list_entries_total_count(self):
        sa_session = self.app.model.context
        stored_workflow, workflows = self._create_stored_workflow_with_versions(2)

        entries, total = self.journal_manager.list_entries(sa_session, stored_workflow)
        assert len(entries) == 0
        assert total == 0

        self.journal_manager.create_entry(
            sa_session=sa_session,
            stored_workflow=stored_workflow,
            user=self.trans.user,
            title="Action 1",
            source_action_type=None,
            action_payloads=[],
            workflow_before=workflows[0],
            workflow_after=workflows[1],
            execution_messages=[],
        )
        sa_session.flush()

        entries, total = self.journal_manager.list_entries(sa_session, stored_workflow)
        assert len(entries) == 1
        assert total == 1

    def test_list_entries_ordering(self):
        sa_session = self.app.model.context
        stored_workflow, workflows = self._create_stored_workflow_with_versions(2)

        for i in range(3):
            self.journal_manager.create_entry(
                sa_session=sa_session,
                stored_workflow=stored_workflow,
                user=self.trans.user,
                title=f"Action {i}",
                source_action_type=None,
                action_payloads=[],
                workflow_before=workflows[0],
                workflow_after=workflows[1],
                execution_messages=[],
            )
        sa_session.flush()

        entries, _ = self.journal_manager.list_entries(sa_session, stored_workflow)
        # newest first
        assert entries[0].title == "Action 2"
        assert entries[1].title == "Action 1"
        assert entries[2].title == "Action 0"

    def test_get_entry(self):
        sa_session = self.app.model.context
        stored_workflow, workflows = self._create_stored_workflow_with_versions(2)

        entry = self.journal_manager.create_entry(
            sa_session=sa_session,
            stored_workflow=stored_workflow,
            user=self.trans.user,
            title="Test Entry",
            source_action_type=None,
            action_payloads=[],
            workflow_before=workflows[0],
            workflow_after=workflows[1],
            execution_messages=[],
        )
        sa_session.flush()

        fetched = self.journal_manager.get_entry(sa_session, entry.id)
        assert fetched.id == entry.id
        assert fetched.title == "Test Entry"

    def test_get_entry_not_found(self):
        sa_session = self.app.model.context
        with pytest.raises(exceptions.ObjectNotFound):
            self.journal_manager.get_entry(sa_session, 99999)

    def test_create_revert_entry(self):
        sa_session = self.app.model.context
        stored_workflow, workflows = self._create_stored_workflow_with_versions(3)

        entry = self.journal_manager.create_revert_entry(
            sa_session=sa_session,
            stored_workflow=stored_workflow,
            user=self.trans.user,
            workflow_before=workflows[2],
            workflow_after=workflows[2],
            target_workflow=workflows[0],
        )
        sa_session.flush()

        assert entry.is_revert is True
        assert "Reverted to version" in entry.title
        assert entry.action_payloads == []
        assert entry.execution_messages == []
        assert entry.workflow_id_before == workflows[2].id
        assert entry.workflow_id_after == workflows[2].id
