import pkg_resources

import swagger_spec_validator.common

DRS_SPEC = pkg_resources.resource_filename(__name__, 'data_repository_service.swagger.yaml')


def _schema():
    return swagger_spec_validator.common.read_file(DRS_SPEC)    


def GetObject(object_id):
    return {}, 200


def GetBundle(bundle_id):
    return {}, 200


def GetAccessURL(object_id, access_id):

    return response, 200

def GetServiceInfo():
    return _schema()['info'], 200
