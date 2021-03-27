#!/bin/bash

set -e

# Don't display the pip progress bar when running under CI
[ "$CI" = 'true' ] && export PIP_PROGRESS_BAR=off

# Change to packages directory.
cd "$(dirname "$0")"

# Use a throw-away virtualenv
TEST_PYTHON=${TEST_PYTHON:-"python"}
TEST_ENV_DIR=${TEST_ENV_DIR:-$(mktemp -d -t gxpkgtestenvXXXXXX)}

virtualenv -p "$TEST_PYTHON" "$TEST_ENV_DIR"
. "${TEST_ENV_DIR}/bin/activate"
pip install --upgrade pip setuptools wheel
pip install -r../lib/galaxy/dependencies/pinned-lint-requirements.txt

# ensure ordered by dependency dag
PACKAGE_DIRS=(
    util
    objectstore
    job_metrics
    containers
    tool_util
    data
    job_execution
    auth
    web_stack
    web_framework
    app
    webapps
)
# tool_util not yet working 100%,
# data has many problems quota, tool shed install database, etc..
RUN_TESTS=(1 1 1 1 1 1 1 1 1 1 1 0)
RUN_MYPY=(1 1 1 1 1 1 1 1 1 1 1 1)
for ((i=0; i<${#PACKAGE_DIRS[@]}; i++)); do
    package_dir=${PACKAGE_DIRS[$i]}
    run_tests=${RUN_TESTS[$i]}
    run_mypy=${RUN_MYPY[$i]}

    cd "$package_dir"
    pip install -e '.'
    pip install -r test-requirements.txt

    # Install extras (if needed)
    if [ "$package_dir" = "util" ]; then
        pip install -e '.[template,jstree]'
    fi
    if [ "$package_dir" = "tool_util" ]; then
        pip install -e '.[mulled]'
    fi

    if [[ "$run_tests" == "1" ]]; then
        pytest --doctest-modules galaxy tests
    fi
    if [[ "$run_mypy" == "1" ]]; then
        make mypy
    fi
    cd ..
done
