from uuid import uuid4

from galaxy.model import (
    InteractiveToolEntryPoint,
    Job,
)
from .framework import SeleniumIntegrationTestCase


class BaseInteractiveToolsSeleniumIntegration(SeleniumIntegrationTestCase):
    ensure_registered = True

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        config["interactivetools_enable"] = True

    def _create_it_job_with_entry_point(self, tool_port: int = 8888, name: str | None = None) -> tuple[int, int]:
        """Create a running job with one unconfigured entry point, owned by the browser's user."""
        # Use the browser's cookie-authenticated user, not the API interactor's
        # default: SSE connects under the Selenium-registered user, and the
        # dispatch's user_id must match or push_to_user finds no queues.
        user_info = self.api_get("users/current")
        user_id = self._decode_id(user_info["id"])
        sa_session = self._app.model.context
        job = Job()
        job.user_id = user_id
        job.tool_id = "interactivetool_simple"
        job.state = Job.states.RUNNING
        sa_session.add(job)
        sa_session.flush()
        ep = InteractiveToolEntryPoint(
            job=job,
            tool_port=tool_port,
            entry_url="/",
            name=name or f"selenium entry {uuid4()}",
            label="selenium",
            requires_domain=True,
            requires_path_in_url=False,
            requires_path_in_header_named=None,
        )
        sa_session.add(ep)
        sa_session.commit()
        return job.id, ep.id

    def _configure_entry_points(self, job_id: int, tool_port: int = 8888) -> None:
        """Stub the runner's port-routing hook so the job's entry points become active."""
        job = self._app.model.context.get(Job, job_id)
        assert job is not None
        self._app.interactivetool_manager.configure_entry_points(
            job,
            {str(tool_port): {"host": "host.invalid", "port": 12345, "protocol": "http"}},
        )
