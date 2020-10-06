import json
import logging
from pkg_resources import resource_string

log = logging.getLogger(__name__)

SPDX_LICENSES_STRING = resource_string(__name__, 'licenses.json').decode("UTF-8")
SPDX_LICENSES = json.loads(SPDX_LICENSES_STRING)
for license in SPDX_LICENSES["licenses"]:
    license["spdxUrl"] = "https://spdx.org/licenses/%s" % license["reference"][len("./"):]
    seeAlso = license.get("seeAlso", [])
    if len(seeAlso) > 0:
        url = seeAlso[0]
    else:
        url = license["spdxUrl"]
    license["url"] = url


class LicensesManager:

    def __init__(self):
        by_index = {}
        for spdx_license in self.index():

            by_index[spdx_license["licenseId"]] = spdx_license
            by_index[spdx_license["detailsUrl"]] = spdx_license
            for seeAlso in spdx_license.get("seeAlso", []):
                by_index[seeAlso] = spdx_license
        self._by_index = by_index

    def index(self):
        return SPDX_LICENSES["licenses"]

    def get(self, uri):
        if uri in self._by_index:
            return self._by_index[uri]
        else:
            log.warn("Unknown license URI encountered [%s]" % uri)
        return {
            "url": uri
        }
