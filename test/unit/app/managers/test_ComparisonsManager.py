from decimal import Decimal
from itertools import product
from typing import get_args
from unittest import mock

from sqlalchemy import event

from galaxy import model
from galaxy.managers.comparison_cells import (
    COMPARISON_INLINE_EXPRESSION_MAX_BYTES,
    ComparisonAccess,
    ComparisonCellBuilder,
)
from galaxy.managers.comparisons import ComparisonsManager
from galaxy.managers.hdas import HDASerializer
from galaxy.managers.histories import HistoryManager
from galaxy.schema.comparisons import (
    OutputRunsQuery,
    StepRunsQuery,
    ToolRunsQuery,
    WorkflowStepModuleType,
)
from galaxy.schema.fields import Security
from galaxy.workflow.modules import module_types
from .base import BaseTestCase


def test_step_module_type_names_every_module():
    assert set(get_args(WorkflowStepModuleType)) == set(module_types)


class TestComparisonsManagerStatementCount(BaseTestCase):
    def set_up_managers(self):
        super().set_up_managers()
        self.session = self.app.model.session
        cell_builder = _cell_builder(self.app)
        self.comparisons_manager = ComparisonsManager(self.session, cell_builder)
        Security.security = self.app.security
        self.foreign_users = 0
        self.tool_id = "cat1"

    def test_step_runs_statement_count_independent_of_row_count(self):
        for mapped, metadata in product((False, True), (False, True)):
            counts = [self._step_runs_statement_count(invocations, mapped, metadata) for invocations in (1, 5)]
            assert counts[0] == counts[1], f"mapped={mapped}, metadata={metadata}: statements grow with rows {counts}"

    def _step_runs_statement_count(self, invocations: int, mapped: bool, metadata: bool) -> int:
        stored_workflow_id = self._stored_workflow_with_runs(invocations, mapped).id
        access = _access(self.trans.user)
        self.session.expunge_all()
        query = StepRunsQuery.model_construct(
            workflow_id=stored_workflow_id, step_label="target", metadata_elements=_metadata_elements(metadata)
        )
        (table, total), statement_count = self._count_statements(
            lambda: self.comparisons_manager.step_runs(access, stored_workflow_id, query)
        )
        assert total == invocations
        assert len(table.rows) == invocations
        for row in table.rows:
            assert row.cells.pop("input:foreign").model_dump() == {"type": "missing", "reason": "inaccessible"}
            assert all(cell.type != "missing" for cell in row.cells.values())
        return statement_count

    def test_tool_runs_statement_count_independent_of_row_count(self):
        for mapped, metadata in product((False, True), (False, True)):
            counts = [self._tool_runs_statement_count(submissions, mapped, metadata) for submissions in (1, 5)]
            assert counts[0] == counts[1], f"mapped={mapped}, metadata={metadata}: statements grow with rows {counts}"

    def test_tool_runs_matches_tool_shed_versions_without_wildcards(self):
        user = self.trans.user
        history = model.History(name="shed runs", user=user)
        self.session.add(history)
        base = "toolshed.example.org/repos/owner/repo/my_tool"
        tool_ids = [
            f"{base}/1.0",
            f"{base}/2.0",
            "toolshed.example.org/repos/owner/repo/myXtool/1.0",
            f"{base}_extra/1.0",
        ]
        jobs = {}
        for tool_id in tool_ids:
            self.tool_id = tool_id
            jobs[tool_id] = self._job(history, user)
            self.session.add(jobs[tool_id])
        self.session.commit()
        query = ToolRunsQuery.model_construct(tool_id=f"{base}/3.0", include_workflow_jobs=True)
        table, total = self.comparisons_manager.tool_runs(_access(user), query)
        encoded = {self.app.security.encode_id(jobs[tool_id].id) for tool_id in tool_ids[:2]}
        assert total == 2
        assert {row.run.id for row in table.rows} == encoded
        percent_query = ToolRunsQuery.model_construct(
            tool_id="toolshed.example.org/repos/owner/repo/my%tool/1.0", include_workflow_jobs=True
        )
        assert self.comparisons_manager.tool_runs(_access(user), percent_query)[1] == 0

    def test_tool_runs_state_filter_matches_any_mapped_member(self):
        self.tool_id = "mapped_states"
        self._stored_workflow_with_runs(1, mapped=True, member_states=("ok", "error"))
        query = ToolRunsQuery.model_construct(tool_id=self.tool_id, states=["error"], include_workflow_jobs=True)
        table, total = self.comparisons_manager.tool_runs(_access(self.trans.user), query)
        assert total == 1
        (row,) = table.rows
        assert row.run.model == "ImplicitCollectionJobs"
        assert row.run.states == {"ok": 1, "error": 1}
        assert row.state == "error"

    def test_step_runs_state_filter_matches_any_mapped_member(self):
        stored_workflow_id = self._stored_workflow_with_runs(1, mapped=True, member_states=("ok", "error")).id
        query = StepRunsQuery.model_construct(workflow_id=stored_workflow_id, step_label="target", states=["error"])
        table, total = self.comparisons_manager.step_runs(_access(self.trans.user), stored_workflow_id, query)
        assert total == 1
        (row,) = table.rows
        assert row.step_job is not None and row.step_job.model == "ImplicitCollectionJobs"
        assert row.state == "error"

    def test_tool_runs_excludes_mapped_workflow_jobs(self):
        self.tool_id = "mapped_in_workflow"
        user = self.trans.user
        self._stored_workflow_with_runs(1, mapped=True)
        query = ToolRunsQuery.model_construct(tool_id=self.tool_id, include_workflow_jobs=False)
        assert self.comparisons_manager.tool_runs(_access(user), query)[1] == 0
        history = model.History(name="outside workflows", user=user)
        plain = self._job(history, user)
        self.session.add_all([history, plain])
        self.session.commit()
        table, total = self.comparisons_manager.tool_runs(_access(user), query)
        assert total == 1
        assert [row.run.id for row in table.rows] == [self.app.security.encode_id(plain.id)]

    def test_admin_sees_inaccessible_items(self):
        stored_workflow_id = self._stored_workflow_with_runs(1, mapped=False).id
        query = StepRunsQuery.model_construct(workflow_id=stored_workflow_id, step_label="target")
        table, _ = self.comparisons_manager.step_runs(
            _access(self.trans.user, is_admin=True), stored_workflow_id, query
        )
        (row,) = table.rows
        assert row.cells["input:foreign"].type == "dataset"

    def _tool_runs_statement_count(self, submissions: int, mapped: bool, metadata: bool) -> int:
        self.tool_id = f"compared_{submissions}_{mapped}_{metadata}"
        self._stored_workflow_with_runs(submissions, mapped)
        access = _access(self.trans.user)
        self.session.expunge_all()
        query = ToolRunsQuery.model_construct(
            tool_id=self.tool_id, metadata_elements=_metadata_elements(metadata), include_workflow_jobs=True
        )
        (table, total), statement_count = self._count_statements(
            lambda: self.comparisons_manager.tool_runs(access, query)
        )
        assert total == len(table.rows) == submissions
        assert table.tool_versions_available == ["1.0.0"]
        for row in table.rows:
            assert row.run.model == ("ImplicitCollectionJobs" if mapped else "Job")
            assert row.via is not None and row.via.step_label == "target"
            assert row.cells.pop("input:foreign").model_dump() == {"type": "missing", "reason": "inaccessible"}
            assert set(row.cells) == {"input:input1", "output:out_file1"}
            assert all(cell.type != "missing" for cell in row.cells.values())
        return statement_count

    def test_output_runs_statement_count_independent_of_row_count(self):
        for metadata in (False, True):
            counts = [self._output_runs_statement_count(invocations, metadata) for invocations in (1, 5)]
            assert counts[0] == counts[1], f"metadata={metadata}: statements grow with rows {counts}"

    def test_output_runs_flags_duplicate_output_labels(self):
        stored_workflow, first_outputs = self._stored_workflow_with_output_runs(2)
        access = _access(self.trans.user)
        query = OutputRunsQuery.model_construct(workflow_id=stored_workflow.id)
        table, _ = self.comparisons_manager.output_runs(access, stored_workflow.id, query)
        columns = {column.key: column for column in table.columns}
        assert columns["output:out"].duplicate
        assert not columns["output:val"].duplicate
        for row in table.rows:
            cell = row.cells["output:out"]
            assert cell.type == "dataset"
            assert cell.id == self.app.security.encode_id(first_outputs[row.run.id])

    def test_output_runs_output_labels_filter_outputs_only(self):
        stored_workflow, first_outputs = self._stored_workflow_with_output_runs(2)
        query = OutputRunsQuery.model_construct(workflow_id=stored_workflow.id, output_labels=["val"])
        cell_builder = self.comparisons_manager.cell_builder
        with mock.patch.object(cell_builder, "load_hdas", wraps=cell_builder.load_hdas) as load_hdas:
            table, _ = self.comparisons_manager.output_runs(_access(self.trans.user), stored_workflow.id, query)
        assert [column.key for column in table.columns] == ["input:in", "input:foreign", "parameter:p", "output:val"]
        assert table.output_labels_available == ["out", "val"]
        # filtered-out outputs are never loaded
        loaded_hda_ids = set(load_hdas.call_args.args[0])
        assert loaded_hda_ids and not loaded_hda_ids & set(first_outputs.values())

    def test_output_runs_present_in_versions_counts_versions_without_labels(self):
        user = self.trans.user
        stored_workflow = model.StoredWorkflow()
        stored_workflow.user = user
        stored_workflow.name = "labels added later"
        steps = []
        for label in (None, "tool"):
            workflow = model.Workflow()
            workflow.name = stored_workflow.name
            workflow.stored_workflow = stored_workflow
            step = model.WorkflowStep()
            step.order_index = 0
            step.type = "tool"
            step.label = label
            workflow.steps.append(step)
            steps.append(step)
        output = model.WorkflowOutput(steps[1], output_name="out_file1", label="out")
        stored_workflow.latest_workflow = steps[1].workflow
        self.session.add(stored_workflow)
        for step in steps:
            history = model.History(name="run", user=user)
            invocation = model.WorkflowInvocation()
            invocation.workflow = step.workflow
            invocation.history = history
            invocation.state = "scheduled"
            self.session.add_all([history, invocation])
            if step is steps[1]:
                invocation.add_output(output, step, self._hda(history))
        self.session.commit()
        query = OutputRunsQuery.model_construct(workflow_id=stored_workflow.id)
        table, _ = self.comparisons_manager.output_runs(_access(user), stored_workflow.id, query)
        (column,) = table.columns
        assert (column.key, column.present_in_versions) == ("output:out", [1])
        assert [row.version for row in table.rows] == [1, 0]
        assert table.rows[1].cells["output:out"].model_dump() == {"type": "missing", "reason": "not_in_version"}

    def _output_runs_statement_count(self, invocations: int, metadata: bool) -> int:
        stored_workflow, _ = self._stored_workflow_with_output_runs(invocations)
        stored_workflow_id = stored_workflow.id
        access = _access(self.trans.user)
        self.session.expunge_all()
        query = OutputRunsQuery.model_construct(
            workflow_id=stored_workflow_id, metadata_elements=_metadata_elements(metadata)
        )
        (table, total), statement_count = self._count_statements(
            lambda: self.comparisons_manager.output_runs(access, stored_workflow_id, query)
        )
        assert total == len(table.rows) == invocations
        for row in table.rows:
            assert row.cells.pop("input:foreign").model_dump() == {"type": "missing", "reason": "inaccessible"}
            assert row.cells.pop("output:val").model_dump() == {"type": "missing", "reason": "skipped"}
            assert row.cells["parameter:p"].model_dump() == {
                "type": "value",
                "value": 5,
                "source": "parameter",
                "dataset_id": None,
            }
            assert all(cell.type != "missing" for cell in row.cells.values())
        return statement_count

    def _stored_workflow_with_output_runs(self, invocations: int) -> tuple[model.StoredWorkflow, dict[str, int]]:
        """Two versions with labelled inputs and outputs; the second declares output label ``out`` twice."""
        user = self.trans.user
        stored_workflow = model.StoredWorkflow()
        stored_workflow.user = user
        stored_workflow.name = "outputs compared"
        versions = []
        for version in range(2):
            workflow = model.Workflow()
            workflow.name = "outputs compared"
            workflow.stored_workflow = stored_workflow
            steps = {}
            for order_index, (label, step_type) in enumerate(
                [("in", "data_input"), ("foreign", "data_input"), ("p", "parameter_input"), ("tool", "tool")]
            ):
                step = model.WorkflowStep()
                step.order_index = order_index
                step.type = step_type
                step.label = label
                workflow.steps.append(step)
                steps[label] = step
            outputs = [model.WorkflowOutput(steps["tool"], output_name="out_file1", label="out")]
            if version:
                outputs.append(model.WorkflowOutput(steps["tool"], output_name="out_file2", label="out"))
            value_output = model.WorkflowOutput(steps["tool"], output_name="out_value", label="val")
            versions.append((workflow, steps, outputs, value_output))
        stored_workflow.latest_workflow = versions[-1][0]
        self.session.add(stored_workflow)
        self.session.flush()
        foreign_history = self._foreign_private_history()
        invocation_outputs = []
        for i in range(invocations):
            workflow, steps, outputs, value_output = versions[i % 2]
            history = model.History(name=f"run {i}", user=user)
            invocation = model.WorkflowInvocation()
            invocation.workflow = workflow
            invocation.history = history
            invocation.state = "scheduled"
            self.session.add_all([history, invocation])
            invocation.add_input(self._hda(history), step=steps["in"])
            invocation.add_input(self._private_hda(foreign_history), step=steps["foreign"])
            invocation.add_input(5, step=steps["p"])
            output_hdas = [self._hda(history) for _ in outputs]
            for workflow_output, hda in zip(outputs, output_hdas):
                invocation.add_output(workflow_output, steps["tool"], hda)
            invocation.add_output(value_output, steps["tool"], {"__class__": "NoReplacement"})
            invocation_outputs.append((invocation, output_hdas[0]))
        self.session.commit()
        return stored_workflow, {self.app.security.encode_id(inv.id): hda.id for inv, hda in invocation_outputs}

    def _count_statements(self, call):
        """Result of ``call`` (serialized too, which must not lazy-load) and the SQL statements it ran."""
        statements: list[str] = []

        def count(conn, cursor, statement, *args):
            statements.append(statement)

        engine = self.session.get_bind()
        event.listen(engine, "before_cursor_execute", count)
        try:
            result = call()
            result[0].model_dump(mode="json")
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return result, len(statements)

    def _stored_workflow_with_runs(
        self, invocations: int, mapped: bool, member_states: tuple[str, ...] = ("ok", "ok")
    ) -> model.StoredWorkflow:
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
        foreign_history = self._foreign_private_history()
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
                self._mapped_step(invocation_step, history, user, foreign_history, member_states)
            else:
                job = self._job(history, user)
                job.add_input_dataset("input1", self._hda(history))
                job.add_input_dataset("foreign", self._private_hda(foreign_history))
                invocation_step.job = job
                output = self._hda(history)
                job.add_output_dataset("out_file1", output)
                invocation_step.add_output("out_file1", output)
        self.session.commit()
        return stored_workflow

    def _foreign_private_history(self) -> model.History:
        self.foreign_users += 1
        name = f"foreign{self.foreign_users}"
        foreign_user = self.user_manager.create(email=f"{name}@example.org", username=name, password="password")
        foreign_history = model.History(name="foreign", user=foreign_user)
        self.session.add(foreign_history)
        return foreign_history

    def _private_hda(self, history) -> model.HistoryDatasetAssociation:
        hda = self._hda(history)
        security_agent = self.app.security_agent
        role = security_agent.get_private_user_role(history.user, auto_create=True)
        security_agent.set_dataset_permission(hda.dataset, {security_agent.permitted_actions.DATASET_ACCESS: [role]})
        return hda

    def _mapped_step(self, invocation_step, history, user, foreign_history, member_states) -> None:
        icj = model.ImplicitCollectionJobs(populated_state="ok")
        for order_index, state in enumerate(member_states):
            job = self._job(history, user)
            job.state = state
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
        output_hdca.implicit_input_collections.append(
            model.ImplicitlyCreatedDatasetCollectionInput("foreign", self._hdca(foreign_history))
        )
        invocation_step.implicit_collection_jobs = icj
        invocation_step.add_output("out_file1", output_hdca)

    def _job(self, history, user) -> model.Job:
        job = model.Job()
        job.user = user
        job.history = history
        job.tool_id = self.tool_id
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
        self.cell_builder = _cell_builder(self.app)
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
        hda.dataset.file_size = Decimal(3)
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
        hda.dataset.file_size = Decimal(COMPARISON_INLINE_EXPRESSION_MAX_BYTES + 1)
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


def _cell_builder(app) -> ComparisonCellBuilder:
    return ComparisonCellBuilder(app.model.session, HDASerializer(app), app.security_agent, app[HistoryManager])


def _metadata_elements(metadata: bool) -> list[str]:
    return ["data_lines"] if metadata else []


def _access(user: model.User, is_admin: bool = False) -> ComparisonAccess:
    return ComparisonAccess(
        user_id=user.id, role_ids=frozenset(role.id for role in user.all_roles()), is_admin=is_admin
    )
