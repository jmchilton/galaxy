#!/bin/bash
cd client

# Run prettier --check with text output
yarn format-check "$@"
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "prettier format check failed, generating report..."
    # prettier doesn't have JSON format, so capture stderr as structured text
    yarn format-check "$@" 2> ../prettier-report.txt || true
fi

exit $EXIT_CODE
