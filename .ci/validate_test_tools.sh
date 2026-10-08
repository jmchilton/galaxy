#!/bin/sh

cd "$(dirname "$0")"/.. || exit

xsd_path="lib/galaxy/tool_util/xsd/galaxy.xsd"
# Lint the XSD
xmllint --noout "$xsd_path"

test_tools_path='test/functional/tools'
# test all test tools except upload.xml which uses a non-standard conditional
# (without param) which does not survive xsd validation, and
# parameters/macros.xml which is a macro file, not a tool
set --
for tool_file in "$test_tools_path"/*.xml "$test_tools_path"/parameters/*.xml; do
    case "$tool_file" in
        *_conf.xml | */upload.xml | */parameters/macros.xml) ;;
        *) set -- "$@" "$tool_file" ;;
    esac
done
sh scripts/validate_tools.sh "$@"
