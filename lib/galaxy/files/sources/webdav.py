from webdavfs.webdavfs import WebDAVFS

from ._pyfilesystem2 import PyFilesystem2FilesSource


class WebDavFilesSource(PyFilesystem2FilesSource):
    plugin_type = 'webdav'

    def _open_fs(self, user_context):
        props = self._serialization_props(user_context)
        handle = WebDAVFS(**props)
        return handle


__all__ = ('WebDavFilesSource',)
