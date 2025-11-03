#!/bin/bash
set -e

# Setting NODE_PATH and config appropriately, using dependencies from
# client/node_modules, run eslint against args passed to this script.
NODE_PATH=src/ node client/node_modules/eslint/bin/eslint.js -c client/.eslintrc.js "$@"
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "eslint check failed, generating JSON report..."
    NODE_PATH=src/ node client/node_modules/eslint/bin/eslint.js -c client/.eslintrc.js --format json "$@" > eslint-report.json 2>/dev/null || true
fi

exit $EXIT_CODE
