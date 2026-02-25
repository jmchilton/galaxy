from sqlalchemy import select

from galaxy.managers.context import ProvidesAppContext
from galaxy.managers.workflows import (
    RefactorRequest,
)
from galaxy.model import (
    StoredWorkflow,
    User,
    WorkflowActionJournalEntry,
)
from galaxy.tools.parameters.workflow_utils import workflow_building_modes
from galaxy_test.base.populators import WorkflowPopulator
from galaxy_test.driver import integration_util

CHANGELOG_SIMPLE_TEST = """
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


class TestWorkflowChangelogIntegration(integration_util.IntegrationTestCase):
    framework_tool_and_types = True

    def setUp(self):
        super().setUp()
        self.workflow_populator = WorkflowPopulator(self.galaxy_interactor)

    def test_refactor_with_title_creates_journal_entry(self):
        self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_TEST)
        stored_workflow = self._most_recent_stored_workflow
        workflow_before = stored_workflow.latest_workflow

        actions = [{"action_type": "update_name", "name": "renamed workflow"}]
        self._refactor_with_journal(
            actions,
            title="Rename workflow",
            source_action_type="UpdateNameAction",
        )

        entries = self._journal_entries(stored_workflow)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.title == "Rename workflow"
        assert entry.source_action_type == "UpdateNameAction"
        assert entry.workflow_id_before == workflow_before.id
        assert entry.workflow_id_after == stored_workflow.latest_workflow.id
        assert entry.is_revert is False
        assert entry.action_payloads is not None
        assert len(entry.action_payloads) == 1

    def test_refactor_without_title_no_journal_entry(self):
        self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_TEST)
        stored_workflow = self._most_recent_stored_workflow

        actions = [{"action_type": "update_name", "name": "renamed"}]
        self._refactor(actions)

        entries = self._journal_entries(stored_workflow)
        assert len(entries) == 0

    def test_dry_run_no_journal_entry(self):
        self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_TEST)
        stored_workflow = self._most_recent_stored_workflow

        actions = [{"action_type": "update_name", "name": "renamed"}]
        self._refactor_with_journal(
            actions,
            title="Should not journal",
            dry_run=True,
        )

        entries = self._journal_entries(stored_workflow)
        assert len(entries) == 0

    def test_changelog_list_pagination(self):
        self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_TEST)
        stored_workflow = self._most_recent_stored_workflow
        journal_manager = self._app.workflow_action_journal_manager

        for i in range(3):
            actions = [{"action_type": "update_name", "name": f"name {i}"}]
            self._refactor_with_journal(actions, title=f"Change {i}")

        entries, total = journal_manager.list_entries(self._app.model.session, stored_workflow, limit=2, offset=0)
        assert len(entries) == 2
        assert total == 3

        entries, total = journal_manager.list_entries(self._app.model.session, stored_workflow, limit=2, offset=2)
        assert len(entries) == 1
        assert total == 3

    def test_changelog_ordering_newest_first(self):
        self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_TEST)
        stored_workflow = self._most_recent_stored_workflow
        journal_manager = self._app.workflow_action_journal_manager

        for i in range(3):
            actions = [{"action_type": "update_name", "name": f"name {i}"}]
            self._refactor_with_journal(actions, title=f"Change {i}")

        entries, _ = journal_manager.list_entries(self._app.model.session, stored_workflow)
        assert entries[0].title == "Change 2"
        assert entries[1].title == "Change 1"
        assert entries[2].title == "Change 0"

    def test_revert_creates_new_version_and_journal_entry(self):
        self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_TEST)
        stored_workflow = self._most_recent_stored_workflow
        original_workflow = stored_workflow.latest_workflow

        # Create a second version via refactor
        actions = [{"action_type": "update_name", "name": "version 2"}]
        self._refactor(actions)
        assert stored_workflow.latest_workflow.id != original_workflow.id
        version_count_before = len(stored_workflow.workflows)

        # Revert to original
        mock_trans = self._mock_trans()
        wcm = self._app.workflow_contents_manager
        journal_manager = self._app.workflow_action_journal_manager

        workflow_before = stored_workflow.latest_workflow
        new_workflow, target_workflow = wcm.revert(mock_trans, stored_workflow, original_workflow.id)
        journal_manager.create_revert_entry(
            sa_session=mock_trans.sa_session,
            stored_workflow=stored_workflow,
            user=mock_trans.user,
            workflow_before=workflow_before,
            workflow_after=new_workflow,
            target_workflow=target_workflow,
        )
        mock_trans.sa_session.commit()

        # New version created
        assert len(stored_workflow.workflows) == version_count_before + 1
        # Journal entry recorded
        entries = self._journal_entries(stored_workflow)
        assert len(entries) == 1
        assert entries[0].is_revert is True
        assert "Reverted to version" in entries[0].title

    def test_revert_to_current_version_rejected(self):
        self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_TEST)
        stored_workflow = self._most_recent_stored_workflow
        current_workflow = stored_workflow.latest_workflow

        mock_trans = self._mock_trans()
        wcm = self._app.workflow_contents_manager

        from galaxy.exceptions import RequestParameterInvalidException
        import pytest

        with pytest.raises(RequestParameterInvalidException):
            wcm.revert(mock_trans, stored_workflow, current_workflow.id)

    def test_journal_entry_stores_action_payloads(self):
        self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_TEST)
        stored_workflow = self._most_recent_stored_workflow

        actions = [
            {"action_type": "update_name", "name": "new name"},
            {"action_type": "update_annotation", "annotation": "new annotation"},
        ]
        self._refactor_with_journal(actions, title="Multi-action")

        entries = self._journal_entries(stored_workflow)
        assert len(entries) == 1
        assert len(entries[0].action_payloads) == 2
        assert entries[0].action_payloads[0]["action_type"] == "update_name"
        assert entries[0].action_payloads[1]["action_type"] == "update_annotation"

    def test_journal_entry_stores_execution_messages(self):
        self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_TEST)
        stored_workflow = self._most_recent_stored_workflow

        actions = [{"action_type": "update_name", "name": "new name"}]
        self._refactor_with_journal(actions, title="With messages")

        entries = self._journal_entries(stored_workflow)
        assert len(entries) == 1
        # execution_messages is a list of lists (one per action)
        assert isinstance(entries[0].execution_messages, list)

    def test_atomic_transaction_refactor_failure_no_orphan_entry(self):
        """If refactor fails, no journal entry should be created."""
        self.workflow_populator.upload_yaml_workflow(CHANGELOG_SIMPLE_TEST)
        stored_workflow = self._most_recent_stored_workflow

        # Use an invalid action to cause failure
        actions = [{"action_type": "update_step_label", "label": "nonexistent", "step": {"order_index": 999}}]
        try:
            self._refactor_with_journal(actions, title="Should not persist")
        except Exception:
            pass

        entries = self._journal_entries(stored_workflow)
        assert len(entries) == 0

    # --- Helpers ---

    def _refactor(self, actions, stored_workflow=None, dry_run=False, style="ga"):
        mock_trans = self._mock_trans()
        app = self._app
        original_url_for = app.url_for

        def url_for(*args, **kwd):
            return ""

        app.url_for = url_for
        try:
            return self._manager.refactor(
                mock_trans,
                stored_workflow or self._most_recent_stored_workflow,
                RefactorRequest(actions=actions, dry_run=dry_run, style=style),
            )
        finally:
            app.url_for = original_url_for

    def _refactor_with_journal(
        self,
        actions,
        stored_workflow=None,
        dry_run=False,
        style="ga",
        title=None,
        source_action_type=None,
    ):
        """Refactor with journal support — mimics the service layer's journal wiring."""
        mock_trans = self._mock_trans()
        sw = stored_workflow or self._most_recent_stored_workflow
        app = self._app
        original_url_for = app.url_for

        def url_for(*args, **kwd):
            return ""

        app.url_for = url_for
        try:
            payload = RefactorRequest(
                actions=actions,
                dry_run=dry_run,
                style=style,
                title=title,
                source_action_type=source_action_type,
            )
            should_journal = title is not None and not dry_run
            if should_journal:
                workflow_before = sw.latest_workflow

            response = self._manager.refactor(
                mock_trans,
                sw,
                payload,
                defer_commit=should_journal,
            )

            if should_journal:
                workflow_after = sw.latest_workflow
                action_dicts = [a.model_dump() for a in payload.actions]
                message_dicts = [[m.model_dump() for m in ae.messages] for ae in response.action_executions]
                self._app.workflow_action_journal_manager.create_entry(
                    sa_session=mock_trans.sa_session,
                    stored_workflow=sw,
                    user=mock_trans.user,
                    title=title,
                    source_action_type=source_action_type,
                    action_payloads=action_dicts,
                    workflow_before=workflow_before,
                    workflow_after=workflow_after,
                    execution_messages=message_dicts,
                )
                mock_trans.sa_session.commit()

            return response
        finally:
            app.url_for = original_url_for

    def _mock_trans(self):
        stmt = select(User).order_by(User.id.desc()).limit(1)
        user = self._app.model.session.execute(stmt).scalar_one()
        return MockTrans(self._app, user)

    def _journal_entries(self, stored_workflow):
        sa_session = self._app.model.session
        stmt = (
            select(WorkflowActionJournalEntry)
            .where(WorkflowActionJournalEntry.stored_workflow_id == stored_workflow.id)
            .order_by(WorkflowActionJournalEntry.create_time.desc())
        )
        return sa_session.scalars(stmt).all()

    @property
    def _manager(self):
        return self._app.workflow_contents_manager

    @property
    def _most_recent_stored_workflow(self):
        app = self._app
        stmt = select(StoredWorkflow).order_by(StoredWorkflow.id.desc()).limit(1)
        return app.model.session.scalars(stmt).unique().all()[-1]


class MockTrans(ProvidesAppContext):
    def __init__(self, app, user):
        self._app = app
        self.user = user
        self.history = None
        self.workflow_building_mode = workflow_building_modes.ENABLED
        self.tag_handler = app.tag_handler

    @property
    def galaxy_session(self):
        return None

    @property
    def app(self):
        return self._app

    @property
    def url_builder(self) -> None:
        return None
