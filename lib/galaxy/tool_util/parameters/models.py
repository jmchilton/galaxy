from abc import abstractmethod
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Type,
    Union,
)

from pydantic import (
    BaseConfig,
    BaseModel,
    create_model,
    Extra,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    validator,
)
from pydantic.error_wrappers import ValidationError
from typing_extensions import (
    Literal,
    Protocol,
)

from galaxy.exceptions import RequestParameterInvalidException
from ._types import (
    cast_as_type,
    list_type,
    optional_if_needed,
    union_type,
)

# TODO:
# - implement job vs request...
# - drill down
# - implement data_ref on rules and implement some cross model validation
# - Optional conditionals... work through that?
# - Sections - fight that battle again...

# + request: Return info needed to build request pydantic model at runtime.
# + request_internal: This is a pydantic model to validate what Galaxy expects to find in the database,
# in particular dataset and collection references should be decoded integers.
StateRepresentationT = Literal["request", "request_internal", "job_internal", "test_case"]


# could be made more specific - validators need to be classmethod
ValidatorDictT = Dict[str, "classmethod[Any]"]


class DynamicModelInformation(NamedTuple):
    name: str
    definition: tuple
    validators: ValidatorDictT


class StrictModel(BaseModel):
    class Config:
        extra = Extra.forbid


def allow_batching(job_template: DynamicModelInformation, batch_type: Optional[Type] = None) -> DynamicModelInformation:
    job_py_type: Type = job_template.definition[0]
    default_value = job_template.definition[1]
    batch_type = batch_type or job_py_type

    class BatchRequest(StrictModel):
        meta_class: Literal["Batch"] = Field(..., alias="__class__")
        values: List[batch_type]  # type: ignore[valid-type]

    request_type = union_type([job_py_type, BatchRequest])

    return DynamicModelInformation(
        job_template.name,
        (request_type, default_value),
        {},  # should we modify these somehow?
    )


class HasPyType(Protocol):
    @property
    def name(self) -> str:
        ...

    @property
    def py_type(self) -> Type:
        """Get Python Type for simple model type."""
        ...


def dynamic_model_information_from_py_type(param_model: HasPyType, py_type: Optional[Type] = None):
    is_optional = getattr(param_model, "optional", False)
    py_type = py_type or param_model.py_type
    return DynamicModelInformation(
        param_model.name,
        (py_type, ... if not is_optional else None),
        {},
    )


# We probably need incoming (parameter def) and outgoing (parameter value as transmitted) models,
# where value in the incoming model means "default value" and value in the outgoing model is the actual
# value a user has set. (incoming/outgoing from the client perspective).
class BaseToolParameterModelDefinition(BaseModel):
    name: str
    parameter_type: str

    @abstractmethod
    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        """Return info needed to build Pydantic model at runtime for validation."""


class BaseGalaxyToolParameterModelDefinition(BaseToolParameterModelDefinition):
    hidden: bool = False
    label: Optional[str] = None
    help: Optional[str] = None
    argument: Optional[str]
    refresh_on_change: bool = False
    is_dynamic = False
    optional: bool = False


class LabelValue(BaseModel):
    label: str
    value: str


class TextParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["gx_text"] = "gx_text"
    area: bool = False
    default_value: Optional[str] = Field(alias="value")
    default_options: List[LabelValue] = []

    @property
    def py_type(self) -> Type:
        return optional_if_needed(StrictStr, self.optional)

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        return dynamic_model_information_from_py_type(self)


class IntegerParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["gx_integer"] = "gx_integer"
    optional: bool
    value: Optional[int]
    min: Optional[int]
    max: Optional[int]

    @property
    def py_type(self) -> Type:
        return optional_if_needed(StrictInt, self.optional)

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        return dynamic_model_information_from_py_type(self)


class FloatParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["gx_float"] = "gx_float"
    value: Optional[float]
    min: Optional[float]
    max: Optional[float]

    @property
    def py_type(self) -> Type:
        return optional_if_needed(union_type([StrictInt, StrictFloat]), self.optional)

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        return dynamic_model_information_from_py_type(self)


DataSrcT = Literal["hda", "ldda"]
MultiDataSrcT = Literal["hda", "ldda", "hdca"]
CollectionStrT = Literal["hdca"]

TestCaseDataSrcT = Literal["File"]


class DataRequest(StrictModel):
    src: DataSrcT
    id: StrictStr


class BatchDataInstance(StrictModel):
    src: MultiDataSrcT
    id: StrictStr


class MultiDataInstance(StrictModel):
    src: MultiDataSrcT
    id: StrictStr


MultiDataRequest: Type = union_type([MultiDataInstance, List[MultiDataInstance]])


class DataRequestInternal(StrictModel):
    src: DataSrcT
    id: StrictInt


class BatchDataInstanceInternal(StrictModel):
    src: MultiDataSrcT
    id: StrictInt


class MultiDataInstanceInternal(StrictModel):
    src: MultiDataSrcT
    id: StrictInt


class DataTestCaseValue(StrictModel):
    src: TestCaseDataSrcT = Field("class")
    path: str


class MultipleDataTestCaseValue(StrictModel):
    __root__: List[DataTestCaseValue]


MultiDataRequestInternal: Type = union_type([MultiDataInstanceInternal, List[MultiDataInstanceInternal]])


class DataParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["gx_data"] = "gx_data"
    extensions: List[str] = ["data"]
    multiple: bool = False
    min: Optional[int]
    max: Optional[int]

    @property
    def py_type(self) -> Type:
        base_model: Type
        if self.multiple:
            base_model = MultiDataRequest
        else:
            base_model = DataRequest
        return optional_if_needed(base_model, self.optional)

    @property
    def py_type_internal(self) -> Type:
        base_model: Type
        if self.multiple:
            base_model = MultiDataRequestInternal
        else:
            base_model = DataRequestInternal
        return optional_if_needed(base_model, self.optional)

    @property
    def py_type_test_case(self) -> Type:
        base_model: Type
        if self.multiple:
            base_model = MultiDataRequestInternal
        else:
            base_model = DataTestCaseValue
        return optional_if_needed(base_model, self.optional)

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        if state_representation == "request":
            return allow_batching(dynamic_model_information_from_py_type(self), BatchDataInstance)
        elif state_representation == "request_internal":
            return allow_batching(
                dynamic_model_information_from_py_type(self, self.py_type_internal), BatchDataInstanceInternal
            )
        elif state_representation == "job_internal":
            return dynamic_model_information_from_py_type(self, self.py_type_internal)
        elif state_representation == "test_case":
            return dynamic_model_information_from_py_type(self, self.py_type_test_case)


class DataCollectionRequest(StrictModel):
    src: CollectionStrT
    id: StrictStr


class DataCollectionRequestInternal(StrictModel):
    src: CollectionStrT
    id: StrictInt


class DataCollectionParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["gx_data_collection"] = "gx_data_collection"
    collection_type: Optional[str]
    extensions: List[str] = ["data"]

    @property
    def py_type(self) -> Type:
        return optional_if_needed(DataCollectionRequest, self.optional)

    @property
    def py_type_internal(self) -> Type:
        return optional_if_needed(DataCollectionRequestInternal, self.optional)

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        if state_representation == "request":
            return allow_batching(dynamic_model_information_from_py_type(self))
        elif state_representation == "request_internal":
            return allow_batching(dynamic_model_information_from_py_type(self, self.py_type_internal))
        else:
            raise NotImplementedError("...")


class HiddenParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["gx_hidden"] = "gx_hidden"

    @property
    def py_type(self) -> Type:
        return optional_if_needed(StrictStr, self.optional)

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        return dynamic_model_information_from_py_type(self)


def ensure_color_valid(value: Optional[Any]):
    if value is None:
        return
    if not isinstance(value, str):
        raise TypeError(f"Invalid color value type {value.__class__} encountered.")
    value_str: str = value
    message = f"Invalid color value string format {value_str} encountered."
    if len(value_str) != 7:
        raise ValueError(message + "0")
    if value_str[0] != "#":
        raise ValueError(message + "1")
    for byte_str in value_str[1:]:
        if byte_str not in "0123456789abcdef":
            raise ValueError(message + "2")


class ColorParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["gx_color"] = "gx_color"

    @property
    def py_type(self) -> Type:
        return optional_if_needed(StrictStr, self.optional)

    @classmethod
    def validate_color_str(c, value: str) -> str:
        ensure_color_valid(value)
        return value

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        validators = {"color_format": validator(self.name, allow_reuse=True)(ColorParameterModel.validate_color_str)}
        return DynamicModelInformation(
            self.name,
            (self.py_type, ...),
            validators,
        )


class BooleanParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["gx_boolean"] = "gx_boolean"
    value: Optional[bool] = False
    truevalue: Optional[str]
    falsevalue: Optional[str]

    @property
    def py_type(self) -> Type:
        return optional_if_needed(StrictBool, self.optional)

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        return dynamic_model_information_from_py_type(self)


class DirectoryUriParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["gx_directory_uri"]
    value: Optional[str]


class RulesMapping(StrictModel):
    type: str
    columns: List[StrictInt]


class RulesModel(StrictModel):
    rules: List[Dict[str, Any]]
    mappings: List[RulesMapping]


class RulesParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["gx_rules"] = "gx_rules"

    @property
    def py_type(self) -> Type:
        return RulesModel

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        return dynamic_model_information_from_py_type(self)


class SelectParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["gx_select"] = "gx_select"
    options: Optional[List[LabelValue]] = None
    multiple: bool

    @property
    def py_type(self) -> Type:
        if self.options is not None:
            literal_options: List[Type] = [cast_as_type(Literal[o.value]) for o in self.options]
            py_type = union_type(literal_options)
        else:
            py_type = StrictStr
        if self.multiple:
            py_type = list_type(py_type)
        return optional_if_needed(py_type, self.optional)

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        return dynamic_model_information_from_py_type(self)


DiscriminatorType = Union[bool, str]


class ConditionalWhen(StrictModel):
    discriminator: DiscriminatorType
    parameters: List["ToolParameterT"]


class ConditionalParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["gx_conditional"] = "gx_conditional"
    test_parameter: Union[BooleanParameterModel, SelectParameterModel]
    whens: List[ConditionalWhen]

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        test_param_name = self.test_parameter.name
        test_info = self.test_parameter.pydantic_template(state_representation)
        extra_validators = test_info.validators
        when_types: List[Type[BaseModel]] = []
        for when in self.whens:
            discriminator = when.discriminator
            parameters = when.parameters
            extra_kwd = {test_param_name: (Literal[discriminator], ...)}
            when_types.append(
                create_field_model(
                    parameters,
                    f"When_{test_param_name}_{discriminator}",
                    state_representation,
                    extra_kwd=extra_kwd,
                    extra_validators=extra_validators,
                )
            )

        cond_type = union_type(when_types)

        class ConditionalType(BaseModel):
            __root__: cond_type = Field(..., discriminator=test_param_name)  # type: ignore[valid-type]

        return DynamicModelInformation(
            self.name,
            (ConditionalType, ...),
            {},
        )


class RepeatParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["gx_repeat"] = "gx_repeat"
    parameters: List["ToolParameterT"]

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        # Maybe validators for min and max...
        instance_class: Type[BaseModel] = create_field_model(
            self.parameters, f"Repeat_{self.name}", state_representation
        )

        class RepeatType(BaseModel):
            __root__: List[instance_class]  # type: ignore[valid-type]

        return DynamicModelInformation(
            self.name,
            (RepeatType, ...),
            {},
        )


LiteralNone: Type = Literal[None]  # type: ignore[assignment]


class CwlNullParameterModel(BaseToolParameterModelDefinition):
    parameter_type: Literal["cwl_null"] = "cwl_null"

    @property
    def py_type(self) -> Type:
        return LiteralNone

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        return DynamicModelInformation(
            self.name,
            (self.py_type, ...),
            {},
        )


class CwlStringParameterModel(BaseToolParameterModelDefinition):
    parameter_type: Literal["cwl_string"] = "cwl_string"

    @property
    def py_type(self) -> Type:
        return StrictStr

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        return DynamicModelInformation(
            self.name,
            (self.py_type, ...),
            {},
        )


class CwlIntegerParameterModel(BaseToolParameterModelDefinition):
    parameter_type: Literal["cwl_integer"] = "cwl_integer"

    @property
    def py_type(self) -> Type:
        return StrictInt

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        return DynamicModelInformation(
            self.name,
            (self.py_type, ...),
            {},
        )


class CwlFloatParameterModel(BaseToolParameterModelDefinition):
    parameter_type: Literal["cwl_float"] = "cwl_float"

    @property
    def py_type(self) -> Type:
        return union_type([StrictFloat, StrictInt])

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        return DynamicModelInformation(
            self.name,
            (self.py_type, ...),
            {},
        )


class CwlBooleanParameterModel(BaseToolParameterModelDefinition):
    parameter_type: Literal["cwl_boolean"] = "cwl_boolean"

    @property
    def py_type(self) -> Type:
        return StrictBool

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        return DynamicModelInformation(
            self.name,
            (self.py_type, ...),
            {},
        )


class CwlUnionParameterModel(BaseToolParameterModelDefinition):
    parameter_type: Literal["cwl_union"] = "cwl_union"
    parameters: List["CwlParameterT"]

    @property
    def py_type(self) -> Type:
        union_of_cwl_types: List[Type] = []
        for parameter in self.parameters:
            union_of_cwl_types.append(parameter.py_type)
        return union_type(union_of_cwl_types)

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:

        return DynamicModelInformation(
            self.name,
            (self.py_type, ...),
            {},
        )


class CwlFileParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["cwl_file"] = "cwl_file"

    @property
    def py_type(self) -> Type:
        return DataRequest

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        return dynamic_model_information_from_py_type(self)


class CwlDirectoryParameterModel(BaseGalaxyToolParameterModelDefinition):
    parameter_type: Literal["cwl_directory"] = "cwl_directory"

    @property
    def py_type(self) -> Type:
        return DataRequest

    def pydantic_template(self, state_representation: StateRepresentationT) -> DynamicModelInformation:
        return dynamic_model_information_from_py_type(self)


CwlParameterT = Union[
    CwlIntegerParameterModel,
    CwlFloatParameterModel,
    CwlStringParameterModel,
    CwlBooleanParameterModel,
    CwlNullParameterModel,
    CwlFileParameterModel,
    CwlDirectoryParameterModel,
    CwlUnionParameterModel,
]

GalaxyParameterT = Union[
    TextParameterModel,
    IntegerParameterModel,
    FloatParameterModel,
    BooleanParameterModel,
    HiddenParameterModel,
    SelectParameterModel,
    DataParameterModel,
    DataCollectionParameterModel,
    DirectoryUriParameterModel,
    RulesParameterModel,
    ColorParameterModel,
    ConditionalParameterModel,
    RepeatParameterModel,
]

ToolParameterT = Union[
    CwlParameterT,
    GalaxyParameterT,
]


class ToolParameterModel(BaseModel):
    __root__: ToolParameterT = Field(..., discriminator="parameter_type")


ConditionalWhen.update_forward_refs()
ConditionalParameterModel.update_forward_refs()
RepeatParameterModel.update_forward_refs()
CwlUnionParameterModel.update_forward_refs()


class ToolParameterBundle(Protocol):
    """An object having a dictionary of input models (i.e. a 'Tool')"""

    # TODO: rename to parameters to align with ConditionalWhen and Repeat.
    input_models: List[ToolParameterModel]


class ToolParameterBundleModel(BaseModel):

    input_models: List[ToolParameterModel]


def parameters_by_name(tool_parameter_bundle: ToolParameterBundle) -> Dict[str, ToolParameterT]:
    as_dict = {}
    for input_model in tool_parameter_bundle.input_models:
        if input_model.__class__ == ToolParameterModel:
            input_model = input_model.__root__
        as_dict[input_model.name] = input_model
    return as_dict


def create_model_strict(*args, **kwd) -> Type[BaseModel]:
    class Config(BaseConfig):
        extra = Extra.forbid

    return create_model(*args, __config__=Config, **kwd)


def create_request_model(tool: ToolParameterBundle, name: str = "DynamicModelForTool") -> Type[BaseModel]:
    return create_field_model(tool.input_models, name, "request")


def create_request_internal_model(tool: ToolParameterBundle, name: str = "DynamicModelForTool") -> Type[BaseModel]:
    return create_field_model(tool.input_models, name, "request_internal")


def create_field_model(
    tool_parameter_models: Union[List[ToolParameterModel], List[ToolParameterT]],
    name: str,
    state_representation: StateRepresentationT,
    extra_kwd: Optional[Mapping[str, tuple]] = None,
    extra_validators: Optional[ValidatorDictT] = None,
):
    kwd: Dict[str, tuple] = {}
    if extra_kwd:
        kwd.update(extra_kwd)
    model_validators = (extra_validators or {}).copy()

    for input_model in tool_parameter_models:
        if input_model.__class__ == ToolParameterModel:
            input_model = input_model.__root__
        from typing import cast

        input_model = cast(ToolParameterT, input_model)
        input_name = input_model.name
        pydantic_request_template = input_model.pydantic_template(state_representation)
        kwd[input_name] = pydantic_request_template.definition
        input_validators = pydantic_request_template.validators
        for validator_name, validator_callable in input_validators.items():
            model_validators[f"{input_name}_{validator_name}"] = validator_callable

    pydantic_model = create_model_strict(name, __validators__=model_validators, **kwd)
    return pydantic_model


def validate_against_model(pydantic_model: Type[BaseModel], parameter_state: Dict[str, Any]) -> None:
    try:
        pydantic_model(**parameter_state)
    except ValidationError as e:
        # TODO: Improve this or maybe add a handler for this in the FastAPI exception
        # handler.
        raise RequestParameterInvalidException(str(e))


def validate_request(tool: ToolParameterBundle, request: Dict[str, Any]) -> None:
    pydantic_model = create_request_model(tool)
    validate_against_model(pydantic_model, request)


def validate_internal_request(tool: ToolParameterBundle, request: Dict[str, Any]) -> None:
    pydantic_model = create_request_internal_model(tool)
    validate_against_model(pydantic_model, request)
