# Tool License Agreements

Some tools wrap software whose terms limit who may use it, or for what. Common examples are
academic-only and non-commercial licenses. A tool can declare a `<license_agreement>`, and Galaxy
then refuses to create its jobs until the submitting user affirms that agreement. This applies
whether the job comes from the tool form, a workflow, or the API.

This document describes that contract for tool authors, Galaxy operators, and API clients. The
element itself is specified in the [tool XML reference](schema.md#tool-requirements-license-agreement).

```{important}
A license agreement records that an authenticated account supplied an affirmation to authorize a
job. It does not prove that a person read the terms or that the statement is true, and Galaxy does
not check whether a wrapper's terms are legally adequate.
```

## License agreements versus `license`

Tools already have a `license` attribute (`<tool license="MIT">`). It holds an SPDX identifier
for the **wrapper's** license. It is metadata only: Galaxy never prompts for it and never enforces
it.

A `<license_agreement>` is different. It describes restrictions on **running** the tool and is
enforced on every job. The two are independent, and a tool may declare either one, both, or
neither.

## Authoring

### A minimal agreement

```xml
<tool id="meme_meme" name="MEME" version="5.5.8+galaxy0" profile="26.2">
    <requirements>
        <requirement type="package" version="5.5.8">meme</requirement>
        <license_agreement id="meme-suite-academic" version="2" path="meme_license.txt">
            <label>MEME Suite academic-use license</label>
            <url>https://meme-suite.org/meme/doc/copyright.html</url>
            <affirmation>I certify that I am not using this tool for commercial purposes, under the MEME Suite academic-use license terms.</affirmation>
        </license_agreement>
    </requirements>
    ...
</tool>
```

- **Profile:** declaring an agreement requires `profile="26.2"` or newer. A tool with an older
  profile that declares one fails to load, and `planemo lint` reports it.
- **Terms:** `path` names a UTF-8 file relative to the tool directory. The file must stay inside
  that directory. Prefer `path`, since the license file usually ships with the software and
  several tools can share one copy. For short terms you can write them inline in a `<text>`
  element instead. Start the inline terms on the line after `<text>` so their indentation can be
  removed. Each agreement must use exactly one of `path` or `<text>`.
- **Affirmation:** a single line stating what the user is asserting. Write it for the person
  running the tool.
- **Login:** a tool that declares an agreement always requires login, because only an account can
  make an affirmation.

### What an agreement's identity is

Galaxy identifies an agreement by its `agreement_hash`. This is a SHA-256 of a versioned
canonical JSON document containing the affirmation and the terms. Nothing else is included.

- **Display-only attributes:** `id`, `version`, `label` and `url` are shown to users and recorded
  with acceptances, but they are not part of the hash. Fixing a label or URL never asks anyone
  to accept again. Galaxy never fetches `url`.
- **What prompts again:** changing the wording of the affirmation or the terms produces a new
  agreement, and every user must affirm it again.
- **Normalization:** these differences do not change the hash: line endings, whitespace on lines
  that contain nothing else (they become empty lines, which still count), blank lines at the start
  or end, a UTF-8 byte order mark, and (for inline `<text>` only) indentation shared by every line.
  Trailing whitespace on other lines does change the hash. Files are not dedented, so inline terms
  match a file only when the file has no shared indentation.
- **Shared agreements:** tools that declare the same affirmation and terms declare the _same_
  agreement, even with different `id`s. A suite of tools sharing one license file shares one
  acceptance.

### Choosing `binds`

`binds` says what the affirmation is about:

`submission` (the default)
: The affirmation is a statement about the work, such as _"I certify that I am not using this tool
for commercial purposes."_ Circumstances can change between runs, so the user affirms it for
each submission. Galaxy never remembers it.

`user`
: The affirmation is a statement about the person, such as _"I have read and agree to these
terms."_ The user may accept it once, and Galaxy remembers that until the user revokes it.

Keep the default unless the affirmation really is a lasting fact about the user.

```{warning}
Do not declare the same affirmation and terms with `binds="submission"` in one place and
`binds="user"` in another. The hash ignores `binds`, so Galaxy treats both as the same agreement and
uses whichever declaration it sees first. This is a known defect: a persistent acceptance can then
satisfy the submission-bound declaration, and a workflow can pass its request-time check but fail
when the submission-bound step is scheduled.
```

### What one tool can express

A tool may declare several agreements. **Every one of them** must be accepted before its jobs run,
so the agreements combine with AND. There is no way to express alternatives, such as "academic
use _or_ a purchased commercial license". Splitting an OR condition into two agreements would
require both, and would wrongly exclude legitimately licensed users. Agreements are also
unconditional: they apply to every run of the tool, whatever its parameter values.

### Tools that cannot declare agreements

Some execution paths cannot carry a submission's affirmation. For these, Galaxy either rejects the
combination or never runs the tool on the user's behalf:

- **Custom tool actions:** a tool whose action creates jobs without Galaxy's execution checks (for
  example `model_operations`) fails to load if it declares an agreement.
- **Data source tools:** `data_source` and `data_source_async` tools fail to load if they declare
  an agreement. The remote site's callback creates the job, and it cannot carry the user's
  affirmation. This applies to `binds="user"` agreements as well, even for users who already have
  a persistent acceptance.
- **Datatype converters:** being a converter is decided by `datatypes_conf.xml`, not by the tool,
  so Galaxy never selects a converter that declares an agreement. This covers implicit conversion
  of tool inputs, the dataset _Convert_ options, and collection conversion. Users can still run
  such a converter directly from the tool panel, where it prompts like any other tool.

### Testing

Tool tests send one-time acceptances for every agreement the tool declares, so `planemo test` and
Galaxy's tool framework tests need no changes. This requires a Galaxy server and a
`galaxy-tool-util` release that both include license agreement support. This is an automated assertion by the test account,
not a person's affirmation.

Workflow framework tests cannot yet supply one-time acceptances.

## Enforcement

### Where it is checked

Enforcement lives in the default tool action's preconditions, which run before each job is created.
For each submission they also run once up front, before any jobs or output collections exist, so a
refused map-over leaves nothing behind. For tool submissions, access checks run first: a user who
cannot access the tool learns nothing about its agreements. Every path that submits through the
tool action is covered.

The tool form submits to `POST /api/jobs` when tool requests and Celery are enabled and the tool
has typed parameters. Otherwise it uses `POST /api/tools`.

| Entry point                                   | Checked                                                              | Notes                                                                                                                    |
| --------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `POST /api/tools`                             | when the request arrives                                             |                                                                                                                          |
| `POST /api/jobs` (tool requests)              | when the Celery task runs                                            | Tool access and undeclared hashes are checked when the request arrives. If agreements are unmet, the tool request fails. |
| `POST /api/workflows/{id}/invocations`        | when the request arrives, and again for each step as it is scheduled |                                                                                                                          |
| Rerun or remap                                | as for the endpoint used                                             | A new submission, so it needs a new authorization.                                                                       |
| Resuming a paused job, automatic resubmission | not checked again                                                    | These are the same job, already authorized when it was created.                                                          |

### What a job records

Each job stores how each of its agreements was authorized: the agreement hash, plus whether it was a
`one_time` or `persistent` acceptance. A persistent acceptance also references its acceptance event.
Galaxy stores the terms by hash, so the exact text that was affirmed stays in the database after the
tool changes. There is no API or UI for a job's license records yet.

### Workflows

- **Every tool counts:** a workflow's agreements are those of every tool step, including steps in
  subworkflows. One prompt covers each distinct agreement, however many steps declare it.
- **Checked at invocation:** invoking a workflow fails with `403` if any agreement is unaccepted.
  This happens before anything is scheduled.
- **Pinning:** each invocation and subinvocation pins the one-time acceptances its own tool steps
  declare, so they authorize jobs scheduled long after the request.
- **Revocation during a run:** persistent acceptances are checked again when each step is
  scheduled. If one was revoked in between, the invocation fails with a message whose `reason` is
  `license_not_accepted`, with `workflow_step_id` and `details` (the comma-separated agreement ids).
  Jobs that were already created keep running.
- **Steps skipped by `when`:** these still need acceptance. Agreements are collected from every
  tool step before any condition is evaluated.

## User experience

- **Tool form:** the form shows each agreement with its terms, and each unaccepted one with its
  affirmation as a checkbox. Run stays disabled until every one is affirmed. For `binds="user"`
  agreements, the user can also choose to have the acceptance remembered. That is recorded before
  the job is submitted, so it remains even if the submission fails. A refused submission names the
  missing agreements and reloads the form.
- **Workflow run forms:** both the simple and expanded forms show one prompt per distinct
  agreement, including those of subworkflow tools. An invocation that fails at scheduling shows the
  `license_not_accepted` message.
- **User Preferences:** the _License Agreements_ page lists current persistent acceptances with
  their terms and history, and lets the user revoke each one.

## API

The examples use Galaxy's test fixture tools (`test/functional/tools/license_agreement_*.xml`).
Hashes are shortened.

There are two ways to authorize a submission:

- **One-time acceptance:** include the agreement hash in `one_time_license_acceptances` on the
  submission. It authorizes that submission only. Use this for `binds="submission"` agreements;
  it also works for `binds="user"` ones.
- **Persistent acceptance:** record it once through the user's acceptances API. It satisfies every
  later submission, and only `binds="user"` agreements can be accepted this way.

Hashes must come from the agreements the tool or workflow declares. Galaxy rejects an undeclared
hash with `400`, and it never accepts terms supplied by the client.

### Discover

```console
$ curl -H "x-api-key: $KEY" "$GALAXY/api/tools/license_agreement_path_tool/license_agreements"
[
  {
    "agreement_hash": "3f1c…",
    "affirmation": "I certify that I am not using this tool for commercial purposes.",
    "terms": "Test Tool Non-Commercial License\n…",
    "id": "license_agreement_path",
    "version": "1",
    "label": "Test Tool Non-Commercial License",
    "url": "https://example.org/test-tool-license",
    "binds": "submission",
    "accepted": false
  }
]
```

`accepted` is `true` only when the user's persistent acceptance satisfies the agreement. Pass
`?tool_version=` to choose a version. `GET /api/tools/{id}/build` (the tool form) includes the same
list as `license_agreements`.

For a workflow, `GET /api/workflows/{id}/license_agreements` (with `?version=` optional) returns
the same fields plus `steps`. Each step gives its `path` of order indices through subworkflows, and
its `tool_id` and `tool_version`. Show the `terms` and `affirmation` to the person before
submitting on their behalf.

### Submit with one-time acceptance

```console
$ curl -X POST -H "x-api-key: $KEY" -H "Content-Type: application/json" "$GALAXY/api/tools" -d '{
    "tool_id": "license_agreement_path_tool",
    "history_id": "…",
    "inputs": {"input": "x"},
    "one_time_license_acceptances": ["3f1c…"]
  }'
```

`POST /api/jobs` and `POST /api/workflows/{id}/invocations` take the same
`one_time_license_acceptances` field.

### Refusals

An unaccepted agreement on `POST /api/tools` or a workflow invocation returns `403` with error code
`403009` (`TOOL_EXECUTION_PRECONDITION_UNMET`). The `unmet` list gives each failed condition:

```json
{
  "err_code": 403009,
  "err_msg": "Tool 'license_agreement_path_tool' requires accepting license agreements [license_agreement_path].",
  "unmet": [
    {
      "kind": "license_agreement",
      "message": "Tool 'license_agreement_path_tool' requires accepting license agreements [license_agreement_path].",
      "details": {
        "tool_id": "license_agreement_path_tool",
        "tool_version": "1.0",
        "agreements": [
          {
            "id": "license_agreement_path",
            "agreement_hash": "3f1c…",
            "binds": "submission",
            "…": "…"
          }
        ]
      },
      "remedy_route": null
    }
  ]
}
```

The workflow invocation refusal has the same structure. Its `message` starts "Workflow requires
accepting license agreements", and its `details` holds only `agreements`, where each entry is a
full record from the workflow discovery endpoint: terms, `accepted` and `steps` included.

The same error code with `"kind": "access"` means the tool itself is not accessible. For an
anonymous user it has `"remedy_route": "/login/start"`.

Tool requests are checked asynchronously. `POST /api/jobs` succeeds, but the tool request then
fails, and `GET /api/tool_requests/{id}` shows `"state": "failed"`. Its `state_message` holds
`err_msg`, `err_code` and the same `unmet` list.

### Persistent acceptance

```console
$ curl -X POST -H "x-api-key: $KEY" -H "Content-Type: application/json" \
    "$GALAXY/api/users/current/license_acceptances" -d '{
    "tool_id": "license_agreement_variant_tool",
    "license_id": "license_agreement_path",
    "agreement_hash": "9a07…"
  }'
```

The payload names a tool declaring the agreement (`tool_id`, plus `tool_version` if needed), the
agreement's `id` as `license_id`, and its `agreement_hash`. For a workflow agreement, take
`tool_id` and `tool_version` from any entry in its `steps`. The terms are taken from the installed
tool. `agreement_hash` confirms which terms the user was shown: if the tool's terms changed since
then, the request fails with `400` and the user must review them again.

The request also fails with `400` when:

- the agreement is `binds="submission"`;
- the tool is unknown;
- the tool does not declare `license_id`.

The response is `{"agreement": {...}, "event": {...}}`: the stored terms and the accept event.
Accepting an agreement that is already accepted returns the existing acceptance.

- `GET /api/users/current/license_acceptances` lists current acceptances. Add
  `?include_history=true` to get every accept and revoke event, oldest first.
- `DELETE /api/users/current/license_acceptances/{agreement_hash}` revokes an acceptance. It
  returns `204`, or `404` when the agreement is not currently accepted.

Users can only view and change their own acceptances. This applies to administrators too.

Workflow and tool runs started through Galaxy's MCP server or its AI agents cannot send
`one_time_license_acceptances`. These runs fail unless every agreement is `binds="user"` and
already accepted.

## Operators

- **Storage:** the migration adds four tables:
  - `tool_license_agreement`: terms by hash;
  - `tool_license_acceptance_event`: append-only accept and revoke events;
  - `job_license_acceptance`;
  - `workflow_invocation_license_acceptance`.
- **Purging users:** both the user manager and `pgcleanup.py` (the `purge_deleted_users` and
  `purge_deleted_users_gdpr` actions) delete a purged user's acceptance events. Jobs keep the agreement hash and how it
  was authorized, with the event reference cleared. Terms are kept. Events the purged user
  recorded for another account are kept, without the attribution. The model allows such
  administrator-granted events, but no API records them yet.
- **Remote tool evaluation:** this does not read license files. Agreements are checked before a
  job exists.
- **Changing terms:** terms are read when the tool loads, so edits to a license file take effect
  only after the tool is reloaded or Galaxy restarts. A changed affirmation or terms means existing
  persistent acceptances no longer satisfy the tool, and users are prompted again. The old
  acceptance still appears under User Preferences. A one-time acceptance pinned to a
  workflow invocation authorizes only the hash it named. If a tool reload changes that hash, later
  steps of the invocation fail with `license_not_accepted`.
