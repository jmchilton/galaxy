from unittest.mock import Mock

from sqlalchemy import event

from galaxy import model
from galaxy.app_unittest_utils.galaxy_mock import MockApp
from galaxy.schema.wes import State
from galaxy.webapps.galaxy.services.wes import WesService
from galaxy.work.context import WorkRequestContext


def test_list_runs_loads_completions_in_page_query():
    app = MockApp()
    session = app.model.session
    user = model.User(email="wes@example.org", password="password", username="wes")
    history = model.History(user=user, name="wes")
    workflow = model.Workflow()
    workflow.stored_workflow = model.StoredWorkflow(user=user, name="wes")
    session.add_all([user, history, workflow])
    for job_state_summary in ({"ok": 2}, {"ok": 1, "error": 1}, None):
        invocation = model.WorkflowInvocation()
        invocation.workflow = workflow
        invocation.history = history
        invocation.state = "completed" if job_state_summary else "scheduled"
        session.add(invocation)
        if job_state_summary:
            session.add(
                model.WorkflowInvocationCompletion(workflow_invocation=invocation, job_state_summary=job_state_summary)
            )
    session.commit()
    user_id = user.id
    session.expunge_all()

    trans = WorkRequestContext(app, user=session.get(model.User, user_id))
    # list_runs uses neither the workflows service nor the config.
    service = WesService(Mock(), Mock(), app.security)
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        runs = service.list_runs(trans, page_size=10).runs or []
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert [run.state for run in runs] == [State.RUNNING, State.EXECUTOR_ERROR, State.COMPLETE]
    assert len(statements) == 1, statements
