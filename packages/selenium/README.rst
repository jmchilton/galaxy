
.. image:: https://badge.fury.io/py/galaxy-selenium.svg
   :target: https://pypi.org/project/galaxy-selenium/


Galaxy Browser Automation Framework
------------------------------------

.. note::
   The package is named ``galaxy-selenium`` for historical reasons, but a more accurate name
   would be ``galaxy-browser-automation`` since it supports both Selenium and Playwright backends.

Overview
--------

This package provides a browser automation framework for Galaxy_ with:

* **Multi-backend support**: Selenium and Playwright backends with a unified API
* **Protocol-based architecture**: Clean separation between Galaxy logic and browser interaction
* **Comprehensive testing**: Full unit test coverage for both backends
* **CLI tooling**: Utilities for building command-line automation scripts
* **Type safety**: Full type hints with mypy validation

* Code: https://github.com/galaxyproject/galaxy

.. _Galaxy: http://galaxyproject.org/


Architecture
------------

.. rubric:: Core Interfaces

The framework is built around two main protocol interfaces:

**HasDriverProtocol** (``has_driver_protocol.py``)
    Defines ~60+ browser automation operations including:

    - Element finding (by ID, selector, XPath, etc.)
    - Wait methods (visible, clickable, absent, etc.)
    - Interactions (click, hover, drag-and-drop, keyboard input)
    - Navigation (URLs, frames, alerts)
    - JavaScript execution
    - Accessibility testing (axe-core integration)

**WebElementProtocol** (``web_element_protocol.py``)
    Defines the common element API:

    - ``text``, ``click()``, ``send_keys()``, ``clear()``
    - ``get_attribute()``, ``is_displayed()``, ``is_enabled()``
    - ``find_element()``, ``find_elements()``
    - ``value_of_css_property()`` for CSS introspection


.. rubric:: Architecture Diagram

::

    ┌─────────────────────────────────────────────────────┐
    │         Galaxy Application Layer                     │
    │                                                       │
    │  NavigatesGalaxy (navigates_galaxy.py)              │
    │  - Galaxy-specific page objects                      │
    │  - Workflow interactions                             │
    │  - History management                                │
    │  - Tool execution                                    │
    └────────────────┬────────────────────────────────────┘
                     │ extends
                     ↓
    ┌─────────────────────────────────────────────────────┐
    │      Browser Automation Abstraction Layer           │
    │                                                       │
    │  HasDriverProxy (has_driver_proxy.py)               │
    │  - Delegates to HasDriverProtocol implementation     │
    │  - Runtime backend selection via composition         │
    └────────────────┬────────────────────────────────────┘
                     │ uses
                     ↓
    ┌──────────────────────────────────┬──────────────────┐
    │   HasDriverProtocol              │                  │
    │   (has_driver_protocol.py)       │                  │
    │   - Abstract interface           │                  │
    │   - ~60+ operations              │                  │
    └──────────────┬───────────────────┴──────────────────┘
                   │ implemented by
         ┌─────────┴──────────┐
         ↓                    ↓
    ┌─────────────┐    ┌──────────────────┐
    │  HasDriver  │    │ HasPlaywright    │
    │             │    │ Driver           │
    │ Selenium    │    │                  │
    │ backend     │    │ Playwright       │
    │             │    │ backend          │
    └──────┬──────┘    └────────┬─────────┘
           │                    │
           ↓                    ↓
    ┌─────────────┐    ┌──────────────────┐
    │ WebElement  │    │ PlaywrightElement│
    │ (Selenium)  │    │ (wrapper)        │
    │             │    │                  │
    │ implements  │    │ implements       │
    │ protocol    │    │ protocol         │
    └─────────────┘    └──────────────────┘
           │                    │
           └──────────┬─────────┘
                      ↓
           WebElementProtocol
           (web_element_protocol.py)


.. rubric:: Implementations

**Selenium Backend** (``has_driver.py``)
    - Uses Selenium WebDriver
    - Direct WebElement support (implements protocol natively)
    - Mature, widely-used automation framework
    - Supports remote execution (Selenium Grid)

**Playwright Backend** (``has_playwright_driver.py``)
    - Uses Playwright sync API
    - PlaywrightElement wrapper (adapts ElementHandle to protocol)
    - Modern automation with auto-waiting
    - Fast and reliable for modern web apps
    - Local execution only (no remote support)

Both implementations:

- Share identical test suite (150+ parametrized tests)
- Provide consistent API via protocols
- Support headless and headed modes
- Include full type hints


.. rubric:: Separation of Concerns

::

    Application Logic          │  Browser Automation
    (Galaxy-specific)         │  (Generic, reusable)
    ─────────────────────────────────────────────────
    navigates_galaxy.py       │  has_driver_protocol.py
    - Galaxy UI interactions  │  - Abstract interface
    - Workflow automation     │  - Element finding
    - History operations      │  - Wait strategies
    - Tool wrappers           │  - Interactions
                              │
    smart_components.py       │  has_driver.py
    - Galaxy component        │  - Selenium impl
      wrappers                │
    - Page object patterns    │  has_playwright_driver.py
                              │  - Playwright impl
                              │
                              │  web_element_protocol.py
                              │  - Element interface

**Key Principle**: Galaxy-specific logic lives in ``navigates_galaxy.py`` and extends the
generic browser automation protocols. This separation allows:

- Testing browser automation independently
- Reusing automation primitives across projects
- Switching backends without changing application code
- Clear boundaries between concerns


Testing
-------

The framework includes comprehensive unit tests in ``test/unit/selenium/test_has_driver.py``:

- **Parametrized tests**: Every test runs against Selenium, Playwright, and proxied backends
- **150+ test cases** covering all protocol methods
- **Test fixtures**: Reusable HTML pages served via local HTTP server
- **Scope-optimized**: Session-scoped server, function-scoped drivers

Run tests from the package directory::

    # All tests
    uv run pytest tests/seleniumtests/test_has_driver.py -v

    # Specific test class
    uv run pytest tests/seleniumtests/test_has_driver.py::TestElementFinding -v

    # Type checking
    make mypy

.. warning::
    Always run pytest from the package directory (``packages/selenium/``), not from the
    monorepo root. Running from root can cause fixture scope issues.


Driving Galaxy with gxui
-----------------------

``galaxy-selenium`` includes ``gxui``, a command-line interface that keeps a Galaxy
browser context in a session daemon. It uses the same navigation methods and
smart components as the end-to-end tests, without requiring ``galaxy-test-selenium``.

Install the package and Playwright's browser, then configure a named profile::

    pip install galaxy-selenium
    playwright install chromium
    gxui config init
    gxui config profile add local --url http://localhost:8080
    gxui config set default_profile local
    gxui config set auth.username learner@example.org
    gxui start
    gxui login
    gxui history-new "My Analysis"
    gxui stop

``login`` prompts for missing credentials in a terminal, masking the password.
In scripts, set ``GXUI_PASSWORD``, configure ``auth.password_env``, or use
``gxui login --password-stdin``. Missing credentials produce an actionable error
when stdin is not a terminal. Passwords sent to the daemon are excluded from
process arguments, busy status, authentication errors and transcripts.

Bare ``gxui`` reports session status; ``gxui help`` lists verbs, and
``gxui help VERB`` describes their arguments. ``gxui login --help`` describes
client-side login options. The client can also run as
``python -m galaxy.selenium.gxui.client``.

.. rubric:: Profiles and precedence

The default configuration path is ``$XDG_CONFIG_HOME/gxui/config.yml``, falling
back to ``~/.config/gxui/config.yml``. ``--config`` overrides ``GXUI_CONFIG``.
Select a profile with ``--profile``, then ``GXUI_PROFILE``, then
``default_profile``. Configuration flags go before the command; ``start`` also
accepts them after the command. A profile name is the default session name;
``--session``, ``GXUI_SESSION`` or a configured ``session`` can override it.
Without a profile, the session name is ``default``.

.. code-block:: yaml

    version: 1
    default_profile: test
    defaults:
      headless: true
      timeout_multiplier: 1
      idle_timeout: 3600
    profiles:
      test:
        url: https://test.galaxyproject.org
        auth:
          username: learner@example.org
          password_env: GXUI_TEST_PASSWORD
      local:
        url: http://localhost:8080
        headless: false
        auth:
          username: developer@example.org
          password: local-development-password

Every runtime setting follows ``CLI > environment > profile > defaults >
builtin``. Environment variables use ``GXUI_`` plus the uppercase setting name;
the URL retains its existing name ``GXUI_GALAXY_URL``.

==================== =========================== ==========================
Setting              Environment                 Builtin
==================== =========================== ==========================
url                  GXUI_GALAXY_URL             http://localhost:8080
headless             GXUI_HEADLESS               true
port                 GXUI_PORT                   0 (free CDP port)
idle_timeout         GXUI_IDLE_TIMEOUT           3600 seconds; 0 disables
timeout_multiplier   GXUI_TIMEOUT_MULTIPLIER     1
client_timeout       GXUI_CLIENT_TIMEOUT         110 seconds
artifacts            GXUI_ARTIFACTS              $GXUI_HOME/<session>
playwright_cli       GXUI_PLAYWRIGHT_CLI         unset
session              GXUI_SESSION                profile name or default
==================== =========================== ==========================

Use ``--headed`` and ``--headless`` to override either boolean value. Other CLI
names use hyphens, for example ``--idle-timeout``. ``GXUI_HOME`` separately
controls daemon sockets, logs and the default artifact location.

Inspect and edit configuration without starting a browser::

    gxui config profile list
    gxui --profile test config show --resolved --sources
    gxui config set defaults.headless false
    gxui --profile test config set idle_timeout 0
    gxui --profile test config set auth.password_env GXUI_TEST_PASSWORD
    gxui --profile local config set auth.password
    gxui --profile local config unset auth.password
    gxui --profile test start --headless

``config set auth.password`` prompts when its value is omitted. ``config show``
redacts literal passwords and does not read password environment references or
keyrings. Edits are validated and atomically written with owner-only permissions.
Setting an authentication source replaces the previous source. Profile names
use letters, numbers, underscores, dots and hyphens. Unknown keys and duplicate
YAML keys are rejected.

A profile's authentication belongs to its entire Galaxy base URL, including a
path prefix such as ``/galaxy/``. Overriding the URL clears that profile's
credentials and saved state when the target differs. Explicit ``GXUI_USERNAME``
and ``GXUI_PASSWORD`` can supply credentials for the selected target; changing
the account clears the previously selected authentication source. ``start`` is
idempotent for an existing session bound to the same URL and profile. Target
mismatches produce an error. Config edits apply to subsequent starts; ``status``
reports the running session's captured profile, URL and browser mode.

Existing flat ``galaxy_selenium_context.yml`` files containing ``login_email``
and ``login_password`` remain readable through ``--config``. Config editing
commands leave those legacy files read-only; create a profile config to migrate.

.. rubric:: Browser login and saved authentication

For SSO or two-factor login, complete sign-in in a headed browser::

    gxui --profile test login --interactive

The daemon changes a headless browser to a headed browser when necessary,
preserving its current storage state. It waits for Galaxy to report an actual
logged-in user before saving authentication. ``--timeout`` sets the interactive
login deadline (default: 300 seconds). ``gxui login --save`` saves an ordinary
password login or an existing authenticated session.

Saved state includes cookies and local storage. Files are written with owner-only
permissions under ``$XDG_STATE_HOME/gxui/<session>-auth.json`` (default:
``~/.local/state/gxui/``) and bound to the Galaxy base URL. For named profiles,
successful saving replaces ``auth`` with ``username`` and ``storage_state`` so
future starts restore it automatically. Profile storage-state paths may be
relative to the config directory. Explicit ``--storage-state`` or
``GXUI_STORAGE_STATE`` paths are relative to the current directory. Externally
created Playwright storage-state files remain supported. An expired session
requires signing in again; ``login --interactive`` works without a password.
Switching to a different logged-in account requires ``logout`` first.

.. rubric:: Optional keyring

Install ``galaxy-selenium[keyring]`` to read passwords from an OS keyring.
Configure ``auth.username`` and ``auth.keyring: true``. The service name is
``gxui:<canonical Galaxy base URL>`` (without the trailing slash), and the account
name is the configured username. Populate that service/account with the keyring's
own tools. The package has no required keyring dependency; missing backends
produce a clear error. Each profile selects one authentication source:
``password``, ``password_env``, ``keyring`` or ``storage_state``.

Reusable upload helpers are available independently of the daemon::

    from galaxy.selenium.context import GalaxySeleniumContextImpl
    from galaxy.selenium.upload_activity_helpers import UsesUploadActivity

    class UploadSession(GalaxySeleniumContextImpl, UsesUploadActivity):
        pass

    session = UploadSession({"driver": {"backend_type": "playwright", "headless": True}})
    try:
        session.home()
        session.upload_context("paste-content").stage_paste_content("example data").start()
    finally:
        session.configured_driver.quit()


Building CLI Tools
------------------

The ``cli.py`` module provides infrastructure for building command-line automation tools.

.. rubric:: Core Components

**add_selenium_arguments(parser)**
    Adds standard CLI arguments:

    - ``--selenium-browser``: Browser choice (chrome, firefox, auto)
    - ``--selenium-headless``: Headless mode flag
    - ``--backend``: Backend selection (selenium, playwright)
    - ``--galaxy_url``: Target Galaxy instance URL
    - ``--selenium-remote``: Remote execution (Selenium only)

**DriverWrapper**
    Adapts argparse args to a NavigatesGalaxy instance:

    - Handles backend selection
    - Manages virtual display (for headless Selenium)
    - Provides Galaxy navigation utilities
    - Cleanup via ``finish()`` method

.. rubric:: Example: dump_tour.py

The ``scripts/dump_tour.py`` script demonstrates CLI tool development:

.. code-block:: python

    #!/usr/bin/env python
    import argparse
    from galaxy.selenium import cli

    def main(argv=None):
        args = _arg_parser().parse_args(argv)
        driver_wrapper = cli.DriverWrapper(args)

        # Use driver_wrapper for automation
        callback = DumpTourCallback(driver_wrapper, args.output)
        driver_wrapper.run_tour(args.tour, tour_callback=callback)

    def _arg_parser():
        parser = argparse.ArgumentParser(description="Walk a Galaxy tour")
        parser.add_argument("tour", help="tour to walk")
        parser.add_argument("-o", "--output", help="screenshot output dir")
        parser = cli.add_selenium_arguments(parser)  # Add standard args
        return parser

    class DumpTourCallback:
        def handle_step(self, step, step_index: int):
            self.driver_wrapper.save_screenshot(f"{output}/{step_index}.png")

Usage::

    # With Selenium backend
    python dump_tour.py my_tour.yaml --backend selenium --selenium-headless

    # With Playwright backend
    python dump_tour.py my_tour.yaml --backend playwright --galaxy_url http://localhost:8080


.. rubric:: Building Your Own CLI Tool

1. **Import the CLI utilities**::

    from galaxy.selenium import cli

2. **Create argument parser**::

    parser = argparse.ArgumentParser(description="My automation tool")
    parser.add_argument("--my-option", help="Custom option")
    parser = cli.add_selenium_arguments(parser)  # Add standard args

3. **Create DriverWrapper**::

    args = parser.parse_args()
    driver_wrapper = cli.DriverWrapper(args)

4. **Use NavigatesGalaxy API**::

    # driver_wrapper has all NavigatesGalaxy methods
    driver_wrapper.navigate_to(url)
    driver_wrapper.click_selector("#my-button")
    driver_wrapper.wait_for_selector_visible(".result")

5. **Clean up**::

    driver_wrapper.finish()  # Quits driver and stops virtual display


Development
-----------

.. rubric:: Package Structure

::

    packages/selenium/
    ├── galaxy/selenium/          # Symlink to lib/galaxy/selenium/
    ├── tests/seleniumtests/      # Symlink to test/unit/selenium/
    ├── README.rst                # This file
    └── pyproject.toml

    lib/galaxy/selenium/          # Actual source code
    ├── has_driver_protocol.py    # Protocol interface
    ├── has_driver.py             # Selenium implementation
    ├── has_playwright_driver.py  # Playwright implementation
    ├── web_element_protocol.py   # Element interface
    ├── playwright_element.py     # Element wrapper
    ├── navigates_galaxy.py       # Galaxy-specific logic
    ├── smart_components.py       # Component wrappers
    ├── cli.py                    # CLI utilities
    └── scripts/
        └── dump_tour.py          # Example CLI tool

    test/unit/selenium/           # Actual tests
    ├── conftest.py               # Pytest fixtures
    ├── test_has_driver.py        # Main test suite
    └── fixtures/                 # HTML test pages


.. rubric:: Running Commands

Always use ``uv run`` from the package directory::

    # Run tests
    uv run pytest tests/seleniumtests/test_has_driver.py -v

    # Type checking
    make mypy

    # Linting
    uv run ruff check .


.. rubric:: Adding New Low-Level Browser Operations

Low-level operations are generic browser automation primitives that work with both backends.

**Manual Process:**

1. **Add to protocol** (``has_driver_protocol.py``)::

    @abstractmethod
    def my_new_operation(self, param: str) -> bool:
        """Do something useful."""
        ...

2. **Implement in Selenium** (``has_driver.py``)::

    def my_new_operation(self, param: str) -> bool:
        # Selenium implementation
        return self.driver.do_something(param)

3. **Implement in Playwright** (``has_playwright_driver.py``)::

    def my_new_operation(self, param: str) -> bool:
        # Playwright implementation
        return self.page.do_something(param)

4. **Update proxy** (``has_driver_proxy.py``)::

    def my_new_operation(self, param: str) -> bool:
        """Do something useful."""
        return self._driver_impl.my_new_operation(param)

5. **Add tests** (``test_has_driver.py``)::

    def test_my_new_operation(self, has_driver_instance, base_url):
        """Test new operation works on both backends."""
        has_driver_instance.navigate_to(f"{base_url}/test.html")
        result = has_driver_instance.my_new_operation("test")
        assert result is True

**Automated Process:**

Use the ``/add-browser-operation`` slash command to automate these steps::

    /add-browser-operation scroll element to center of viewport

This command will generate all the necessary code across all files and create tests.


.. rubric:: Adding New Smart Component Operations

Smart component operations are higher-level conveniences that may require adding low-level
operations first. These operations make Galaxy components more ergonomic to use in tests.

**When to Add Smart Operations:**

- When you find yourself repeating a pattern of low-level operations
- When Galaxy-specific UI patterns need convenient wrappers
- When you want to express test intent more clearly

**Process:**

1. **Determine if low-level support exists**:

   Check if the required browser operation exists in ``HasDriverProtocol``. If not,
   add it first using the process above (or ``/add-browser-operation``).

2. **Add to SmartTarget** (``smart_components.py``):

   Add a method to the ``SmartTarget`` class::

    def my_smart_operation(self, **kwds):
        """High-level operation description."""
        # Delegate to has_driver protocol methods
        element = self._has_driver.wait_for_visible(self._target, **kwds)
        return self._has_driver.my_low_level_operation(element)

3. **Consider return value wrapping**:

   If your operation returns a Component or Target, wrap it::

    def get_child_component(self, name: str):
        """Get a child component and wrap it smartly."""
        child = self._target.get_child(name)
        return self._wrap(child)  # Returns SmartTarget

4. **Add tests** (``test/unit/selenium/test_smart_components.py``):

   Test with both backends using the ``has_driver_instance`` fixture::

    def test_my_smart_operation(self, has_driver_instance, base_url):
        has_driver_instance.navigate_to(f"{base_url}/smart_components.html")

        # Use SmartComponent wrapping
        component = SmartComponent(MyComponent(), has_driver_instance)
        result = component.my_target.my_smart_operation()

        assert result is not None

**Example: Adding a "wait_for_and_hover" operation**

This demonstrates when you need to add a low-level operation first:

1. **Check low-level support**: ``hover()`` already exists in ``HasDriverProtocol`` ✓

2. **Add to SmartTarget**::

    def wait_for_and_hover(self, **kwds):
        """Wait for element to be visible and hover over it."""
        element = self._has_driver.wait_for_visible(self._target, **kwds)
        self._has_driver.hover(element)
        return element

3. **Usage in tests**::

    # Before: Multiple steps
    element = driver.wait_for_visible(component.menu)
    driver.hover(element)

    # After: One expressive call
    component.menu.wait_for_and_hover()

**Example: Adding operation requiring new low-level support**

When the operation needs a new browser primitive:

1. **Add low-level operation** (see "Adding New Low-Level Browser Operations"):

   Add ``scroll_to_center(element)`` to protocols and implementations

2. **Add smart wrapper**::

    def wait_for_and_scroll_to_center(self, **kwds):
        """Wait for element and scroll it to viewport center."""
        element = self._has_driver.wait_for_visible(self._target, **kwds)
        self._has_driver.scroll_to_center(element)
        return element

3. **Test both levels**:

   - Test low-level in ``test_has_driver.py``
   - Test smart wrapper in ``test_smart_components.py``


See Also
--------

* `Selenium Documentation <https://www.selenium.dev/documentation/>`_
* `Playwright Documentation <https://playwright.dev/python/>`_
* `Galaxy Testing Documentation <https://docs.galaxyproject.org/en/latest/dev/writing_tests.html>`_
