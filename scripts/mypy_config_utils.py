import argparse
import configparser
import os
import re
from dataclasses import dataclass
from typing import (
    Optional,
    List,
    Set,
)

OUTPUT_ERROR_LINE_PATTERN = re.compile("(.*):\\d+: error:.*")


@dataclass
class MyPyEntry:
    section_name: str
    package_name: str
    target: str


@dataclass
class MyPyError:
    target: str


def read_log_for_errored_files(mypy_output_log) -> List[MyPyError]:
    errors = []
    with open(mypy_output_log, "r") as f:
        for line in f.readlines():
            match = OUTPUT_ERROR_LINE_PATTERN.match(line)
            if match:
                errors.append(MyPyError(match.group(1)))
    return errors


def target_files(errors: List[MyPyError]) -> Set[str]:
    target_files = set()
    for error in errors:
        target_files.add(error.target)
    return target_files


def main():
    config = configparser.ConfigParser()
    config.read("./mypy.ini")
    entries: List[MyPyEntry] = []
    for section in config.sections():
        if not section.startswith("mypy-"):
            continue
        section_name = section
        package_name = section[len("mypy-") :]
        if not (package_name.startswith("galaxy.") or package_name.startswith("tool_shed")):
            continue
        if "*" in package_name:
            # Do not handle wild cards yet.
            continue
        entry = MyPyEntry(section_name, package_name, to_python_path(package_name))
        if entry.target is None:
            print(f"Warning section {entry.section_name} does not refer to existant files")
        entries.append(entry)

    parser = argparse.ArgumentParser(description="utility script for managing Galaxy's mypy.ini file.")
    parser.add_argument("--compare-log", dest="compare_log")
    args = parser.parse_args()
    if args.compare_log:
        errors = read_log_for_errored_files(args.compare_log)
        files_with_errors = target_files(errors)
        for entry in entries:
            if entry.target not in files_with_errors:
                print(f"No errors detected for {entry.target} referenced in section {entry.section_name}")


def to_python_path(package_name: str) -> Optional[str]:
    path = os.path.join("lib", package_name.replace(".", "/"))
    if os.path.exists(path + ".py"):
        path = f"{path}.py"
    else:
        index_path = os.path.join(path, "__init__.py")
        if os.path.exists(index_path):
            path = index_path
        else:
            path = None
    return path


if __name__ == "__main__":
    main()
