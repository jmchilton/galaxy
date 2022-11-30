from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from galaxy.tool_util.parser.cwl import CwlInputSource
from galaxy.tool_util.parser.interface import (
    InputSource,
    PageSource,
    PagesSource,
)
from .models import (
    BooleanParameterModel,
    ColorParameterModel,
    ConditionalParameterModel,
    ConditionalWhen,
    CwlBooleanParameterModel,
    CwlDirectoryParameterModel,
    CwlFileParameterModel,
    CwlFloatParameterModel,
    CwlIntegerParameterModel,
    CwlNullParameterModel,
    CwlStringParameterModel,
    CwlUnionParameterModel,
    DataCollectionParameterModel,
    DataParameterModel,
    FloatParameterModel,
    HiddenParameterModel,
    IntegerParameterModel,
    LabelValue,
    RepeatParameterModel,
    RulesParameterModel,
    SelectParameterModel,
    TextParameterModel,
    ToolParameterBundle,
    ToolParameterBundleModel,
    ToolParameterModel,
)


def _from_input_source_galaxy(input_source: InputSource) -> ToolParameterModel:
    input_type = input_source.parse_input_type()
    if input_type == "param":
        param_type = input_source.get("type")
        if param_type == "integer":
            optional = input_source.parse_optional()
            return IntegerParameterModel(
                name=input_source.parse_name(),
                optional=optional,
            )
        elif param_type == "boolean":
            return BooleanParameterModel(
                name=input_source.parse_name(),
            )
        elif param_type == "text":
            optional = input_source.parse_optional()
            return TextParameterModel(
                name=input_source.parse_name(),
                optional=optional,
            )
        elif param_type == "float":
            optional = input_source.parse_optional()
            return FloatParameterModel(
                name=input_source.parse_name(),
                optional=optional,
            )
        elif param_type == "hidden":
            optional = input_source.parse_optional()
            return HiddenParameterModel(
                name=input_source.parse_name(),
                optional=optional,
            )
        elif param_type == "color":
            optional = input_source.parse_optional()
            return ColorParameterModel(
                name=input_source.parse_name(),
                optional=optional,
            )
        elif param_type == "rules":
            return RulesParameterModel(
                name=input_source.parse_name(),
            )
        elif param_type == "data":
            optional = input_source.parse_optional()
            multiple = input_source.get_bool("multiple", False)
            return DataParameterModel(
                name=input_source.parse_name(),
                optional=optional,
                multiple=multiple,
            )
        elif param_type == "data_collection":
            optional = input_source.parse_optional()
            return DataCollectionParameterModel(
                name=input_source.parse_name(),
                optional=optional,
            )
        elif param_type == "select":
            # Function... example in devteam cummeRbund.
            optional = input_source.parse_optional()
            dynamic_options = input_source.get("dynamic_options", None)
            dynamic_options_elem = input_source.parse_dynamic_options_elem()
            multiple = input_source.get_bool("multiple", False)
            is_static = dynamic_options is None and dynamic_options_elem is None
            options: Optional[List[LabelValue]] = None
            if is_static:
                options = []
                for (option_label, option_value, _) in input_source.parse_static_options():
                    options.append(LabelValue(label=option_label, value=option_value))
            return SelectParameterModel(
                name=input_source.parse_name(),
                optional=optional,
                options=options,
                multiple=multiple,
            )
        else:
            raise Exception(f"Unknown Galaxy parameter type {param_type}")
    elif input_type == "conditional":
        test_param_input_source = input_source.parse_test_input_source()
        test_parameter = _from_input_source_galaxy(test_param_input_source)
        whens = []
        for (value, case_inputs_sources) in input_source.parse_when_input_sources():
            tool_parameter_models = input_models_for_page(case_inputs_sources)
            whens.append(ConditionalWhen(discriminator=value, parameters=tool_parameter_models))
        return ConditionalParameterModel(
            name=input_source.parse_name(),
            test_parameter=test_parameter,
            whens=whens,
        )
    elif input_type == "repeat":
        # TODO: min/max
        name = input_source.get("name")
        # title = input_source.get("title")
        # help = input_source.get("help", None)
        instance_sources = input_source.parse_nested_inputs_source()
        instance_tool_parameter_models = input_models_for_page(instance_sources)
        return RepeatParameterModel(
            name=name,
            parameters=instance_tool_parameter_models,
        )
    else:
        raise Exception(
            f"Cannot generate tool parameter model for supplied tool source - unknown input_type {input_type}"
        )


def _simple_cwl_type_to_model(simple_type: str, input_source: CwlInputSource):
    if simple_type == "int":
        return CwlIntegerParameterModel(
            name=input_source.parse_name(),
        )
    elif simple_type == "float":
        return CwlFloatParameterModel(
            name=input_source.parse_name(),
        )
    elif simple_type == "null":
        return CwlNullParameterModel(
            name=input_source.parse_name(),
        )
    elif simple_type == "string":
        return CwlStringParameterModel(
            name=input_source.parse_name(),
        )
    elif simple_type == "boolean":
        return CwlBooleanParameterModel(
            name=input_source.parse_name(),
        )
    elif simple_type == "org.w3id.cwl.cwl.File":
        return CwlFileParameterModel(
            name=input_source.parse_name(),
        )
    elif simple_type == "org.w3id.cwl.cwl.Directory":
        return CwlDirectoryParameterModel(
            name=input_source.parse_name(),
        )
    raise NotImplementedError(
        f"Cannot generate tool parameter model for this CWL artifact yet - contains unknown type {simple_type}."
    )


def _from_input_source_cwl(input_source: CwlInputSource) -> ToolParameterModel:
    schema_salad_field = input_source.field
    if schema_salad_field is None:
        raise NotImplementedError("Cannot generate tool parameter model for this CWL artifact yet.")
    if "type" not in schema_salad_field:
        raise NotImplementedError("Cannot generate tool parameter model for this CWL artifact yet.")
    schema_salad_type = schema_salad_field["type"]
    if isinstance(schema_salad_type, str):
        return _simple_cwl_type_to_model(schema_salad_type, input_source)
    elif isinstance(schema_salad_type, list):
        return CwlUnionParameterModel(
            name=input_source.parse_name(),
            parameters=[_simple_cwl_type_to_model(t, input_source) for t in schema_salad_type],
        )
    else:
        raise NotImplementedError("Cannot generate tool parameter model for this CWL artifact yet.")


def input_models_from_json(json: List[Dict[str, Any]]) -> ToolParameterBundle:
    return ToolParameterBundleModel(input_models=json)


def input_models_for_pages(pages: PagesSource) -> List[ToolParameterModel]:
    input_models = []
    if pages.inputs_defined:
        for page_source in pages.page_sources:
            input_models.extend(input_models_for_page(page_source))

    return input_models


def input_models_for_page(page_source: PageSource) -> List[ToolParameterModel]:
    input_models = []
    for input_source in page_source.parse_input_sources():
        tool_parameter_model = from_input_source(input_source)
        input_models.append(tool_parameter_model)
    return input_models


def from_input_source(input_source: InputSource) -> ToolParameterModel:
    tool_parameter: ToolParameterModel
    if isinstance(input_source, CwlInputSource):
        tool_parameter = _from_input_source_cwl(input_source)
    else:
        tool_parameter = _from_input_source_galaxy(input_source)
    return tool_parameter
