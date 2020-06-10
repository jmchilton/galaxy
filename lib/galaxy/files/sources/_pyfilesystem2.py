import abc
import functools
import logging
import os

from ..sources import BaseFilesSource

log = logging.getLogger(__name__)


class PyFilesystem2FilesSource(BaseFilesSource):

    def __init__(self, **kwd):
        props = self._parse_common_config_opts(kwd)
        self._props = props

    @abc.abstractmethod
    def _open_fs(self, user_context=None):
        """Subclasses must instantiate a PyFilesystem2 handle for this file system."""

    def list(self, path="/", recursive=False, user_context=None):
        """Return dictionary of 'Directory's and 'File's."""

        with self._open_fs(user_context=user_context) as h:
            if recursive:
                res = []
                for p, dirs, files in h.walk(path):
                    to_dict = functools.partial(self._resource_info_to_dict, p)
                    res.extend(map(to_dict, dirs))
                    res.extend(map(to_dict, files))
                return res
            else:
                res = h.scandir(path)
                to_dict = functools.partial(self._resource_info_to_dict, path)
                return list(map(to_dict, res))

    def realize_to(self, source_path, native_path, user_context=None):
        with open(native_path, 'wb') as write_file:
            self._open_fs(user_context=user_context).download(source_path, write_file)

    def _resource_info_to_dict(self, dir_path, resource_info):
        name = resource_info.name
        path = os.path.join(dir_path, name)
        uri = self.uri_from_path(path)
        if resource_info.is_dir:
            return {"class": "Directory", "name": name, "uri": uri}
        else:
            created = resource_info.created
            return {
                "class": "File",
                "name": name,
                "size": resource_info.size,
                "ctime": self.to_dict_time(resource_info.created),
                "uri": uri,
            }

    def _serialization_props(self, user_context=None):
        effective_props = {}
        for key, val in self._props.items():
            effective_props[key] = self._evaluate_prop(val, user_context=user_context)
        return effective_props
