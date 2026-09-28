# Deferred data with a separate Pulsar service

Experiment date: 2026-09-26. Galaxy baseline: `a63da1dfd19`.

The eight-case matrix completed with **4 passed, 4 failed** in 178.01 seconds
on the same Galaxy revision and `pulsar-galaxy-lib==0.15.15`.

Pulsar's real HTTP API runs in its own process with a separate staging directory.
The REST runner uses `default_file_action: transfer`; files cross the HTTP API
instead of being copied directly between directories. A macOS sandbox denies
Pulsar and its child processes all reads and writes under Galaxy's test storage
root. A startup probe confirms that reading a Galaxy-owned file raises
`PermissionError` before the service accepts jobs.

This enforces the absent job-storage boundary on one machine. It is not a run on
a second host: Galaxy code and its Python environment remain readable on both
sides, and both processes share the host's network. The experiment is opt-in
and macOS-specific; a container or separate-host version is still needed for
portable CI and deployment validation.

| Input                           | Local evaluation / directory metadata | Remote evaluation / extended metadata                                |
| ------------------------------- | ------------------------------------- | -------------------------------------------------------------------- |
| Ordinary text                   | pass                                  | fail: `cat '' > ''`                                                  |
| Deferred text (`base64://`)     | pass                                  | materializes correctly at Pulsar; fail: empty output path            |
| Deferred BAM (`base64://`)      | pass                                  | materializes correctly at Pulsar; fail: empty output path            |
| Deferred text (controlled HTTP) | pass; Galaxy downloads                | Pulsar evaluator downloads and materializes; fail: empty output path |

### Evidence and failure boundary

- All four local-evaluation cases produce the expected output bytes. Local
  deferred cases retain materialized input bytes in Galaxy's job `inputs/`.
- All four remote jobs have input files in Pulsar's staging directory. A
  separate byte comparison confirms that every input matches its fixture,
  including the 3,592-byte BAM.
- The remote ordinary-input command is `cat '' > ''`. For deferred inputs,
  the input argument is the correct Pulsar staging filename, but the output
  argument is still empty. The shell exits with code 1.
- `metadata/params.json` and `metadata/outputs_populated/datasets_attrs.txt`
  exist for all four remote jobs. This reproduction is not the missing-runtime
  or missing-metadata-files failure reported in the original issue.
- The HTTP fixture holds each connection open while `lsof` identifies its
  client process. Local evaluation downloads from the Galaxy test process
  (PID 8212). Remote evaluation downloads from a separate process (PID 9638)
  running `galaxy/tools/remote_tool_eval.py`. The materialized HTTP bytes match
  the fixture even though the subsequent command fails. No HTTP GET occurs
  while creating the deferred dataset.
- The remote HTTP job also logs an ignored `Bad file descriptor` exception
  from URL materialization. Its input bytes are complete; the fatal failure is
  the empty output path. Keep that warning as a separate follow-up observation.

The likely code boundary is `remote_tool_eval.py`: it reloads the serialized
Galaxy object-store configuration and constructs `SharedComputeEnvironment`.
That class explicitly assumes shared filesystems. The serialized object-store
configuration still points at Galaxy's storage root, which Pulsar cannot read
in this experiment. Ordinary input path resolution becomes empty; deferred
materialization supplies a valid local input path, but output resolution still
becomes empty. This is a diagnosis from the code and artifacts, not a verified
production fix.

### Recommended first repair

1. Keep the ordinary-input failure as the control regression: remote evaluation
   must work before deferred-input success can be attributed to materialization.
2. Give remote evaluation execution-side dataset paths using the existing
   `JobIO`, `DatasetPath`, and Pulsar path-mapping abstractions. Include input,
   output, extra-files, and metadata paths; avoid resolving tool paths through
   Galaxy's original disk object store on the execution side.
3. Make all eight isolated-storage cases pass with their existing byte and
   placement assertions. The tests deliberately retain their failing assertions
   rather than declaring the broken remote cases successful or expected failures.
4. Then test restricted file sources, user credentials, hashes/transforms, and
   collections. The current evidence supports repairing remote evaluation
   before introducing a second deferred-source staging protocol.

### Reproduction and artifacts

The Galaxy checkout now contains `test/integration/test_pulsar_deferred_external.py`
and the small `deferred_pulsar_service.py` HTTP-service launcher. They reuse the
three baseline cases in `test_pulsar_deferred_data.py` and add one HTTP case per
evaluation strategy. The external experiment skips unless explicitly enabled.

On macOS, with Galaxy's prepared virtualenv:

```sh
source .venv/bin/activate
export GALAXY_TEST_EXTERNAL_PULSAR=1
export GALAXY_PYTHON="$VIRTUAL_ENV/bin/python"
export GALAXY_CONFIG_OVERRIDE_CONDA_AUTO_INIT=false
export GALAXY_CONFIG_ENABLE_BETA_WORKFLOW_MODULES=true
export GALAXY_CONFIG_OVERRIDE_ENABLE_BETA_TOOL_FORMATS=true
export GALAXY_TEST_TOOL_CONF="lib/galaxy/config/sample/tool_conf.xml.sample,test/functional/tools/sample_tool_conf.xml"
python -m pytest test/integration/test_pulsar_deferred_external.py -v --tb=short
```

Local artifacts from the eight-case run:

- Test log: `/private/tmp/deferred_external_matrix.log`.
- HTML report: `/private/tmp/deferred_external_matrix.html`.
- Local-evaluation service, staging, and HTTP evidence:
  `/private/tmp/deferred_pulsar_external_mwt7umah/`.
- Remote-evaluation service and staging:
  `/private/tmp/deferred_pulsar_external_k_gy7f1k/`.
- Sanitized input hashes, command lines, and metadata presence summary:
  `/private/tmp/deferred_pulsar_remote_summary.json`.

The final harness additionally retains `http_evidence.json` when tool execution
fails, so subsequent reproductions do not depend on pytest's captured locals.
Service logs contain transient test job keys and are not included in the branch.

A focused rerun of the final HTTP diagnostic reproduced the same output-path
failure (`1 failed` in 43.49 seconds). Its retained JSON confirms that Galaxy
PID 10858 did not fetch the source: remote evaluator PID 12022 did. Its Pulsar
input again matches the expected bytes. Evidence is in
`/private/tmp/deferred_pulsar_external_faydpbxl/http_evidence.json`; the rerun log
is `/private/tmp/deferred_external_http_diagnostic.log`.

The tests and reproduction report are preserved on the research branch
[`jmchilton/galaxy:deferred-pulsar-matrix-20260926`](https://github.com/jmchilton/galaxy/tree/deferred-pulsar-matrix-20260926).
The baseline above predates the production path fix described below.

## 2026-09-27: runner-resolved paths and output transfer

The branch now exports the runner's resolved compute environment alongside
`job_io.json`. Remote evaluation uses this snapshot for ordinary input paths,
output paths, extra-file paths, metadata-file mappings, and job directories.
Deferred inputs are omitted from the input snapshot so their materialized
execution-side paths continue to be used. Old jobs without the snapshot retain
the shared-environment fallback.

Do not register absent input extra-file directories while taking the snapshot:
Pulsar treats registered paths as files to stage, even for a plain text input.

The original isolated remote-evaluation cases now expose a second boundary:
extended metadata on Pulsar writes directly to Galaxy's serialized object store.
A disk object store on Galaxy is unavailable under the sandbox. Output recovery
for extended remote metadata therefore still needs a separate repair; the
original failing cases remain enabled and their assertions are preserved.

An additional four-case class,
`TestExternalPulsarRemoteEvaluationLocalMetadata`, exercises a configuration
with remote tool evaluation and **Galaxy-side extended metadata** after output
transfer (`remote_metadata: false`). This also required staging the job export
and datatype registry for remote evaluation independently of remote metadata.
The existing local-evaluation cases and shared-storage embedded cases remain.

The HTTP test continues to verify that the remote evaluator fetches the input,
that no GET occurs at deferred dataset creation, that Galaxy does not materialize
the input, and that the recovered output matches the original bytes.

The unit regression checks the environment snapshot across JSON serialization,
including inaccessible Galaxy object-store paths, metadata and extra-file
mappings, absent extra-file directories, and deferred input fallback. Composite
and metadata-dependent tools still need end-to-end coverage; this patch does not
establish general support for reference-data path rewriting or all tool types.

### Next implementation boundary

Define how extended metadata returns output files and discovered datasets when
Pulsar cannot access Galaxy's object store. Preserve the original isolated
remote-metadata cases as the acceptance tests. Avoid interpreting successful
remote downloads alone as successful jobs.

### Verification results

Across the selected final and control runs:

| Configuration                                                   | Result                          |
| --------------------------------------------------------------- | ------------------------------- |
| Embedded Pulsar, local evaluation                               | 3 passed                        |
| Embedded Pulsar, remote evaluation                              | 3 passed                        |
| Isolated Pulsar, local evaluation                               | 4 passed                        |
| Isolated Pulsar, remote evaluation, metadata in Galaxy          | 4 passed                        |
| Isolated Pulsar, remote evaluation, extended metadata in Pulsar | 4 failed at object-store writes |
| Compute environment and JobIO unit regressions                  | 3 passed                        |

The final remote-configuration plus embedded-remote run reports **7 passed** in
176.30 seconds. The original isolated remote-metadata run reports **4 failed**
in 103.89 seconds. All four of those remote outputs independently match the
fixtures; the remaining failure is a denied object-store write. The earlier
control run caught the missing-extra-directory registration regression; its
ordinary embedded case passed in the final rerun after the fix.

HTTP evidence for the passing configuration:
`/private/tmp/deferred_pulsar_external_s9ihz7rr/http_evidence.json` (remote
evaluator PID 37076, Galaxy PID 36340, isolation probe denied).

Final report: `/private/tmp/deferred_path_fix_verified.html`.
Original remote-metadata failure evidence:
`/private/tmp/deferred_pulsar_external_pixucq4o/`.
All Python formatting/lint hooks pass. Service logs and runtime credentials are
retained locally and are not committed.
