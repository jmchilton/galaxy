#!/bin/sh

setup_python() {
    # If there is a .venv/ directory, assume it contains a virtualenv that we
    # should run this instance in.
    GALAXY_VIRTUAL_ENV="${GALAXY_VIRTUAL_ENV:-.venv}"
    if [ -d "$GALAXY_VIRTUAL_ENV" -a -z "$skip_venv" ];
    then
        [ -n "$PYTHONPATH" ] && { echo 'Unsetting $PYTHONPATH'; unset PYTHONPATH; }
        echo "Activating virtualenv at $GALAXY_VIRTUAL_ENV"
        . "$GALAXY_VIRTUAL_ENV/bin/activate"
    fi

    # If you are using --skip-venv we assume you know what you are doing but warn
    # in case you don't.
    [ -n "$PYTHONPATH" ] && echo 'WARNING: $PYTHONPATH is set, this can cause problems importing Galaxy dependencies'

    python ./scripts/check_python.py || exit 1
}
