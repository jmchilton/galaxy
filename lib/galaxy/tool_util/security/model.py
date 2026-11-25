"""What a template can read, and how much of it a user controls.

Every name a ``<command>`` template can reference is modelled as a node (a parameter, a dataset, a
collection, a group of parameters): :func:`build_model` builds the :class:`Model` of a tool from
its inputs, outputs, configfiles and template macros.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
)

from galaxy.tool_util.parser.interface import (
    InputSource,
    ToolSource,
)
from galaxy.tool_util.parser.sanitize import ToolParameterSanitizer
from galaxy.util.xml_macros import template_macro_params
from .charsets import (
    Chars,
    default_chars,
    PROBE,
    sanitized,
)
from .nodes import (
    Collection,
    Data,
    Opaque,
    Special,
    User,
    USER_ACCOUNT_ATTRIBUTES,
    Value,
)
from .report import (
    OPAQUE,
    RAW,
    SourceRef,
    SPECIAL,
    TEXT,
    USER_PREFERENCE,
)
from .validators import text_constraint
from .values import (
    AV,
    CLEAN,
    CONDITIONAL,
    Group,
    Node,
    Repeat,
    source,
    tainted,
)

_DYNAMIC_CONDITIONAL = tainted(PROBE, source("value of a conditional built at run time (not sanitized)", OPAQUE))


_SAFE_SPECIALS = (
    "__tool_directory__ __root_dir__ __new_file_path__ __tool_data_path__ __datatypes_config__ __galaxy_url__"
    " __history_id__ __local_working_directory__ __get_data_table_entry__ __admin_users__ GALAXY_DATA_INDEX_DIR"
    " GALAXY_ROOT_DIR GALAXY_DATATYPES_CONF_FILE chromInfo __user_id__ userId user_id __job_resource"
).split()
SAFE_SPECIALS = frozenset(_SAFE_SPECIALS)
_USER_SPECIALS = "__user_email__ userEmail __user_name__ dbkey".split()

# Select-like parameter types whose values come from the user's data.
_USER_SELECT_TYPES = frozenset(("data_column", "group_tag", "genomebuild"))


@dataclass
class Model:
    root: Group
    sanitize: bool = True
    configfiles: dict[str, str] = field(default_factory=dict)
    specials: dict[str, Node] = field(default_factory=dict)
    # Template macros: Cheetah text the template can read in with `#include source=$name#`.
    templates: dict[str, str] = field(default_factory=dict)
    _job_parameters: dict[str, Opaque] = field(default_factory=dict, repr=False)

    def job_parameter(self, name: str) -> AV:
        """A name that is not a tool input: only a job parameter of that name can give it a value.

        Galaxy puts every parameter of the job into the namespace, sanitized like a text parameter.
        A regular job only has the parameters of the tool's inputs, and the template fails where it
        reads any other name.
        """
        if name not in self._job_parameters:
            chars = default_chars(self.sanitize)
            value = tainted(chars, source(f"job parameter ${name}, which is not a tool input", SPECIAL, key=name))
            self._job_parameters[name] = Opaque(f"${name}", value)
        return AV(nodes=(self._job_parameters[name],))

    def sources(self, names: frozenset[str]) -> list[SourceRef]:
        """The user-controlled sources a template that mentions ``names`` can read: the tool's
        inputs, and the account values and preferences it names (``key=None``: any preference)."""
        refs = dict.fromkeys(self.root.sources(names))
        for name in _USER_SPECIALS:
            if name in names:
                refs[SourceRef(SPECIAL, key=name)] = None
        for attribute, key in USER_ACCOUNT_ATTRIBUTES.items():
            if attribute in names:
                refs[SourceRef(SPECIAL, key=key)] = None
        if "extra_preferences" in names:
            refs[SourceRef(USER_PREFERENCE)] = None
        return list(refs)

    def lookup(self, name: str) -> AV | None:
        nodes = self.root.children.get(name)
        if nodes:
            return AV(nodes=tuple(nodes))
        if name in self.specials:
            return AV(nodes=(self.specials[name],))
        # Old tools address nested parameters by their bare name.
        found = self.root.find(name)
        if found:
            return AV(nodes=tuple(found))
        # Galaxy also adds each dataset of a multiple data input by its position: $input1, $input2.
        end = len(name)
        while end > 1 and name[end - 1].isdigit():
            end -= 1
            datasets = [node for node in self.root.children.get(name[:end], ()) if isinstance(node, Data)]
            if datasets:
                return AV(nodes=tuple(datasets))
        return None


def _user_select(input_source: InputSource) -> str | None:
    """Why the options of a select come from user data, None when the tool or the admin defines them."""
    ptype = input_source.get("type")
    if ptype in _USER_SELECT_TYPES:
        return str(ptype)
    if input_source.get("dynamic_options"):
        return "select with options from code"
    dynamic = input_source.parse_dynamic_options()
    if dynamic is None:
        return None
    elem = dynamic.elem()
    if elem.get("from_dataset") or elem.get("from_url"):
        return "select with options from a dataset"
    if elem.get("from_file") or elem.get("from_data_table") or elem.get("from_parameter"):
        return None
    if any(f.get("type") == "data_meta" for f in elem.findall("filter")):
        return "select with options from dataset metadata"
    return None


def _static_options(input_source: InputSource) -> AV:
    """The values of a select whose options the tool lists, as the literals they are."""
    if input_source.parse_dynamic_options() is not None:
        # The options Galaxy offers are built when the form is: the listed ones are not all.
        return CLEAN
    options = frozenset(str(option[1]) for option in input_source.parse_static_options())
    return AV(literals=options) if options else CLEAN


def _escapes_single_quote(sanitizer: ToolParameterSanitizer | None) -> bool:
    """The sanitizer rewrites ' to the sequence that writes a quote inside a single-quoted shell word."""
    return sanitizer is not None and sanitizer.sanitize_param("'") in ("'\"'\"'", "'\\''")


def _value(input_source: InputSource, path: str, tool_sanitize: bool) -> Node:
    ptype = input_source.get("type") or "text"
    if ptype in ("data", "hidden_data"):
        return Data(path, multiple=input_source.get_bool("multiple", False), sanitize=tool_sanitize)
    if ptype == "data_collection":
        types = [t.strip() for t in (input_source.get("collection_type") or "").split(",") if t.strip()]
        nested = any(":" in t for t in types) if types else None
        return Collection(path, nested=nested, sanitize=tool_sanitize)
    if ptype in ("integer", "float", "boolean", "baseurl", "rules"):
        return Value(path, ptype)

    sanitizer_elem = input_source.parse_sanitizer_elem()
    sanitizer = ToolParameterSanitizer.from_element(sanitizer_elem) if sanitizer_elem is not None else None

    def rendered(chars: Chars) -> Chars:
        return sanitized(chars, sanitizer) if tool_sanitize else chars

    if ptype in ("select", "drill_down") or ptype in _USER_SELECT_TYPES:
        reason = _user_select(input_source)
        if reason is None:
            # Its options are the tool's: a name a template looks up a variable by can be built from them.
            options = _static_options(input_source)
            return Value(path, ptype, as_text=options, as_raw=options)
        label = f"{reason} param '{path}'" if reason in _USER_SELECT_TYPES else f"'{path}' ({reason})"
        if ptype == "data_column":
            # Galaxy checks a column against the dataset's columns, except for an empty dataset.
            label += f", {CONDITIONAL}"
        as_raw = tainted(PROBE, source(f"raw value of {label} (not sanitized)", RAW, path))
        as_text = tainted(rendered(PROBE), source(label, TEXT, path))
        return Value(path, ptype, as_text=as_text, as_raw=as_raw, as_element=as_raw)

    constraint = text_constraint(input_source)
    universe = constraint.chars
    # Only a start that is narrower than the rest of the value is worth carrying.
    lead = constraint.lead if "-" in universe and "-" not in constraint.lead else None
    word_first = constraint.word_first()
    words = word_first if "-" in universe and "-" not in word_first else None
    if ptype in ("color", "directory_uri", "file", "ftpfile"):
        # These types return the submitted value as it is: no sanitizer runs when they are rendered.
        value = AV(
            chars=universe,
            # The rendered text is the submitted value.
            sources=frozenset((source(f"{ptype} param '{path}' (not sanitized)", RAW, path),)),
            lead=lead,
            words=words,
        )
        return Value(path, ptype, as_text=value, as_raw=value, text_like=True)
    # text, hidden and anything unknown.
    return Value(
        path,
        ptype,
        as_text=AV(
            chars=rendered(universe),
            sources=frozenset((source(f"{ptype} param '{path}'", TEXT, path),)),
            quoted="sq-escaped" if tool_sanitize and _escapes_single_quote(sanitizer) else "",
            lead=rendered(lead) if lead is not None else None,
            words=rendered(words) if words is not None else None,
            verbatim=True,
        ),
        as_raw=AV(
            chars=universe,
            sources=frozenset((source(f"raw value of {ptype} param '{path}' (sanitizer bypassed)", RAW, path),)),
            lead=lead,
            words=words,
            verbatim=True,
        ),
        text_like=True,
    )


def _add_inputs(group: Group, input_sources: list[InputSource], prefix: str, tool_sanitize: bool) -> None:
    for input_source in input_sources:
        input_type = input_source.parse_input_type()
        try:
            name = input_source.parse_name()
        except ValueError:
            # A parameter without a name cannot be referenced from a template.
            continue
        path = f"{prefix}{name}"
        if input_type == "repeat":
            item = Group(path)
            _add_inputs(
                item, input_source.parse_nested_inputs_source().parse_input_sources(), f"{path}.", tool_sanitize
            )
            group.add(name, Repeat(path, item))
        elif input_type == "section":
            section = Group(path)
            _add_inputs(
                section, input_source.parse_nested_inputs_source().parse_input_sources(), f"{path}.", tool_sanitize
            )
            group.add(name, section)
        elif input_type == "conditional" and not _has_test_param(input_source):
            # A conditional whose cases Galaxy builds at run time (value_from): any value of any name.
            group.add(name, Opaque(path, _DYNAMIC_CONDITIONAL))
        elif input_type == "conditional":
            test_source = input_source.parse_test_input_source()
            conditional = Group(path, selector=test_source.parse_name())
            _add_inputs(conditional, [test_source], f"{path}.", tool_sanitize)
            values = []
            for value_name, case_source in input_source.parse_when_input_sources():
                values.append(str(value_name))
                case = Group(path)
                _add_inputs(case, case_source.parse_input_sources(), f"{path}.", tool_sanitize)
                for child_name, nodes in case.children.items():
                    for node in nodes:
                        conditional.add(child_name, node)
                        conditional.cases[node] = str(value_name)
            conditional.case_values = frozenset(values)
            group.add(name, conditional)
        elif input_type == "param":
            group.add(name, _value(input_source, path, tool_sanitize))
            if (input_source.get("type") or "") in ("data", "hidden_data"):
                # Galaxy adds the dataset converted for a <conversion> next to the parameter.
                for conversion, _ in input_source.parse_conversion_tuples():
                    if conversion and conversion not in group.children:
                        group.add(conversion, Data(f"{prefix}{conversion}", sanitize=tool_sanitize))


def _has_test_param(input_source: InputSource) -> bool:
    elem = getattr(input_source, "input_elem", None)
    return elem is None or elem.find("param") is not None


def build_model(tool_source: ToolSource) -> Model:
    tool_sanitize = bool(tool_source.parse_sanitize())
    root = Group("")
    for page_source in tool_source.parse_input_pages().page_sources:
        _add_inputs(root, page_source.parse_input_sources(), "", tool_sanitize)
    model = Model(root=root, sanitize=tool_sanitize)

    xml_tree: Any = getattr(tool_source, "xml_tree", None)
    if xml_tree is not None:
        # Template macros are an XML construct.
        model.templates = {name: text or "" for name, text in template_macro_params(xml_tree.getroot()).items()}
    try:
        outputs, collections = tool_source.parse_outputs(None)
    except Exception:
        outputs, collections = {}, {}
    for output_name in outputs:
        if output_name not in root.children:
            root.add(output_name, Data(output_name, output=True))
    for collection_name in collections:
        if collection_name not in root.children:
            root.add(collection_name, Collection(collection_name, output=True))
    for configfile in tool_source.parse_template_configfiles():
        if configfile.name:
            model.configfiles[configfile.name] = configfile.content or ""
            if configfile.name not in root.children:
                root.add(configfile.name, Special(f"configfile:{configfile.name}"))
    # Paths of the files Galaxy writes itself: the job's inputs as JSON, the file sources config.
    generated = [c.name for c in tool_source.parse_input_configfiles()]
    generated += [c.name for c in tool_source.parse_file_sources()]
    for name in generated:
        if name and name not in root.children:
            root.add(name, Special(name))

    for name in _SAFE_SPECIALS:
        model.specials[name] = Special(name)
    for name in _USER_SPECIALS:
        chars = default_chars(tool_sanitize)
        model.specials[name] = Special(name, value=tainted(chars, source(f"${name}", SPECIAL, key=name)))

    model.specials["__user__"] = User()
    model.specials["__app__"] = Special("__app__", opaque=CLEAN)
    return model
