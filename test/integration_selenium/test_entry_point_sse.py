"""Playwright E2E tests for the SSE pipeline.

Covers two flows:

* Interactive-tool entry-point updates: when an entry point transitions to
  ``configured`` server-side (the runner's port-routing hook calls
  ``configure_entry_points``), the logged-in user's browser receives the
  ``entry_point_update`` event and the entry-point store refetches, without
  the 10 s polling interval. The server side is stubbed by creating the Job
  and entry point directly and calling
  ``InteractiveToolManager.configure_entry_points`` on the live app — the
  exact dispatch site in production.

* History updates in the multi-history view: when a history that is *not*
  the user's current history is mutated (dataset upload via the API), the
  multi-history view panel for that history refreshes via SSE without
  switching the current history. Polling is disabled when
  ``enable_sse_updates`` is true, so an item appearing in the non-current
  panel implies the SSE-driven refresh path fired.
"""

from galaxy.util.wait import wait_on
from galaxy_test.selenium.framework import (
    managed_history,
    selenium_test,
)
from ._base_interactive_tools import BaseInteractiveToolsSeleniumIntegration

SSE_CONNECT_TIMEOUT_SECONDS = 15
SSE_EVENT_TIMEOUT_SECONDS = 15


class TestEntryPointSSESeleniumIntegration(BaseInteractiveToolsSeleniumIntegration):
    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        config["enable_celery_tasks"] = False
        # App.vue only calls entryPointStore.startWatchingEntryPoints() when
        # interactivetools_enable is True (set by the base), and the store only opens an SSE
        # connection when enable_sse_updates is True. Without both,
        # __galaxy_sse_connected never becomes true and the gate below times out.
        config["enable_sse_updates"] = True

    def _wait_for_sse_connected(self) -> None:
        """Block until the frontend confirms the SSE pipeline is live."""
        wait_on(
            lambda: True if self.execute_script("return window.__galaxy_sse_connected === true") else None,
            "window.__galaxy_sse_connected === true",
            timeout=SSE_CONNECT_TIMEOUT_SECONDS,
        )

    def _last_sse_event_ts(self) -> int:
        return self.execute_script("return window.__galaxy_sse_last_event_ts || 0") or 0

    def _wait_for_sse_event_after(self, baseline_ts: int) -> None:
        wait_on(
            lambda: True if self._last_sse_event_ts() > baseline_ts else None,
            "window.__galaxy_sse_last_event_ts advanced past baseline",
            timeout=SSE_EVENT_TIMEOUT_SECONDS,
        )

    @selenium_test
    @managed_history
    def test_entry_point_update_pushed_via_sse(self):
        """configure_entry_points should trigger an SSE push the client observes."""
        # Navigate home so the entry-point store is mounted and subscribed.
        self.home()
        self._wait_for_sse_connected()
        baseline_ts = self._last_sse_event_ts()
        self.screenshot("entry_point_sse_before")

        job_id, _ep_id = self._create_it_job_with_entry_point(tool_port=8888)

        self._configure_entry_points(job_id, tool_port=8888)

        # Prove the update arrived via SSE (not polling): the composable's
        # event-timestamp hook only advances when useSSE's listener fires.
        self._wait_for_sse_event_after(baseline_ts)
        self.screenshot("entry_point_sse_after")

    @selenium_test
    def test_history_update_in_multi_view_for_non_current_history(self):
        """SSE history_update events should refresh non-current panels in the multi-history view.

        Polling is disabled when ``enable_sse_updates`` is true, so the only path
        that can surface a new dataset in a non-current history's panel is the
        SSE handler in ``historyStore.handleHistorySSEEvent``.
        """
        self.home()
        first_history_id = self.current_history_id()
        # New history via the API populator. The browser's current history is
        # tracked separately and must remain the first one — this test
        # exercises the *non-current* update path.
        second_history_id = self.dataset_populator.new_history(name="multi-view-sse-target")
        self.home()
        assert (
            self.current_history_id() == first_history_id
        ), "Browser current history flipped; cannot assert non-current SSE update path."

        self.open_history_multi_view()
        self._wait_for_sse_connected()
        baseline_ts = self._last_sse_event_ts()
        self.screenshot("history_multi_view_sse_before")

        # Upload to the non-current history. wait=False — terminal dataset
        # state doesn't matter here; the SSE event fires on any history
        # mutation, and the assertion below only requires the new item to
        # appear in the multi-view panel.
        self.dataset_populator.new_dataset(second_history_id, content="sse content", wait=False)

        # Prove SSE delivered the event (timestamp only advances on a real push).
        self._wait_for_sse_event_after(baseline_ts)

        # And that the multi-history view rendered the new item without a
        # current-history switch. With polling disabled, the only way for the
        # second history's panel to surface hid=1 is via handleHistorySSEEvent.
        item_selector = self.content_item_by_attributes(hid=1, multi_history_panel=True)
        self.wait_for_visible(item_selector, wait_type=self.wait_types.JOB_COMPLETION)
        assert self.current_history_id() == first_history_id
        self.screenshot("history_multi_view_sse_after")
