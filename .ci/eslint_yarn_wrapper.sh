#!/bin/bash
cd client

echo "Calling yarn..."


# Run vue-tsc with text output
yarn eslint "$@"
EXIT_CODE=$?

echo "Moo cow $EXIT_CODE"

if [ $EXIT_CODE -ne 0 ]; then
    echo "eslint check failed, generating report..."
    # eslint doesn't have JSON format, so capture stderr as text
    yarn eslint --format json "$@" -o ../eslint-report.json || true
fi

exit $EXIT_CODE
