#!/bin/bash

set -ex

PACKAGE_LIST_FILE=packages_by_dep_dag.txt
FOR_PULSAR=0
SKIP_PACKAGES=(
    web_client
    meta
)

should_skip_package() {
    local pkg
    for pkg in "${SKIP_PACKAGES[@]}"; do
        [ "$1" = "$pkg" ] && return 0
    done
    return 1
}

wheel_contents() {
    python -c 'import sys, zipfile; print("\n".join(sorted(n for n in zipfile.ZipFile(sys.argv[1]).namelist() if ".dist-info/" not in n)))' "$1"
}

# Downstream packagers rebuild the wheel from the sdist without git or the
# sdist's egg-info, so only MANIFEST.in decides which non-Python files ship.
check_wheel_from_bare_sdist() {
    local work_dir
    work_dir=$(mktemp -d -t gxpkgsdistXXXXXX)
    tar -xzf dist/*.tar.gz -C "$work_dir"
    rm -rf "$work_dir"/*/*.egg-info "$work_dir"/*/src/*.egg-info
    (cd "$work_dir"/*/ && ${BUILD_WHEEL_CMD} --wheel -o "${work_dir}/dist")
    if ! diff <(wheel_contents dist/*.whl) <(wheel_contents "$work_dir"/dist/*.whl); then
        echo "Wheel rebuilt from sdist without egg-info differs from dist wheel (< only in dist wheel), update MANIFEST.in" >&2
        return 1
    fi
    rm -rf "$work_dir"
}

for arg in "$@"; do
    if [ "$arg" = "--for-pulsar" ]; then
        PACKAGE_LIST_FILE=packages_for_pulsar_by_dep_dag.txt
        FOR_PULSAR=1
    fi
done

# Don't display the pip progress bar when running under CI
if [ "$CI" = 'true' ]; then
    export PIP_PROGRESS_BAR=off
fi

# Change to packages directory.
cd "$(dirname "$0")"

TEST_PYTHON=${TEST_PYTHON:-"python3"}

if command -v uv >/dev/null; then
    VENV_CMD="uv venv --python $TEST_PYTHON"
    PIP_CMD="$(command -v uv) pip"
    BUILD_WHEEL_CMD="$(command -v uv) build"
    TWINE_CMD="$(command -v uvx) twine"
    export UV_EXTRA_INDEX_URL=https://wheels.galaxyproject.org/simple
    export UV_INDEX_STRATEGY=unsafe-best-match
else
    VENV_CMD="$TEST_PYTHON -m venv"
    PIP_CMD='python -m pip'
    BUILD_WHEEL_CMD='python -m build'
    TWINE_CMD=twine
    export PIP_EXTRA_INDEX_URL=https://wheels.galaxyproject.org/simple
fi

# Ensure ordered by dependency DAG
while read -r package_dir || [ -n "$package_dir" ]; do  # https://stackoverflow.com/questions/12916352/shell-script-read-missing-last-line
    # Ignore empty lines
    if [ -z "$package_dir" ]; then
        continue
    fi
    # Ignore lines beginning with `#`
    if  [[ $package_dir =~ ^#.* ]]; then
        continue
    fi
    if should_skip_package "$package_dir"; then
        printf "\nSkipping package %s\n\n" "$package_dir"
        continue
    fi

    printf "\n========= TESTING PACKAGE %s =========\n\n" "$package_dir"

    cd "$package_dir"

    # Use a throw-away virtualenv
    TEST_ENV_DIR=$(mktemp -d -t gxpkgtestenvXXXXXX)
    ${VENV_CMD} "${TEST_ENV_DIR}"
    # shellcheck disable=SC1091
    . "${TEST_ENV_DIR}/bin/activate"
    if [ "${PIP_CMD}" = 'python -m pip' ]; then
        ${PIP_CMD} install --upgrade build pip setuptools twine wheel
    fi

    # Install extras (if needed)
    if [ "$package_dir" = "util" ]; then
        ${PIP_CMD} install '.[image-util,template,jstree,config-template,test]'
    elif [ "$package_dir" = "tool_util" ]; then
        ${PIP_CMD} install '.[cwl,mulled,edam,extended-assertions,test]'
    elif grep -q '^test = \[' pyproject.toml 2>/dev/null; then
        ${PIP_CMD} install '.[test]'
    else
        ${PIP_CMD} install .
    fi

    if [ $FOR_PULSAR -eq 0 ]; then
        marker_args=(-m 'not external_dependency_management')
    else
        marker_args=()
    fi
    # Ignore exit code 5 (no tests ran)
    pytest "${marker_args[@]}" . || test $? -eq 5
    if [ $FOR_PULSAR -eq 0 ]; then
        ${PIP_CMD} install -r ../../lib/galaxy/dependencies/pinned-typecheck-requirements.txt
        # make mypy uses uv now and so this legacy code should just run mypy
        # directly to use the venv we have already activated
        cd src
        mypy .
        cd ..
        if [ -d tests ]; then
            mypy tests
        fi

        ${BUILD_WHEEL_CMD} -o dist
        ${TWINE_CMD} check dist/*
        check_wheel_from_bare_sdist
    fi
    cd ..
    deactivate
    rm -rf "${TEST_ENV_DIR}"
done < $PACKAGE_LIST_FILE
