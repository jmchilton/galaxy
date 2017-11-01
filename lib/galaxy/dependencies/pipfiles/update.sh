#!/bin/sh

commit=0

usage() {
cat << EOF
Usage: ${0##*/} [-c]

Use pipenv to regenerate locked and hashed versions of Galaxy dependencies.
Use -c to automatically commit these changes (be sure you have no staged git
changes).

EOF
}

while getopts ":i" opt; do
    case "$opt" in
        h)
            usage
            exit 0
            ;;
        i)
            commit=1
            ;;
        '?')
            usage >&2
            exit 1
            ;;
    esac
done

THIS_DIRECTORY="$(cd "$(dirname "$0")" > /dev/null && pwd)"
cd "$THIS_DIRECTORY"
ENVS="develop
flake8
flake8_imports"

for env in $ENVS
do
        cd "$env"
        pipenv lock
        pipenv lock -r > pinned-hashed-requirements.txt
        # Strip out hashes and trailing whitespace for unhashed version
        # of this requirements file.
        sed 's/--hash[^[:space:]]*//g' pinned-hashed-requirements.txt | sed 's/[[:space:]]*$//' > pinned-requirements.txt
        cd ".."
done

if [ "$commit" -eq "1" ];
then
	git add -u .
	git commit -m "Rev and re-lock Galaxy dependencies."
fi
