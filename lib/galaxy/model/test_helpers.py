from tempfile import mkdtemp

from galaxy import model, objectstore
from galaxy.datatypes import registry
from galaxy.model import mapping
from galaxy.security import idencoding


class DataApp(object):
    """Minimal Galaxy-app-like object for galaxy-data package.

    Sets up datatypes and models.
    """

    def __init__(self):
        self.config = DataConfig()
        self.object_store = objectstore.build_object_store_from_config(self.config, config_dict={
            "type": "disk",
        })
        self.model = mapping.init("/tmp", self.config.database_connection, create_tables=True, object_store=self.object_store)
        self.security = idencoding.IdEncodingHelper(id_secret='6e46ed6483a833c100e68cc3f1d0dd76')
        self.model.Dataset.object_store = self.object_store
        self.init_datatypes()

    def init_datatypes(self):
        datatypes_registry = registry.Registry()
        datatypes_registry.load_datatypes()
        model.set_datatypes_registry(datatypes_registry)
        self.datatypes_registry = datatypes_registry


class DataConfig(object):

    def __init__(self):
        self.database_connection = "sqlite:///:memory:"
        self.jobs_directory = "/tmp"
        self.new_file_path = "/tmp"
        self.file_path = mkdtemp()
