# Linter Wrappers & CI JSON Report Generation

These wrappers and tox environments generate standalone JSON/text reports for linters on failure, enabling automated PR summary analysis without breaking existing text logging workflows.

## Design Pattern

**Python linters (mypy, ruff):** Integrated into tox.ini `-ci` environments
- `tox -e lint-ci` - Runs ruff with JSON retry logic
- `tox -e mypy-ci` - Runs mypy with JSON retry logic

Each `-ci` environment:
1. Runs the linter with normal text output (preserves logs, colored output, etc.)
2. On failure, re-runs with JSON/structured format
3. Saves JSON report to repo root for artifact upload
4. Maintains original exit code so CI still fails appropriately

**JavaScript linters (eslint, vue-tsc):** Shell wrapper scripts
- Smaller ecosystem, so kept as standalone scripts

This approach keeps your current logging intact while generating structured outputs for parsing on failures only.

## Python Linters (tox-based)

### `tox -e lint-ci`
Generates `ruff-report.json` on failure.

**Usage in CI:**
```bash
tox -e lint-ci
```

**What it does:**
- Runs `ruff check .` with default text output
- On failure, re-runs with `--output-format json`, saves to `ruff-report.json`
- Also runs flake8 wrapper as normal

**Configuration in tox.ini:**
```ini
[testenv:lint-ci]
deps = {[testenv:lint]deps}
setenv = {[testenv:lint]setenv}
commands =
    bash -c "ruff check . ; EXIT=$?; if [ $EXIT -ne 0 ]; then ruff check . --output-format json > ruff-report.json; fi; exit $EXIT"
    bash .ci/flake8_wrapper.sh
```

### `tox -e mypy-ci`
Generates `mypy-report.json` on failure.

**Usage in CI:**
```bash
tox -e mypy-ci
```

**What it does:**
- Runs `mypy test lib` with default text output
- On failure, re-runs with `-O json` flag, saves to `mypy-report.json`

**Configuration in tox.ini:**
```ini
[testenv:mypy-ci]
deps = {[testenv:mypy]deps}
setenv = {[testenv:mypy]setenv}
commands =
    bash -c "mypy test lib ; EXIT=$?; if [ $EXIT -ne 0 ]; then mypy test lib -O json > mypy-report.json; fi; exit $EXIT"
```

## JavaScript Linters (Shell wrappers)

### `eslint_wrapper.sh`
Generates `eslint-report.json` on failure.

**Usage in CI:**
```bash
bash .ci/eslint_wrapper.sh
```

**What it does:**
- Runs eslint with default text output
- On failure, re-runs with `--format json`, saves to `eslint-report.json`
- Preserves original eslint search paths and configuration

### `vue_tsc_wrapper.sh`
Generates `tsc-report.txt` on failure.

**Usage in CI:**
```bash
bash .ci/vue_tsc_wrapper.sh
```

**What it does:**
- Runs `yarn type-check` in client/ with default output
- On failure, captures stderr to `tsc-report.txt` (vue-tsc has no JSON format)

## Jest (Direct command)

Jest doesn't need a wrapper - it supports both output modes in one run.

**Usage in CI:**
```bash
yarn jest --json --outputFile ../jest-report.json
```

**What it does:**
- Generates `jest-report.json` while maintaining normal stdout output
- Jest supports both modes simultaneously, no re-run needed

## Artifact Upload

All workflows upload reports on failure:

```yaml
- uses: actions/upload-artifact@v5
  if: failure()
  with:
    name: <Report name>
    path: |
      <report1>.json
      <report2>.json
```

These artifacts are automatically discovered by `gh-ci-artifacts` and parsed into structured format for PR summaries.

## Output Files

All files are generated at repo root:
- `mypy-report.json` - mypy type checking results
- `ruff-report.json` - ruff linting results
- `eslint-report.json` - eslint linting results
- `tsc-report.txt` - TypeScript type checking (text format)
- `jest-report.json` - Jest test results

## Integration with gh-ci-artifacts

All generated reports are automatically discovered and parsed by `gh-ci-artifacts` based on filename patterns:
- `mypy-report.json` - mypy type checking results
- `ruff-report.json` - ruff linting results
- `eslint-report.json` - eslint linting results
- `tsc-report.txt` - TypeScript type checking (text format)
- `jest-report.json` - Jest test results

These are converted to structured JSON in `database/pr_reviews/*/` for automated PR summary generation.

## GitHub Workflows

Workflows call the tox `-ci` environments to get both text logs and JSON reports:

```yaml
# lint.yaml
- name: Run linting
  run: tox -e lint-ci

- name: Run mypy checks
  run: tox -e mypy-ci

# jest.yaml
- name: Run Unit Tests
  run: yarn jest --json --outputFile ../jest-report.json

# js_lint.yaml
- name: Run ESLint
  run: bash .ci/eslint_wrapper.sh

- name: Run vue-tsc
  run: bash .ci/vue_tsc_wrapper.sh

# Upload reports only on failure
- uses: actions/upload-artifact@v5
  if: failure()
  with:
    name: Linter reports
    path: |
      mypy-report.json
      ruff-report.json
      eslint-report.json
      jest-report.json
      tsc-report.txt
```
