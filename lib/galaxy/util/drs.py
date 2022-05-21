from os import PathLike
from typing import Union

import requests

from galaxy.util import (
    CHUNK_SIZE,
    DEFAULT_SOCKET_TIMEOUT,
)

TargetPathT = Union[str, PathLike]


def _not_implemented(drs_uri: str, desc: str) -> NotImplementedError:
    missing_client_func = f"Galaxy client cannot currently fetch URIs {desc}."
    header = f"Missing client functionaltiy required to fetch DRS URI {drs_uri}."
    rest_of_message = """Currently Galaxy client only works with HTTP/HTTPS targets but extensions for
    other types would be gladly welcomed by the Galaxy team. Please
    report use cases not covered by this function to our issue tracker
    at https://github.com/galaxyproject/galaxy/issues/new.
    """
    return NotImplementedError(f"{header} {missing_client_func} {rest_of_message}")


def fetch_drs_to_file(drs_uri: str, target_path: TargetPathT, force_http=False):
    """Fetch contents of drs:// URI to a target path."""
    if not drs_uri.startswith("drs://"):
        raise ValueError(f"Unknown scheme for drs_uri {drs_uri}")
    rest_of_drs_uri = drs_uri[len("drs://") :]
    if "/" not in rest_of_drs_uri:
        # DRS URI uses compact identifiers, not yet implemented.
        # https://ga4gh.github.io/data-repository-service-schemas/preview/release/drs-1.2.0/docs/more-background-on-compact-identifiers.html
        raise _not_implemented(drs_uri, "that use compact identifiers")
    netspec, object_id = rest_of_drs_uri.split("/", 1)
    scheme = "https"
    if force_http:
        scheme = "http"
    get_url = f"{scheme}://{netspec}/ga4gh/drs/v1/objects/{object_id}"
    response = requests.get(get_url, timeout=DEFAULT_SOCKET_TIMEOUT)
    response.raise_for_status()
    response_object = response.json()
    if "access_methods" not in response_object:
        raise ValueError(f"No access methods found in DRS response for {drs_uri}")
    access_methods = response_object["access_methods"]
    if len(access_methods) == 0:
        raise ValueError(f"No access methods found in DRS response for {drs_uri}")

    filtered_access_methods = [m for m in access_methods if m["type"].startswith("http")]
    if len(filtered_access_methods) == 0:
        unimplemented_access_types = [m["type"] for m in access_methods]
        raise _not_implemented(drs_uri, f"that is fetched via unimplemented types ({unimplemented_access_types})")

    access_method = filtered_access_methods[0]
    access_url = access_method["access_url"]
    url = access_url["url"]
    headers_list = access_url.get("headers") or []
    headers_as_dict = {}
    for header_str in headers_list:
        key, value = header_str.split(": ", 1)
        headers_as_dict[key] = value

    download_response = requests.get(url, headers=headers_as_dict, stream=True, timeout=DEFAULT_SOCKET_TIMEOUT)
    download_response.raise_for_status()
    with open(target_path, "wb") as f:
        for chunk in download_response.iter_content(chunk_size=CHUNK_SIZE):
            # If you have chunk encoded response uncomment if
            # and set chunk_size parameter to None.
            # if chunk:
            f.write(chunk)
