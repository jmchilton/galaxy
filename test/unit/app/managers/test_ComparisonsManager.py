from unittest import mock

from sqlalchemy import event

from galaxy import model
from galaxy.managers.comparison_cells import (
    COMPARISON_INLINE_EXPRESSION_MAX_BYTES,
    ComparisonCellBuilder,
)
from galaxy.managers.comparisons import ComparisonsManager
from galaxy.managers.hdas import HDASerializer
from galaxy.schema.comparisons import StepRunsQuery
from galaxy.schema.fields import Security
from .base import BaseTestCase


class TestComparisonsManagerStatementCount(BaseTestCase):
    def set_up_managers(self):
        super().set_up_managers()
        self.session = self.app.model.session
        cell_builder = ComparisonCellBuilder(self.session, HDASerializer(self.app))
        self.comparisons_manager = ComparisonsManager(self.session, cell_builder)
        Security.security = self.app.security

    def test_step_runs_statement_count_independent_of_row_count(self):
        for mapped in (False, True):
            counts = [self._step_runs_statement_count(invocations, mapped) for invocations in (1, 5)]
            assert counts[0] == counts[1], f"mapped={mapped}: statements grow with rows {counts}"

    def _step_runs_statement_count(self, invocations: int, mapped: bool) -> int:
        stored_workflow_id = self._stored_workflow_with_runs(invocations, mapped).id
        user_id = self.trans.user.id
        self.session.expunge_all()
        query = StepRunsQuery.model_construct(
            workflow_id=stored_workflow_id, step_label="target", metadata_elements=["data_lines"]
        )
        statements: list[str] = []

        def count(conn, cursor, statement, *args):
            statements.append(statement)

        engine = self.session.get_bind()
        event.listen(engine, "before_cursor_execute", count)
        try:
            table, total = self.comparisons_manager.step_runs(user_id, stored_workflow_id, query)
            # serialization must not lazy-load either
            table.model_dump(mode="json")
        finally:
            event.remove(engine, "before_cursor_execute", count)
        assert total == invocations
        assert len(table.rows) == invocations
        assert all(cell.type != "missing" for row in table.rows for cell in row.cells.values())
        return len(statements)

    def _stored_workflow_with_runs(self, invocations: int, mapped: bool) -> model.StoredWorkflow:
        user = self.trans.user
        stored_workflow = model.StoredWorkflow()
        stored_workflow.user = user
        stored_workflow.name = "compared"
        versions = []
        for _ in range(2):
            workflow = model.Workflow()
            workflow.name = "compared"
            workflow.stored_workflow = stored_workflow
            step = model.WorkflowStep()
            step.order_index = 0
            step.type = "tool"
            step.tool_id = "cat1"
            step.label = "target"
            workflow.steps.append(step)
            versions.append((workflow, step))
        stored_workflow.latest_workflow = versions[-1][0]
        self.session.add(stored_workflow)
        for i in range(invocations):
            workflow, step = versions[i % 2]
            history = model.History(name=f"run {i}", user=user)
            invocation = model.WorkflowInvocation()
            invocation.workflow = workflow
            invocation.history = history
            invocation.state = "scheduled"
            invocation_step = model.WorkflowInvocationStep()
            invocation_step.workflow_invocation = invocation
            invocation_step.workflow_step = step
            invocation_step.state = "scheduled"
            self.session.add_all([history, invocation, invocation_step])
            if mapped:
                self._mapped_step(invocation_step, history, user)
            else:
                job = self._job(history, user)
                job.add_input_dataset("input1", self._hda(history))
                invocation_step.job = job
                invocation_step.add_output("out_file1", self._hda(history))
        self.session.commit()
        return stored_workflow

    def _mapped_step(self, invocation_step, history, user) -> None:
        icj = model.ImplicitCollectionJobs(populated_state="ok")
        for order_index in range(2):
            job = self._job(history, user)
            job.add_input_dataset("input1", self._hda(history))
            association = model.ImplicitCollectionJobsJobAssociation()
            association.order_index = order_index
            association.implicit_collection_jobs = icj
            association.job = job
            self.session.add(association)
        input_hdca = self._hdca(history)
        output_hdca = self._hdca(history)
        output_hdca.implicit_collection_jobs = icj
        output_hdca.implicit_output_name = "out_file1"
        output_hdca.implicit_input_collections.append(
            model.ImplicitlyCreatedDatasetCollectionInput("input1", input_hdca)
        )
        invocation_step.implicit_collection_jobs = icj
        invocation_step.add_output("out_file1", output_hdca)

    def _job(self, history, user) -> model.Job:
        job = model.Job()
        job.user = user
        job.history = history
        job.tool_id = "cat1"
        job.tool_version = "1.0.0"
        job.state = "ok"
        return job

    def _hda(self, history) -> model.HistoryDatasetAssociation:
        hda = model.HistoryDatasetAssociation(
            history=history, extension="txt", create_dataset=True, sa_session=self.session
        )
        assert hda.dataset
        hda.dataset.state = "ok"
        self.session.add(hda)
        return hda

    def _hdca(self, history) -> model.HistoryDatasetCollectionAssociation:
        collection = model.DatasetCollection(collection_type="list", populated=True)
        hdca = model.HistoryDatasetCollectionAssociation(collection=collection, history=history)
        self.session.add(hdca)
        return hdca


class TestComparisonCellBuilder(BaseTestCase):
    def set_up_managers(self):
        super().set_up_managers()
        self.session = self.app.model.session
        self.cell_builder = ComparisonCellBuilder(self.session, HDASerializer(self.app))
        Security.security = self.app.security

    def test_dataset_cell_skips_file_metadata(self):
        hda = self._hda("bam")
        assert "bam_index" in hda.metadata.spec
        assert "bam_index" not in self.cell_builder.metadata_keys(hda)
        cell = self.cell_builder.dataset_cell(hda, ["bam_index"], inline_expression_values=False)
        assert cell.type == "dataset"
        assert cell.metadata == {}

    def test_dataset_cell_caps_list_metadata(self):
        hda = self._hda("tabular")
        hda.metadata.column_names = [f"c{i}" for i in range(60)]
        hda.metadata.data_lines = 7
        cell = self.cell_builder.dataset_cell(hda, ["column_names", "data_lines"], inline_expression_values=False)
        assert cell.type == "dataset"
        assert cell.metadata == {"column_names": [f"c{i}" for i in range(50)], "data_lines": 7}

    def test_expression_value_cell_skips_unknown_size(self):
        hda = self._hda("expression.json")
        assert hda.dataset
        hda.dataset.state = "ok"
        with mock.patch("galaxy.managers.comparison_cells.read_expression_json", return_value=42) as read:
            cell = self.cell_builder.dataset_cell(hda, [], inline_expression_values=True)
        assert cell.type == "dataset"
        read.assert_not_called()

    def test_expression_value_cell_inlines_small_value(self):
        hda = self._hda("expression.json")
        assert hda.dataset
        hda.dataset.state = "ok"
        hda.dataset.file_size = 3
        with mock.patch("galaxy.managers.comparison_cells.read_expression_json", return_value=42):
            cell = self.cell_builder.dataset_cell(hda, [], inline_expression_values=True)
        assert cell.type == "value"
        assert cell.value == 42
        assert cell.source == "expression_json"
        assert cell.dataset_id == self.app.security.encode_id(hda.id)

    def test_expression_value_cell_skips_large_value(self):
        hda = self._hda("expression.json")
        assert hda.dataset
        hda.dataset.state = "ok"
        hda.dataset.file_size = COMPARISON_INLINE_EXPRESSION_MAX_BYTES + 1
        with mock.patch("galaxy.managers.comparison_cells.read_expression_json", return_value=42) as read:
            cell = self.cell_builder.dataset_cell(hda, [], inline_expression_values=True)
        assert cell.type == "dataset"
        read.assert_not_called()

    def _hda(self, extension: str) -> model.HistoryDatasetAssociation:
        history = model.History(name="cells", user=self.trans.user)
        self.session.add(history)
        hda = model.HistoryDatasetAssociation(
            history=history, extension=extension, create_dataset=True, sa_session=self.session
        )
        self.session.add(hda)
        self.session.commit()
        return hda
