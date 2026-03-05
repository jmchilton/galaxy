import functools
import json
import logging
import os
import urllib.parse

from cwl_utils.pack import pack
from cwltool.utils import visit_field

log = logging.getLogger(__name__)


def get_cwl_test_url(cwl_version):
    branch = "main"
    if cwl_version == "1.0":
        repo_name = "common-workflow-language"
        tests_dir = "v1.0/v1.0"
    else:
        repo_name = f"cwl-v{cwl_version}"
        tests_dir = "tests"
    if cwl_version == "1.2.1":
        branch = "1.2.1_proposed"
    return f"https://raw.githubusercontent.com/common-workflow-language/{repo_name}/{branch}/{tests_dir}"


def get_url(item, cwl_version, base_dir):
    # quick hack, to make it more useful upload files/directories/paths to Galaxy instance ?
    if isinstance(item, dict) and item.get("class") == "File":
        location = item.pop("path", None)
        if not location:
            parse_result = urllib.parse.urlparse(item["location"])
            if parse_result.scheme == "file":
                location = urllib.parse.unquote(parse_result.path)
            if base_dir not in location:
                return item
            location = os.path.relpath(location, base_dir)
        url = f"{get_cwl_test_url(cwl_version)}/{location}"
        log.debug("Rewrote location from '%s' to '%s'", location, url)
        item["location"] = url
    return item


def rewrite_locations(workflow_path: str, output_path: str):
    workflow_obj = pack(workflow_path)
    cwl_version = workflow_path.split("test/functional/tools/cwl_tools/v")[1].split("/")[0]
    cwl_tools_root = (
        workflow_path.split("test/functional/tools/cwl_tools/v")[0] + f"test/functional/tools/cwl_tools/v{cwl_version}/"
    )
    if cwl_version == "1.0":
        tests_root = os.path.normpath(os.path.join(cwl_tools_root, "v1.0"))
    else:
        tests_root = os.path.normpath(os.path.join(cwl_tools_root, "tests"))
    visit_field(
        workflow_obj,
        ("default"),
        functools.partial(get_url, cwl_version=cwl_version, base_dir=tests_root),
    )
    with open(output_path, "w") as output:
        json.dump(workflow_obj, output)
