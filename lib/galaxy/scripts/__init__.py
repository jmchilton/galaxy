import os
import sys


# ensure supported version
assert sys.version_info[:2] >= ( 2, 6 ) and sys.version_info[:2] <= ( 2, 7 ), 'Python version must be 2.6 or 2.7, this is: %s' % sys.version


def setup_mapping():
    import galaxy.model.mapping  # need to load this before we unpickle, in order to setup properties assigned by the mappers

    # this looks REAL stupid, but it is REQUIRED in order for SA to insert parameters into the classes defined by the mappers --> it appears that instantiating ANY mapper'ed class would suffice here
    galaxy.model.Job()


def get_and_setup_log(name):
    import logging
    logging.basicConfig()
    log = logging.getLogger(name)
    return log


def get_tmp_dir():
    os.path.abspath(os.getcwd())


def get_datatypes_registry(integrated_datatypes_conf):
    import galaxy.datatypes.registry
    import galaxy.model

    galaxy_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir))
    galaxy.datatypes.metadata.MetadataTempFile.tmp_dir = get_tmp_dir()

    datatypes_registry = galaxy.datatypes.registry.Registry()
    datatypes_registry.load_datatypes(root_dir=galaxy_root, config=integrated_datatypes_conf )
    galaxy.model.set_datatypes_registry(datatypes_registry)
    return datatypes_registry
