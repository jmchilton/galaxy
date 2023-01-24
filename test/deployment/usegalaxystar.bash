#!/bin/bash

# Once-a-release deployment tests for usegalaxy*
set -e
PROJECT_ROOT=../..
cd "$PROJECT_ROOT"
. ./scripts/common_startup_functions.sh
echo "$GALAXY_TEST_DEPLOYMENT_TARGET"
. .venv/bin/activate
if [ "$GALAXY_TEST_DEPLOYMENT_TARGET" -eq "usegalaxymain" ];
then
    GALAXY_TEST_EXTERNAL="https://usegalaxy.org"
    GALAXY_TEST_USER_API_KEY="$GALAXY_TEST_USEGALAXYMAIN_USER_KEY"
fi
export GALAXY_TEST_EXTERNAL
export GALAXY_TEST_USER_API_KEY
pytest -m "not requires_admin" -m "not requires_new_library" lib/galaxy_test/api/test_datatypes.py
