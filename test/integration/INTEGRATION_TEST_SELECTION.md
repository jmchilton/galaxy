# Selecting expensive integration suites in CI

For pull requests and pushes, `scripts/select_integration_tests.py` compares
changed paths and exports `GALAXY_TEST_CI_SELECTION` plus diagnostic flags
`GALAXY_TEST_CI_UTILS_CHANGED`, `GALAXY_TEST_CI_JOBS_PLUMBING_CHANGED`, and
`GALAXY_TEST_CI_OBJECTSTORE_PLUMBING_CHANGED`. Pull requests compare the merge
base of the base/head commits to the head; pushes compare before/after commits.
Renames include both old and new paths. Missing history, invalid comparison
commits, scheduled runs, and manual runs select every family.

The path policy in `test/integration/integration_selection.py` selects individual
runner/objectstore plugins for direct plugin edits. Shared utilities, job and
objectstore plumbing select all expensive families. Shared test infrastructure,
dependencies, model/config/tool/datatype/metadata code and CI changes also select
all families. Dataset upload/download APIs, services and managers, file-source
plumbing and tool execution paths also select all families. S3 XML configuration
and multipart helpers select both S3 and Cloud because Cloud shares the S3 parser.
General integration tests always run.

Only tests marked `@pytest.mark.ci_integration_family("family")` may be
deselected. A pure plugin module can set `pytestmark` to this marker so its
generated `test_tools` tests are covered too. Mixed modules mark individual
classes/functions: fake HTCondor tests and disk upload tests remain unconditional;
cloud subclasses add their own marker to their inherited S3 dependency. When
several markers apply, any selected family retains the test. The
historically named Swift suites currently use boto3 against SeaweedFS and belong
to the `s3` family. Add new families to the central path policy before marking
their tests; unmarked tests and unknown families keep running.

Selection happens during collection, before fixtures/class startup and before
cost-based sharding. Local runs without the selection environment variable run
everything, as do malformed/incompatible selection values. To request a full
local run after experimenting with selection, unset `GALAXY_TEST_CI_SELECTION`.

Minikube, PostgreSQL, RabbitMQ, Apptainer and mulled-cache preparation remain in
the workflow. Some unconditional suites still use containers; this selection
limits expensive plugin suites without changing those shared services.
