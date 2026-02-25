from sqlalchemy import (
    func,
    select,
)

from galaxy import exceptions
from galaxy.model import WorkflowActionJournalEntry


class WorkflowActionJournalManager:
    def create_entry(
        self,
        sa_session,
        stored_workflow,
        user,
        title,
        source_action_type,
        action_payloads,
        workflow_before,
        workflow_after,
        execution_messages,
    ):
        entry = WorkflowActionJournalEntry()
        entry.stored_workflow = stored_workflow
        entry.user = user
        entry.title = title
        entry.source_action_type = source_action_type
        entry.action_payloads = action_payloads
        entry.workflow_id_before = workflow_before.id
        entry.workflow_id_after = workflow_after.id
        entry.execution_messages = execution_messages
        sa_session.add(entry)
        return entry

    def list_entries(self, sa_session, stored_workflow, limit=50, offset=0):
        stmt = (
            select(WorkflowActionJournalEntry)
            .where(WorkflowActionJournalEntry.stored_workflow_id == stored_workflow.id)
            .order_by(WorkflowActionJournalEntry.create_time.desc())
            .limit(limit)
            .offset(offset)
        )
        entries = sa_session.scalars(stmt).all()
        count_stmt = (
            select(func.count())
            .select_from(WorkflowActionJournalEntry)
            .where(WorkflowActionJournalEntry.stored_workflow_id == stored_workflow.id)
        )
        total = sa_session.scalar(count_stmt)
        return entries, total

    def get_entry(self, sa_session, entry_id):
        entry = sa_session.get(WorkflowActionJournalEntry, entry_id)
        if not entry:
            raise exceptions.ObjectNotFound()
        return entry

    def create_revert_entry(self, sa_session, stored_workflow, user, workflow_before, workflow_after, target_workflow):
        version = stored_workflow.version_of(target_workflow)
        entry = WorkflowActionJournalEntry()
        entry.stored_workflow = stored_workflow
        entry.user = user
        entry.title = f"Reverted to version {version}"
        entry.is_revert = True
        entry.action_payloads = []
        entry.execution_messages = []
        entry.workflow_id_before = workflow_before.id
        entry.workflow_id_after = workflow_after.id
        sa_session.add(entry)
        return entry
