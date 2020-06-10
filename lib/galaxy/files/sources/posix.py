import functools
import os
import shutil

from galaxy.util.path import safe_contains

from ..sources import BaseFilesSource

DEFAULT_ENFORCE_SYMLINK_SECURITY = True

class PosixFilesSource(BaseFilesSource):
    plugin_type = 'posix'

    # If this were a PyFilesystem2FilesSource all that would be needed would be,
    # but we couldn't enforce security our way I suspect.
    # def _open_fs(self):
    #    from fs.osfs import OSFS
    #    handle = OSFS(**self._props)
    #    return handle

    def __init__(self, **kwd):
        props = self._parse_common_config_opts(kwd)
        self.root = kwd["root"]
        self.enforce_symlink_security = kwd.get("enforce_symlink_security", DEFAULT_ENFORCE_SYMLINK_SECURITY)

    def list(self, path="/", recursive=True, user_context=None):
        if recursive:
            res = []
            # TODO: safe walk...
            for p, dirs, files in h.walk(path):
                to_dict = functools.partial(self._resource_info_to_dict, p)
                res.extend(map(to_dict, dirs))
                res.extend(map(to_dict, files))
            return res
        else:
            dir_path = self._to_native_path(path, user_context=user_context)
            res = os.listdir(dir_path)
            to_dict = functools.partial(self._resource_info_to_dict, path, user_context=user_context)
            return list(map(to_dict, res))

    def realize_to(self, source_path, native_path, user_context=None):
        effective_root = self._effective_root(user_context)
        source_native_path = self._to_native_path(source_path, user_context=user_context)
        if self.enforce_symlink_security:
            if not safe_contains(effective_root, source_native_path, allowlist=self._file_sources_config.symlink_allowlist):
                raise Exception("Operation not allowed.")
        else:
            source_native_path = os.path.normpath(source_native_path)
            assert source_native_path.startswith(os.path.normpath(effective_root))

        shutil.copyfile(source_native_path, native_path)

    def _to_native_path(self, source_path, user_context=None):
        source_path = os.path.normpath(source_path)
        if source_path.startswith("/"):
            source_path = source_path[1:]
        return os.path.join(self._effective_root(user_context), source_path)

    def _effective_root(self, user_context=None):
        return self._evaluate_prop(self.root, user_context=user_context)

    def _resource_info_to_dict(self, dir, name, user_context=None):
        rel_path = os.path.join(dir, name)
        full_path = self._to_native_path(rel_path, user_context=user_context)
        uri = self.uri_from_path(rel_path)
        if os.path.isdir(full_path):
            return {"class": "Directory", "name": name, "uri": uri}
        else:
            statinfo = os.lstat(full_path)
            return {
                "class": "File",
                "name": name,
                "size": statinfo.st_size,
                "ctime": self.to_dict_time(statinfo.st_ctime),
                "uri": uri,
            }

    def _serialization_props(self, user_context=None):
        return {
            "root": self._effective_root(user_context),
        }


__all__ = ('PosixFilesSource',)
