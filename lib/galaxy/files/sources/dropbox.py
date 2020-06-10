from dropboxfs.dropboxfs import DropboxFS

from ._pyfilesystem2 import PyFilesystem2FilesSource


class DropboxFilesSource(PyFilesystem2FilesSource):
    plugin_type = 'dropbox'

    def _open_fs(self, user_context):
        props = self._serialization_props(user_context)
        handle = DropboxFS(**props)
        return handle


__all__ = ('DropboxFilesSource',)
