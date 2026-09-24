.. _api-client-best-practices:

API Client Best Practices
=========================

Galaxy has a long-lived API with a mixture of stable resource endpoints,
compatibility endpoints, and endpoints primarily designed for Galaxy's own web
interface. This page describes the practices external clients should prefer and
the legacy patterns reviewers should flag when assessing a project that drives
Galaxy through the API.

Start From the Supported Contract
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prefer the API contract exposed by a running Galaxy instance:

- Use ``/api/docs`` or ``/api/redoc`` on the target Galaxy server as the
  primary reference for request and response shapes.
- Prefer endpoints that are documented in the OpenAPI schema and backed by
  typed request and response models.
- Treat routes or parameters marked ``deprecated``, ``unstable``, ``BETA``,
  ``experimental``, ``internal``, or "tied to the GUI" as unsuitable for broad
  external use unless the project is prepared to track Galaxy development
  closely.
- If an external project depends on an unstable or UI-oriented endpoint, open a
  Galaxy issue or pull request describing the consumer and the required
  contract. Graduation to a stable API should include documented models,
  tests, and removal of unstable/beta warnings where appropriate.

Use Maintained Client Layers When Possible
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For Python projects, prefer BioBlend_ when it covers the workflow. BioBlend
captures common compatibility details and gives Galaxy maintainers one shared
place to improve client behavior.

For non-Python projects, prefer an OpenAPI-generated or OpenAPI-validated
client when possible. Custom clients in Rust, JavaScript, Java, or another
language are reasonable, but they should still treat the OpenAPI description as
the contract and preserve Galaxy API behavior such as authentication, error
responses, content types, pagination, and redirects.

When a project must bypass BioBlend or generated clients, document why and keep
the Galaxy-specific code isolated behind a small compatibility layer. That
makes future endpoint migrations easier.

Avoid Legacy and UI-Facing API Shapes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following patterns are common in older code and should be reviewed
carefully.

Dataset Preview and Downloads
-----------------------------

The ``/api/datasets/{id}/display`` and
``/api/histories/{history_id}/contents/{id}/display`` routes combine preview,
datatype-rendered display, chunked display, raw access, and download behavior.
They remain compatibility routes, but new clients should prefer a dedicated
download route when the target Galaxy version provides one.

Clients that download datasets must be prepared for redirects. A Galaxy
download endpoint may respond with a ``3xx`` status pointing at an object store
or other backing service instead of streaming bytes from Galaxy itself. Follow
redirects for download requests, do not assume a ``200`` response, and avoid
forwarding Galaxy API credentials to a different host when following a
redirect.

Tool Execution Payloads
-----------------------

Tool execution has accumulated several request shapes. New client code should
prefer model-aware request formats and should validate requests using the
tool-specific schema when possible:

``GET /api/tools/{tool_id}/parameter_request_schema``
    Returns a JSON schema for the tool request API, including map/reduce
    concepts that are not represented well by older flat parameter payloads.

Avoid relying on ``/api/tools/{tool_id}/build`` responses or Galaxy UI form
state as the long-term execution contract. Those structures are useful for
rendering forms, but they are not a stable client-side model of tool execution.

For collection mapping, be explicit about whether the workflow should map or
reduce. A flat ``list`` connected to a ``multiple="true"`` data input is
defined as a reduction: the tool receives the whole list in one job. Directly
using ``{"batch": true, "values": [...]}`` around a flat list for such an
input can produce histories that are lossy when extracted back into workflows.
If the intent is one job per element and faithful workflow extraction matters,
first map ``__BUILD_LIST__`` to create a ``list:list`` collection, then feed
that collection to the ``multiple="true"`` input so Galaxy maps the outer list
and reduces each inner list.

Workflow Export Formats
-----------------------

For workflow download/export, prefer the standard export formats intended for
workflow import and invocation. Formats such as ``editor``, ``run``, and some
instance-specific representations are tied more closely to Galaxy's GUI and
should not be treated as stable interchange formats by external projects.

Library Contents
----------------

Several older library-content routes are retained for compatibility but are
marked deprecated in the API schema. Prefer the current library, folder, and
library dataset endpoints:

- Use ``GET /api/folders/{folder_id}/contents`` instead of deprecated
  ``GET /api/libraries/{library_id}/contents``.
- Use ``GET /api/libraries/datasets/{id}``, ``PATCH
  /api/libraries/datasets/{id}``, and ``DELETE /api/libraries/datasets/{id}``
  instead of deprecated ``/api/libraries/{library_id}/contents/{id}``
  operations.
- Be cautious with archive download routes that are still implemented through
  the legacy web framework and are not fully represented by OpenAPI models.

Review Rubric for API-Driven Projects
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When reviewing or grading a project that drives Galaxy through the API, record
findings in these categories:

- Contract source: Does the project use OpenAPI, BioBlend, or another maintained
  compatibility layer, or does it hard-code undocumented routes and payloads?
- Endpoint stability: Does it depend on deprecated, unstable, beta,
  experimental, internal, or GUI-oriented endpoints?
- Payload fidelity: Does it use typed/model-aware request shapes where
  available, especially for tools, workflows, collections, and libraries?
- Workflow round-trip behavior: If the project creates histories intended for
  workflow extraction or re-invocation, does it avoid known lossy map/reduce
  patterns?
- Download behavior: Does it handle redirects, content disposition, streaming,
  and object-store-backed downloads correctly?
- Upstreaming: If it needs an API behavior that is not stable, does it open a
  Galaxy issue or pull request to document and support that use case?

This rubric is intentionally suitable for both human review and assistant-based
review. The goal is guidance, not prohibition: projects can implement their own
clients, but they should understand where they are taking on compatibility
work.

Keeping Guidance Synchronized
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Endpoint-specific guidance should live as close as possible to the endpoint:
route summaries, route descriptions, Pydantic field descriptions, response
models, ``deprecated=True``, and ``unstable=True`` should all feed the OpenAPI
schema. Cross-cutting guidance and review rules belong on this page.

When adding or changing an API endpoint, update the endpoint documentation and
the relevant client guidance together. If the change creates a new preferred
replacement for a legacy pattern, document both the replacement and the old
pattern clients should avoid.

.. _BioBlend: https://bioblend.readthedocs.io/
