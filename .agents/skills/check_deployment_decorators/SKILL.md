---
name: check_deployment_decorators
description: Audit Galaxy API and browser tests for deployment requirement decorators and tool availability skips. Use when changing tests that may run against an external Galaxy or adding tests to the deployment runner.
---

# Check deployment decorators

Check the selected tests against the behavior they actually exercise. Read
`doc/source/dev/writing_tests.md` under **Test Decorators** and **Deployment
Tests**, then inspect `lib/galaxy_test/base/decorators.py` and
`test/deployment/usegalaxystar.bash` in the current branch. The runner's marker
expression and runtime skip settings define which tests it can run.

## Scope the audit

- Identify changed API and browser test methods from the user's target or the
  branch diff against its intended base. Include tests in files proposed for
  the runner, even if the runner has not yet been edited. Do not treat unit or
  integration tests as deployment candidates without an explicit reason.
- Trace each selected test through setup, fixtures, parametrized cases, and
  called helpers. Inspect helper implementations when their name does not make
  the effect clear. A text search is a starting point, not proof that a test
  requires a decorator.
- Inspect class and wrapper decorators. `@managed_history` already adds
  `requires_new_history`. `@requires_new_user` and `@requires_new_library`
  already add `requires_admin`.

## Match effects to annotations

| Effect exercised by the test | Annotation or guard |
| --- | --- |
| Admin-only API/UI action, admin key, named-user creation or switch through `_different_user()` | `@requires_admin` |
| Registration of a new account | `@requires_new_user` |
| Creation of a library | `@requires_new_library` |
| A distinct history is needed when a shared history might be configured | `@requires_new_history` |
| Publication of a dataset, workflow, or other object | `@requires_new_published_objects` |
| A Celery worker is needed for the tested behavior | `@requires_celery` |
| A specific installed tool is needed | `@requires_tool_id("id")` or `@skip_without_tool("id")` |

Ordinary jobs, datasets, and workflows require no annotation. Anonymous
`_different_user(anon=True)` does not create a user. `using_requirement(...)`
inside a helper protects a path at runtime, but the test still needs a marker
when the deployment runner must deselect it before execution. A test can need
several annotations. Flag a missing guard for a configured datatype, plugin,
or external service only when the code depends on it, and suggest the existing
skip helper that fits the dependency.

## Verify and report

For each candidate, compare the needed requirements with its effective pytest
markers. If dependencies are installed, use `pytest --collect-only -q -m
'requires_admin or requires_new_user or requires_new_library or
requires_new_published_objects or requires_celery' <test-file>` or a narrower
marker expression to confirm selection. Collection checks marker wiring only.
Do not send requests to a public deployment as part of this audit.

Report missing or incorrect annotations with file and test names, the concrete
call path that requires them, and the decorator to add. Distinguish confirmed
gaps from cases that need a live deployment or more context. If asked to fix
the tests, make the smallest annotation change and rerun relevant collection
and local tests.
