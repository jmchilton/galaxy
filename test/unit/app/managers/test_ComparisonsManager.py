from itertools import product
from typing import get_args

import pytest
from sqlalchemy import event

from galaxy import model
from galaxy.datatypes.binary import Bam
from galaxy.managers.comparison_cells import (
    cap_metadata_value,
    COMPARISON_INLINE_EXPRESSION_MAX_BYTES,
    COMPARISON_METADATA_MAX_ITEMS,
    ComparisonAccess,
    ComparisonCellBuilder,
    inlinable_expression,
    scalar_metadata_keys,
)
from galaxy.managers.comparison_records import (
    ComparisonRecordLoader,
    LabelledStep,
)
from galaxy.managers.comparison_states import SUMMARY_STATES
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


class TestComparisonsManager(BaseTestCase):
    def set_up_managers(self):
        super().set_up_managers()
        self.session = self.app.model.session
        cell_builder = _cell_builder(self.app)
        self.comparisons_manager = ComparisonsManager(self.session, ComparisonRecordLoader(self.session), cell_builder)
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
            lambda: self.comparisons_manager.step_runs(access, query)
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

    def test_tool_runs_state_filter_matches_batch_summary_state(self):
        user = self.trans.user
        history = model.History(name="mixed batches", user=user)
        self.session.add(history)
        self.tool_id = "mixed_batches"
        batch_states = [
            ["ok", "ok"],
            ["ok", "error"],
            ["ok", "failed"],
            ["ok", "running", "queued"],
            ["new", "queued"],
            ["new"],
            ["ok", "skipped"],
            ["skipped", "skipped"],
            ["ok", "paused"],
            ["stopped", "paused"],
            ["deleted"],
        ]
        batches = []
        for states in batch_states:
            icj = model.ImplicitCollectionJobs(populated_state="ok")
            for order_index, state in enumerate(states):
                job = self._job(history, user)
                job.state = state
                association = model.ImplicitCollectionJobsJobAssociation()
                association.order_index = order_index
                association.implicit_collection_jobs = icj
                association.job = job
                self.session.add(association)
            batches.append(icj)
        self.session.commit()
        shown_states: dict[str, str | None] = {self.app.security.encode_id(icj.id): None for icj in batches}
        for state in (*SUMMARY_STATES, "failed"):
            query = ToolRunsQuery.model_construct(tool_id=self.tool_id, include_workflow_jobs=True, states=[state])
            table, total = self.comparisons_manager.tool_runs(_access(user), query)
            assert total == len(table.rows)
            for row in table.rows:
                assert row.state == state
                assert shown_states[row.run.id] is None
                shown_states[row.run.id] = state
        # every batch matches exactly the state it shows
        assert None not in shown_states.values()

    def test_labelled_steps_only_versions_with_the_label(self):
        stored_workflow = model.StoredWorkflow()
        stored_workflow.user = self.trans.user
        stored_workflow.name = "relabelled"
        steps = []
        for label, step_type in (("before", "data_input"), ("target", "tool")):
            workflow = model.Workflow()
            workflow.name = "relabelled"
            workflow.stored_workflow = stored_workflow
            step = model.WorkflowStep()
            step.order_index = 0
            step.type = step_type
            step.label = label
            workflow.steps.append(step)
            steps.append((workflow, step))
        stored_workflow.latest_workflow = steps[-1][0]
        self.session.add(stored_workflow)
        self.session.commit()
        records = ComparisonRecordLoader(self.session)
        workflow, step = steps[1]
        assert records.labelled_steps(stored_workflow.id, "target") == {workflow.id: LabelledStep(step.id, "tool")}
        assert records.labelled_steps(stored_workflow.id, "missing") == {}

    def test_admin_sees_inaccessible_items(self):
        stored_workflow_id = self._stored_workflow_with_runs(1, mapped=False).id
        query = StepRunsQuery.model_construct(workflow_id=stored_workflow_id, step_label="target")
        table, _ = self.comparisons_manager.step_runs(_access(self.trans.user, is_admin=True), query)
        (row,) = table.rows
        assert row.cells["input:foreign"].type == "dataset"

    def test_multiple_input_members_checked_for_access(self):
        user = self.trans.user
        history = model.History(name="multiple input", user=user)
        self.session.add(history)
        self.tool_id = "multiple_input_tool"
        job = self._job(history, user)
        own, foreign = self._hda(history), self._private_hda(self._foreign_private_history())
        for name, hda in (("f1", own), ("f11", own), ("f12", foreign)):
            job.add_input_dataset(name, hda)
        self.session.add(job)
        self.session.commit()
        query = ToolRunsQuery.model_construct(tool_id=self.tool_id, include_workflow_jobs=True)
        table, _ = self.comparisons_manager.tool_runs(_access(user), query)
        (row,) = table.rows
        cell = row.cells["input:f1"]
        assert cell.type == "dataset_list"
        own_cell, foreign_cell = cell.items
        assert own_cell.type == "dataset"
        assert own_cell.id == self.app.security.encode_id(own.id)
        assert foreign_cell.model_dump() == {"type": "missing", "reason": "inaccessible"}

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
        table, _ = self.comparisons_manager.output_runs(access, query)
        columns = {column.key: column for column in table.columns}
        assert columns["output:out"].duplicate
        assert not columns["output:val"].duplicate
        for row in table.rows:
            cell = row.cells["output:out"]
            assert cell.type == "dataset"
            assert cell.id == self.app.security.encode_id(first_outputs[row.run.id])

    def test_output_runs_new_filter_matches_unset_state(self):
        stored_workflow, first_outputs = self._stored_workflow_with_output_runs(2)
        unset_id, scheduled_id = first_outputs
        invocation = self.session.get(model.WorkflowInvocation, self.app.security.decode_id(unset_id))
        assert invocation
        invocation.state = None
        self.session.commit()
        access = _access(self.trans.user)
        for state, expected in (("new", unset_id), ("scheduled", scheduled_id)):
            query = OutputRunsQuery.model_construct(workflow_id=stored_workflow.id, states=[state])
            table, total = self.comparisons_manager.output_runs(access, query)
            assert [(row.run.id, row.state) for row in table.rows] == [(expected, state)]
            assert total == 1

    def _output_runs_statement_count(self, invocations: int, metadata: bool) -> int:
        stored_workflow, _ = self._stored_workflow_with_output_runs(invocations)
        stored_workflow_id = stored_workflow.id
        access = _access(self.trans.user)
        self.session.expunge_all()
        query = OutputRunsQuery.model_construct(
            workflow_id=stored_workflow_id, metadata_elements=_metadata_elements(metadata)
        )
        (table, total), statement_count = self._count_statements(
            lambda: self.comparisons_manager.output_runs(access, query)
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
                self._mapped_step(invocation_step, history, user, foreign_history)
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

    def _mapped_step(self, invocation_step, history, user, foreign_history) -> None:
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


def test_scalar_metadata_keys_skip_file_metadata():
    keys = scalar_metadata_keys(Bam.metadata_spec)
    assert "bam_index" in Bam.metadata_spec
    assert "bam_index" not in keys
    assert "bam_version" in keys


@pytest.mark.parametrize(
    "value,expected",
    [
        (list(range(60)), list(range(COMPARISON_METADATA_MAX_ITEMS))),
        (tuple(range(60)), list(range(COMPARISON_METADATA_MAX_ITEMS))),
        ({f"k{i}": i for i in range(60)}, {f"k{i}": i for i in range(COMPARISON_METADATA_MAX_ITEMS)}),
        (["a", "b"], ["a", "b"]),
        (7, 7),
    ],
)
def test_cap_metadata_value(value, expected):
    assert cap_metadata_value(value) == expected


@pytest.mark.parametrize(
    "extension,state,file_size,purged,expected",
    [
        ("expression.json", "ok", 3, False, True),
        ("expression.json", "ok", COMPARISON_INLINE_EXPRESSION_MAX_BYTES, False, True),
        ("expression.json", "ok", COMPARISON_INLINE_EXPRESSION_MAX_BYTES + 1, False, False),
        # size unknown
        ("expression.json", "ok", None, False, False),
        ("expression.json", "running", 3, False, False),
        ("expression.json", "ok", 3, True, False),
        ("txt", "ok", 3, False, False),
    ],
)
def test_inlinable_expression(extension, state, file_size, purged, expected):
    dataset = model.Dataset(state=state)
    dataset.file_size = file_size
    hda = model.HistoryDatasetAssociation(extension=extension, dataset=dataset)
    hda.purged = purged
    assert inlinable_expression(hda) is expected


def _cell_builder(app) -> ComparisonCellBuilder:
    return ComparisonCellBuilder(app.model.session, HDASerializer(app), app.security_agent, app[HistoryManager])


def _metadata_elements(metadata: bool) -> list[str]:
    return ["data_lines"] if metadata else []


def _access(user: model.User, is_admin: bool = False) -> ComparisonAccess:
    return ComparisonAccess(
        user_id=user.id, role_ids=frozenset(role.id for role in user.all_roles()), is_admin=is_admin
    )
