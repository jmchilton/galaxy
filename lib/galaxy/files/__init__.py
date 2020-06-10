from collections import namedtuple

from galaxy.util import (
    plugin_config
)

FileSourcePath = namedtuple('FileSourcePath', ['file_source', 'path'])


class ConfiguredFileSources(object):
    """Load plugins and resolve Galaxy URIs to FileSource objects."""

    def __init__(self, file_sources_config, conf_file=None, conf_dict=None, load_stock_plugins=False):
        self._file_sources_config = file_sources_config
        self._plugin_classes = self._file_source_plugins_dict()
        file_sources = []
        if conf_file is not None:
            file_sources = self._load_plugins_from_file(conf_file)
        elif conf_dict is not None:
            plugin_source = plugin_config.plugin_source_from_dict(conf_dict)
            file_sources = self._parse_plugin_source(plugin_source)

        if load_stock_plugins:
            stock_file_source_conf_dict = []
            if file_sources_config.library_import_dir is not None:
                stock_file_source_conf_dict.append({'type': 'gximport'})
            if file_sources_config.user_library_import_dir is not None:
                stock_file_source_conf_dict.append({'type': 'gxuserimport'})
            if file_sources_config.ftp_upload_dir is not None:
                stock_file_source_conf_dict.append({'type': 'gxftp'})
            if stock_file_source_conf_dict:
                stock_plugin_source = plugin_config.plugin_source_from_dict(stock_file_source_conf_dict)
                file_sources.extend(self._parse_plugin_source(stock_plugin_source))

        self._file_sources = file_sources

    def _load_plugins_from_file(self, conf_file):
        plugin_source = plugin_config.plugin_source_from_path(conf_file)
        return self._parse_plugin_source(plugin_source)

    def _file_source_plugins_dict(self):
        import galaxy.files.sources
        return plugin_config.plugins_dict(galaxy.files.sources, 'plugin_type')

    def _parse_plugin_source(self, plugin_source):
        extra_kwds = {
            'file_sources_config': self._file_sources_config,
        }
        return plugin_config.load_plugins(self._plugin_classes, plugin_source, extra_kwds)

    def get_file_source_path(self, uri):
        """Parse uri into a FileSource object and a path relative to its base."""
        assert "://" in uri
        schema, rest = uri.split("://", 1)
        assert schema in self.get_schemas()
        if schema != "gxfiles":
            # prefix unused
            id_prefix = None
            path = rest
        else:
            if "/" in rest:
                id_prefix, path = rest.split("/", 1)
            else:
                id_prefix, path = rest, "/"
        file_source = self.get_file_source(id_prefix, schema)
        return FileSourcePath(file_source, path)

    def get_file_source(self, id_prefix, schema):
        for file_source in self._file_sources:
            # gxfiles uses prefix to find plugin, other schema are assumed to have
            # at most one file_source.
            if schema != file_source.get_schema():
                continue
            prefix_match = schema != "gxfiles" or file_source.get_prefix() == id_prefix
            if prefix_match:
                return file_source

    def get_schemas(self):
        schemas = set()
        for file_source in self._file_sources:
            schemas.add(file_source.get_schema())
        return schemas

    def plugins_to_dict(self, for_serialization=False, user_context=None):
        rval = []
        for file_source in self._file_sources:
            el = file_source.to_dict(for_serialization=for_serialization, user_context=user_context)
            rval.append(el)
        return rval

    def to_dict(self, for_serialization=False, user_context=None):
        return {
            'file_sources': self.plugins_to_dict(for_serialization=for_serialization, user_context=user_context),
            'config': self._file_sources_config.to_dict()
        }

    @staticmethod
    def from_app_config(config):
        config_file = config.file_sources_config_file
        file_sources_config = ConfiguredFileSourcesConfig.from_app_config(config)
        return ConfiguredFileSources(file_sources_config, config_file, load_stock_plugins=True)

    @staticmethod
    def from_dict(as_dict):
        sources_as_dict = as_dict["file_sources"]
        config_as_dict = as_dict["config"]
        file_sources_config = ConfiguredFileSourcesConfig.from_dict(config_as_dict)
        return ConfiguredFileSources(file_sources_config, conf_dict=sources_as_dict)


class ConfiguredFileSourcesConfig(object):

    def __init__(self, symlink_allowlist=[], library_import_dir=None, user_library_import_dir=None, ftp_upload_dir=None):
        self.symlink_allowlist = symlink_allowlist
        self.library_import_dir = library_import_dir
        self.user_library_import_dir = user_library_import_dir
        self.ftp_upload_dir = ftp_upload_dir

    @staticmethod
    def from_app_config(config):
        # Formalize what we read in from config to create a more clear interface
        # for this component.
        kwds = {}
        kwds["symlink_allowlist"] = getattr(config, "user_library_import_symlink_allowlist", [])
        kwds["library_import_dir"] = getattr(config, "library_import_dir", None)
        kwds["user_library_import_dir"] = getattr(config, "user_library_import_dir", None)
        kwds["ftp_upload_dir"] = getattr(config, "ftp_upload_dir", None)
        return ConfiguredFileSourcesConfig(**kwds)

    def to_dict(self):
        return {
            'symlink_allowlist': self.symlink_allowlist,
            'library_import_dir': self.library_import_dir,
            'user_library_import_dir': self.user_library_import_dir,
            'ftp_upload_dir': self.ftp_upload_dir,
        }

    @staticmethod
    def from_dict(as_dict):
        return ConfiguredFileSourcesConfig(
            symlink_allowlist=as_dict['symlink_allowlist'],
            library_import_dir=as_dict['library_import_dir'],
            user_library_import_dir=as_dict['user_library_import_dir'],
            ftp_upload_dir=as_dict['ftp_upload_dir'],
        )


class ProvidesUserFileSourcesUserContext(object):
    """Implement a FileSourcesUserContext from a Galaxy ProvidesUserContext (e.g. trans)."""

    def __init__(self, trans):
        self.trans = trans

    @property
    def email(self):
        return self.trans.user.email

    @property
    def username(self):
        return self.trans.user.username

    @property
    def ftp_dir(self):
        return self.trans.user_ftp_dir

    @property
    def preferences(self):
        return self.trans.user.extra_preferences


class DictFileSourcesUserContext(object):

    def __init__(self, **kwd):
        self._kwd = kwd

    @property
    def email(self):
        return self._kwd.get("email")

    @property
    def username(self):
        return self._kwd.get("username")

    @property
    def ftp_dir(self):
        return self._kwd.get("user_ftp_dir")

    @property
    def preferences(self):
        return self._kwd.get("preferences")
