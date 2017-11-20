import logging

from galaxy import exceptions, model, web
from galaxy.util import string_as_bool

log = logging.getLogger(__name__)

ERROR_MESSAGE_UNKNOWN_SRC = "Unknown dataset source (src) %s."
ERROR_MESSAGE_NO_NESTED_IDENTIFIERS = "Dataset source new_collection requires nested element_identifiers for new collection."
ERROR_MESSAGE_NO_NAME = "Cannot load invalid dataset identifier - missing name - %s"
ERROR_MESSAGE_NO_COLLECTION_TYPE = "No collection_type define for nested collection %s."
ERROR_MESSAGE_INVALID_PARAMETER_FOUND = "Found invalid parameter %s in element identifier description %s."
ERROR_MESSAGE_DUPLICATED_IDENTIFIER_FOUND = "Found duplicated element identifier name %s."


def api_payload_to_create_params(payload):
    """
    Cleanup API payload to pass into dataset_collections.
    """
    required_parameters = ["collection_type", "element_identifiers"]
    missing_parameters = [p for p in required_parameters if p not in payload]
    if missing_parameters:
        message = "Missing required parameters %s" % missing_parameters
        raise exceptions.ObjectAttributeMissingException(message)

    params = dict(
        collection_type=payload.get("collection_type"),
        element_identifiers=payload.get("element_identifiers"),
        name=payload.get("name", None),
        hide_source_items=string_as_bool(payload.get("hide_source_items", False))
    )
    return params


def validate_input_element_identifiers(element_identifiers):
    """ Scan through the list of element identifiers supplied by the API consumer
    and verify the structure is valid.
    """
    log.debug("Validating %d element identifiers for collection creation." % len(element_identifiers))
    identifier_names = set()
    for element_identifier in element_identifiers:
        if "__object__" in element_identifier:
            message = ERROR_MESSAGE_INVALID_PARAMETER_FOUND % ("__object__", element_identifier)
            raise exceptions.RequestParameterInvalidException(message)
        if "name" not in element_identifier:
            message = ERROR_MESSAGE_NO_NAME % element_identifier
            raise exceptions.RequestParameterInvalidException(message)
        name = element_identifier["name"]
        if name in identifier_names:
            message = ERROR_MESSAGE_DUPLICATED_IDENTIFIER_FOUND % name
            raise exceptions.RequestParameterInvalidException(message)
        else:
            identifier_names.add(name)
        src = element_identifier.get("src", "hda")
        if src not in ["hda", "hdca", "ldda", "new_collection"]:
            message = ERROR_MESSAGE_UNKNOWN_SRC % src
            raise exceptions.RequestParameterInvalidException(message)
        if src == "new_collection":
            if "element_identifiers" not in element_identifier:
                message = ERROR_MESSAGE_NO_NESTED_IDENTIFIERS
                raise exceptions.RequestParameterInvalidException(ERROR_MESSAGE_NO_NESTED_IDENTIFIERS)
            if "collection_type" not in element_identifier:
                message = ERROR_MESSAGE_NO_COLLECTION_TYPE % element_identifier
                raise exceptions.RequestParameterInvalidException(message)
            validate_input_element_identifiers(element_identifier["element_identifiers"])


def get_hda_and_element_identifiers(dataset_collection_instance):
    name = dataset_collection_instance.name
    collection = dataset_collection_instance.collection
    return get_collection(collection, name=name)


def get_collection(collection, name=""):
    names = []
    hdas = []
    if collection.has_subcollections:
        for element in collection.elements:
            subnames, subhdas = get_collection_elements(element.child_collection, name="%s/%s" % (name, element.element_identifier))
            names.extend(subnames)
            hdas.extend(subhdas)
    else:
        for element in collection.elements:
            names.append("%s/%s" % (name, element.element_identifier))
            hdas.append(element.dataset_instance)
    return names, hdas


def get_collection_elements(collection, name=""):
    names = []
    hdas = []
    for element in collection.elements:
        full_element_name = "%s/%s" % (name, element.element_identifier)
        if element.is_collection:
            subnames, subhdas = get_collection(element.child_collection, name=full_element_name)
            names.extend(subnames)
            hdas.extend(subhdas)
        else:
            names.append(full_element_name)
            hdas.append(element.dataset_instance)
    return names, hdas


def dictify_dataset_collection_instance(dataset_collection_instance, parent, security, view="element"):
    hdca_view = "element" if view in ["element", "element-reference"] else "collection"
    dict_value = dataset_collection_instance.to_dict(view=hdca_view)
    encoded_id = security.encode_id(dataset_collection_instance.id)
    if isinstance(parent, model.History):
        encoded_history_id = security.encode_id(parent.id)
        dict_value['url'] = web.url_for('history_content_typed', history_id=encoded_history_id, id=encoded_id, type="dataset_collection")
    elif isinstance(parent, model.LibraryFolder):
        encoded_library_id = security.encode_id(parent.library.id)
        encoded_folder_id = security.encode_id(parent.id)
        # TODO: Work in progress - this end-point is not right yet...
        dict_value['url'] = web.url_for('library_content', library_id=encoded_library_id, id=encoded_id, folder_id=encoded_folder_id)
    if view == "element":
        collection = dataset_collection_instance.collection
        dict_value['elements'] = [dictify_element(_) for _ in collection.elements]
        dict_value['populated'] = collection.populated
    elif view == "element-reference":
        collection = dataset_collection_instance.collection
        dict_value['elements'] = [dictify_element_reference(_) for _ in collection.elements]

    security.encode_all_ids(dict_value, recursive=True)  # TODO: Use Kyle's recursive formulation of this.
    return dict_value


def dictify_element_reference(element):
    """Load minimal details of elements required to show outline of contents in history panel.

    History panel can use this reference to expand to full details if individual dataset elements
    are clicked.
    """
    dictified = element.to_dict(view="element")
    element_object = element.element_object
    if element_object is not None:
        object_detials = dict(
            id=element_object.id,
            model_class=element_object.__class__.__name__,
        )
        if element.child_collection:
            # Recursively yield elements for each nested collection...
            child_collection = element.child_collection
            object_detials["elements"] = [dictify_element_reference(_) for _ in child_collection.elements]
        else:
            object_detials["state"] = element_object.state
            object_detials["hda_ldda"] = 'hda'
            object_detials["history_id"] = element_object.history_id

    else:
        object_detials = None

    dictified["object"] = object_detials
    return dictified


def dictify_element(element):
    dictified = element.to_dict(view="element")
    element_object = element.element_object
    if element_object is not None:
        object_detials = element.element_object.to_dict()
        if element.child_collection:
            # Recursively yield elements for each nested collection...
            child_collection = element.child_collection
            object_detials["elements"] = [dictify_element(_) for _ in child_collection.elements]
            object_detials["populated"] = child_collection.populated
    else:
        object_detials = None

    dictified["object"] = object_detials
    return dictified


__all__ = ('api_payload_to_create_params', 'dictify_dataset_collection_instance')
