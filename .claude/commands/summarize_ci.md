Analyze CI failures for PR {{arg}} in galaxyproject/galaxy repository.

Steps:
1. **Download artifacts using gh-ci-artifacts**:
   - Run: `npx gh-ci-artifacts {{arg}} --repo galaxyproject/galaxy --output-dir database/pr_reviews`
   - This automatically:
     - Downloads only failed/cancelled runs
     - Converts HTML test reports to JSON
     - Extracts linter outputs from logs
     - Handles expired artifacts gracefully
     - Creates summary.json with all metadata
   - Output will be in `database/pr_reviews/{{arg}}/`
   - Check exit code:
     - 0 = complete success
     - 1 = partial (some artifacts failed)
     - 2 = incomplete (runs still in progress)

2. **Load summary.json**:
   - Read `database/pr_reviews/{{arg}}/summary.json`
   - Contains all workflow runs, artifacts, logs, and download status
   - Check `status` field: "complete", "partial", or "incomplete"
   - If incomplete: Report "Tests still running" and exit
   - If no runs found: Report "No failures - all tests passed!" and exit

3. **Parse test failures**:
   - Check `catalog.json` for detected test types
   - Priority order for test results:
     a. `converted/*.json` - HTML converted to JSON (PREFER THESE)
     b. `raw/*/artifact-*/run_*_tests.json` - JSON reports
   - For pytest-json format:
     ```python
     data = json.load(open(json_file))
     failures = [
         {'test': test['nodeid'], 'duration': test.get('duration', 0), 'log': test.get('call', {}).get('longrepr', ''), 'artifact': artifact_name, 'result': test['outcome']}
         for test in data.get('tests', [])
         if test.get('outcome') in ['failed', 'error']
     ]
     ```
   - Note: pytest outcomes are lowercase ('failed', 'error', 'passed')

4. **Categorize failures** by checking error messages:
   - **Transient**: Look for `TRANSIENT FAILURE [Issue #` in error log/message
   - Extract issue number from pattern
   - **New**: All other failures

5. **Check linter failures**:
   - Look in `linting/<run-id>/<job-name>-<linter>.txt`
   - Extract error counts and key messages
   - Common linters: eslint, prettier, ruff, flake8, isort, black, tsc, mypy

6. Generate markdown summary with:
   - Run IDs and workflow names from summary.json
   - **For test failures:**
     - **Known transient failures** (✅):
       - Test name
       - Workflow name
       - Issue number (with link)
       - Duration
     - **New test failures requiring investigation** (❌):
       - Test name
       - Workflow name
       - Result type (failed vs error)
       - Duration
       - Error preview (first 200 chars)
   - **For linting/build failures:**
     - Job name
     - Linter type (from filename)
     - Error count or preview
   - Total counts (separate test failures from linting/build failures)

7. **Write summary to file** `database/pr_reviews/{{arg}}/summary`:
   - Write the complete markdown summary
   - This file is used by `/summarize_ci_post` to post to PR
   - Format: Same markdown as displayed to user

**Example output:**
```
Analyzing PR #21218...
Running gh-ci-artifacts...
✓ Downloaded 15 artifacts across 3 workflow runs
✓ Converted 8 HTML reports to JSON
✓ Extracted 2 linter outputs from logs

Found 3 failed workflow run(s)

Workflow: Playwright tests (Run 18975780470)
  - 2 artifacts downloaded
  - 1 HTML report converted to JSON

Workflow: Integration (Run 18975780416)
  - 1 artifact downloaded (pytest-json)

Workflow: Linting / client-build (Run 18975780500)
  - No artifacts (extracted logs)

================================================================================
FAILURE SUMMARY
================================================================================

🔧 **Linting/Build failures (1):**
  • client / build-client
    Type: eslint
    Errors: 12
    Example: src/components/Workflow.vue - 'computed' is not defined

✅ **Known transient test failures (2):**
  • lib/galaxy_test/selenium/test_history_sharing.py::test_sharing_private_history
    Workflow: Playwright tests
    Issue: https://github.com/galaxyproject/galaxy/issues/12345
    Duration: 00:01:30
  • test/integration/test_tool_discovery.py::test_tool_discovery_landing
    Workflow: Integration
    Issue: https://github.com/galaxyproject/galaxy/issues/67890
    Duration: 00:00:54

❌ **New test failures requiring investigation (1):**
  • lib/galaxy_test/selenium/test_workflow.py::test_save_workflow
    Workflow: Playwright tests
    Type: failed
    Duration: 00:01:15
    Error: AssertionError: Expected element to be visible

**Total:** 1 linting/build failure, 2 transient tests, 1 new test failure

Summary and artifacts saved to database/pr_reviews/21218/
View artifacts: open database/pr_reviews/21218/index.html
```

8. **Display and save:**
    - Print summary to user
    - Write same content to `database/pr_reviews/{{arg}}/summary`
    - Create/update symlink: `ln -sfn {{arg}} database/pr_reviews/latest`
    - Notify user: "View interactive artifact browser: open database/pr_reviews/{{arg}}/index.html"

Output concise summary showing categorized failures. Transient failures indicate "safe to re-run", new failures indicate "requires investigation".

**Notes:**
- gh-ci-artifacts automatically handles all downloading, conversion, and extraction
- Config in `.gh-ci-artifacts.yaml` specifies:
  - outputDir: database/pr_reviews (so output goes to database/pr_reviews/{{arg}}/)
  - Skip patterns for debug artifacts (too large for analysis)
- All data saved to `database/pr_reviews/{{arg}}/` for use by `/summarize_ci_post`
- Interactive HTML viewer available at `database/pr_reviews/{{arg}}/index.html`
- summary.json contains complete metadata; use it as source of truth
- Prefer `converted/*.json` over raw HTML files - better structured for analysis

**Marking tests as transient failures:**
To mark a test as a known transient failure, manually add the `@transient_failure(issue=N)` decorator:

```python
from galaxy.util.unittest_utils import transient_failure

@transient_failure(issue=12345)  # GitHub issue number tracking this failure
def test_flaky_feature(self):
    # Test that sometimes fails
    ...
```

Once decorated, future failures will be automatically categorized as transient.
