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
- **Normalization:** these differences do not change the hash: line endings, lines containing
  only whitespace, blank lines at the start or end, a UTF-8 byte order mark, and (for inline
  `<text>`) indentation shared by every line. Inline terms and the same terms in a file
  therefore produce the same hash.
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

Keep the default unless the affirmation really is a lasting fact about the user. Do not declare the
same affirmation and terms with `binds="submission"` in one tool and `binds="user"` in another.
Because the hash ignores `binds`, both declarations are the same agreement, and how they combine
is not settled yet.

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
Galaxy's tool framework tests need no changes. This is an automated assertion by the test account,
not a person's affirmation.

Workflow framework tests cannot yet supply one-time acceptances.

## Enforcement

### Where it is checked

Enforcement lives in the default tool action's preconditions, which run before each job is created.
Access checks run first: a user who cannot access the tool sees nothing about its agreements. Every
path that submits through the tool action is covered:

| Entry point                                   | Checked                                                              | Notes                                                                                                     |
| --------------------------------------------- | -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `POST /api/tools` (the tool form, legacy API) | when the request arrives                                             | The whole submission, including a map-over, is checked before any jobs or output collections are created. |
| `POST /api/jobs` (tool requests)              | when the Celery task runs                                            | The request is accepted. If agreements are unmet, the tool request fails.                                 |
| `POST /api/workflows/{id}/invocations`        | when the request arrives, and again for each step as it is scheduled |                                                                                                           |
| Rerun or remap (a new submission)             | when the request arrives                                             | A new submission needs a new authorization.                                                               |
| Resuming a paused job, automatic resubmission | not checked again                                                    | These are the same job, already authorized when it was created.                                           |

### What a job records

Each job stores how each of its agreements was authorized: the agreement hash, plus whether it was a
`one_time` or `persistent` acceptance. A persistent acceptance also references its acceptance event.
Galaxy stores the terms by hash, so the exact text that was affirmed stays available after the tool
changes.

### Workflows

- **Every tool counts:** a workflow's agreements are those of every tool step, including steps in
  subworkflows. One prompt covers each distinct agreement, however many steps declare it.
- **Checked at invocation:** invoking a workflow fails with `403` if any agreement is unaccepted.
  This happens before anything is scheduled.
- **Pinning:** one-time acceptances are pinned to the invocation (and to subinvocations whose own
  steps declare them), so they authorize jobs scheduled long after the request.
- **Revocation during a run:** persistent acceptances are checked again when each step is
  scheduled. If one was revoked in between, the invocation fails with reason
  `license_not_accepted`, which names the step and its agreement ids. Jobs that were already
  created keep running.
- **Steps skipped by `when`:** these still need acceptance. Agreements are collected from every
  tool step before any condition is evaluated.

## User experience

- **Tool form:** the form shows each unaccepted agreement with its terms and the affirmation as a
  checkbox. For `binds="user"` agreements, the user can also choose to have the acceptance
  remembered. A refused submission names the missing agreements and reloads the form.
- **Workflow run forms:** both the simple and expanded forms show one prompt per distinct
  agreement, including those of subworkflow tools.
- **User Preferences:** the _License Agreements_ page lists current persistent acceptances with
  their terms and history, and lets the user revoke each one.

## API

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

The terms are taken from the installed tool. `agreement_hash` confirms which terms the user was
shown: if the tool's terms changed since then, the request fails with `400` and the user must review
them again. Accepting an agreement that is already accepted returns the existing acceptance.

- `GET /api/users/current/license_acceptances` lists current acceptances. Add
  `?include_history=true` to get every accept and revoke event, oldest first.
- `DELETE /api/users/current/license_acceptances/{agreement_hash}` revokes an acceptance.

Users can only view and change their own acceptances.

## Operators

- **Storage:** the migration adds four tables:
  - `tool_license_agreement`: terms by hash;
  - `tool_license_acceptance_event`: append-only accept and revoke events;
  - `job_license_acceptance`;
  - `workflow_invocation_license_acceptance`.
- **Purging users:** both the user manager and `pgcleanup.py` (the `purge_deleted_users` and
  `purge_deleted_users_gdpr` actions) delete a purged user's acceptance events. Jobs keep the agreement hash and how it
  was authorized, with the event reference cleared. Terms are kept. Events the purged user
  recorded for another account are kept, without the attribution.
- **Remote tool evaluation:** this does not read license files. Agreements are checked before a
  job exists.
- **Changing terms:** if the terms or affirmation on disk change, existing persistent acceptances
  stop satisfying the tool, and users are prompted again. A one-time acceptance pinned to a
  workflow invocation authorizes only the hash it named. If a tool reload changes that hash, later
  steps of the invocation fail with `license_not_accepted`.
