"""
"""


def get_required_item(from_dict, key, message):
    if key not in from_dict:
        raise RequestParameterInvalidException(message)
    return from_dict[key]


def build_library_for_destination(destination, trans, library_manager):
    library_name = get_required_item(destination, "name", "Must specify a library name")
    description = destination.get("description", "")
    synopsis = destination.get("synopsis", "")
    library = library_manager.create(
        trans, library_name, description=description, synopsis=synopsis
    )
    for key in ["name", "description", "synopsis"]:
        if key in destination:
            del destination[key]
    return library


def validate_and_normalize_target(obj):
    replace_request_syntax_sugar(obj)


def replace_request_syntax_sugar(obj):
    # For data libraries and hdas to make sense - allow items and items_from in place of elements
    # and elements_from. This is destructive and modifies the supplied request.
    if isinstance(obj, list):
        for el in obj:
            replace_request_syntax_sugar(el)
    elif isinstance(obj, dict):
        if "items" in obj:
            obj["elements"] = obj["items"]
            del obj["items"]
        if "items_from" in obj:
            obj["elements_from"] = obj["items_from"]
            del obj["items_from"]
        for value in obj.values():
            replace_request_syntax_sugar(value)
