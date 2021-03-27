"""This module contains a linting functions for tool inputs."""
from galaxy.util import string_as_bool
from ._util import is_datasource, is_valid_cheetah_placeholder
from ..parser.util import _parse_name


def lint_inputs(tool_xml, lint_ctx):
    """Lint parameters in a tool's inputs block."""
    datasource = is_datasource(tool_xml)
    inputs = tool_xml.findall("./inputs//param")
    num_inputs = 0
    for param in inputs:
        num_inputs += 1
        param_attrib = param.attrib
        if "name" not in param_attrib and "argument" not in param_attrib:
            lint_ctx.error("Found param input with no name specified.")
            continue
        param_name = _parse_name(param_attrib.get("name"), param_attrib.get("argument"))

        if "type" not in param_attrib:
            lint_ctx.error(f"Param input [{param_name}] input with no type specified.")
            continue
        param_type = param_attrib["type"]

        if not is_valid_cheetah_placeholder(param_name):
            lint_ctx.warn(f"Param input [{param_name}] is not a valid Cheetah placeholder.")

        if param_type == "data":
            if "format" not in param_attrib:
                lint_ctx.warn(f"Param input [{param_name}] with no format specified - 'data' format will be assumed.")
        elif param_type == "select":
            dynamic_options = param.get("dynamic_options", None)
            if dynamic_options is None:
                dynamic_options = param.find("options")

            select_options = param.findall('./option')
            if any(['value' not in option.attrib for option in select_options]):
                lint_ctx.error(f"Select [{param_name}] has option without value")
            if len(set([option.text.strip() for option in select_options])) != len(select_options):
                lint_ctx.error(f"Select [{param_name}] has multiple options with the same text content")
            if len(set([option.attrib.get("value") for option in select_options])) != len(select_options):
                lint_ctx.error(f"Select [{param_name}] has multiple options with the same value")

            if dynamic_options is None and len(select_options) == 0:
                lint_ctx.warn(f"No options defined for select [{param_name}]")

            if param_attrib.get("display") == "radio":
                if string_as_bool(param_attrib.get("multiple", "false")):
                    lint_ctx.error(f'Select [{param_name}] display="radio" is incompatible with multiple="true"')
                if string_as_bool(param_attrib.get("optional", "false")):
                    lint_ctx.error(f'Select [{param_name}] display="radio" is incompatible with optional="true"')
        # TODO: Validate type, much more...

    conditional_selects = tool_xml.findall("./inputs//conditional")
    for conditional in conditional_selects:
        conditional_name = conditional.get('name')
        if not conditional_name:
            lint_ctx.error("Conditional without a name")
        if conditional.get("value_from"):
            # Probably only the upload tool use this, no children elements
            continue
        first_param = conditional.find("param")
        if first_param is None:
            lint_ctx.error(f"Conditional [{conditional_name}] has no child <param>")
            continue
        first_param_type = first_param.get('type')
        if first_param_type not in ['select', 'boolean']:
            lint_ctx.warn(f'Conditional [{conditional_name}] first param should have type="select" /> or type="boolean"')
            continue

        if first_param_type == 'select':
            select_options = _find_with_attribute(first_param, 'option', 'value')
            option_ids = [option.get('value') for option in select_options]
        else:  # boolean
            option_ids = [
                first_param.get('truevalue', 'true'),
                first_param.get('falsevalue', 'false')
            ]

        if string_as_bool(first_param.get('optional', False)):
            lint_ctx.warn(f"Conditional [{conditional_name}] test parameter cannot be optional")

        whens = conditional.findall('./when')
        if any('value' not in when.attrib for when in whens):
            lint_ctx.error(f"Conditional [{conditional_name}] when without value")

        when_ids = [w.get('value') for w in whens]

        for option_id in option_ids:
            if option_id not in when_ids:
                lint_ctx.warn(f"Conditional [{conditional_name}] no <when /> block found for {first_param_type} option '{option_id}'")

        for when_id in when_ids:
            if when_id not in option_ids:
                if first_param_type == 'select':
                    lint_ctx.warn(f"Conditional [{conditional_name}] no <option /> found for when block '{when_id}'")
                else:
                    lint_ctx.warn(f"Conditional [{conditional_name}] no truevalue/falsevalue found for when block '{when_id}'")

    if datasource:
        for datasource_tag in ('display', 'uihints'):
            if not any([param.tag == datasource_tag for param in inputs]):
                lint_ctx.info(f"{datasource_tag} tag usually present in data sources")

    if num_inputs:
        lint_ctx.info(f"Found {num_inputs} input parameters.")
    else:
        if datasource:
            lint_ctx.info("No input parameters, OK for data sources")
        else:
            lint_ctx.warn("Found no input parameters.")


def lint_repeats(tool_xml, lint_ctx):
    """Lint repeat blocks in tool inputs."""
    repeats = tool_xml.findall("./inputs//repeat")
    for repeat in repeats:
        if "name" not in repeat.attrib:
            lint_ctx.error("Repeat does not specify name attribute.")
        if "title" not in repeat.attrib:
            lint_ctx.error("Repeat does not specify title attribute.")


def _find_with_attribute(element, tag, attribute, test_value=None):
    rval = []
    for el in (element.findall('./%s' % tag) or []):
        if attribute not in el.attrib:
            continue
        value = el.attrib[attribute]
        if test_value is not None:
            if value == test_value:
                rval.append(el)
        else:
            rval.append(el)
    return rval
