try:
    from fs.onedrivefs import OneDriveFS
    from google.oauth2.credentials import Credentials
except ImportError:
    OneDriveFS = None

from typing import Optional

from . import FilesSourceOptions
from ._pyfilesystem2 import PyFilesystem2FilesSource


class OneDriveFilesSource(PyFilesystem2FilesSource):
    plugin_type = "onedrive"
    required_module = OneDriveFS
    required_package = "fs.onedrivefs"

    def _open_fs(self, user_context=None, opts: Optional[FilesSourceOptions] = None):
        props = self._serialization_props(user_context)
        access_token = props.pop("oauth2_access_token")
        if access_token:
            props["token"] = access_token
        handle = OneDriveFS(**props)
        return handle


__all__ = ("OneDriveFilesSource",)
