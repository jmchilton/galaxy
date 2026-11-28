"""What a template can read, and how much of it a user controls.

Every name a ``<command>`` template can reference is modelled as a node (a parameter, a dataset, a
collection, a group of parameters): :func:`build_model` builds the :class:`Model` of a tool from
its inputs, outputs, configfiles and template macros.
"""

from __future__ import annotations

import re
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    Callable,
)

from galaxy.tool_util.parser.interface import (
    InputSource,
    ToolSource,
)
from galaxy.tool_util.parser.sanitize import ToolParameterSanitizer
from galaxy.util.xml_macros import template_macro_params
from .charsets import (
    backslash_escaped,
    Chars,
    default_chars,
    NONE,
    probe,
    PROBE,
    sanitized,
    SINGLE_QUOTE_ESCAPES,
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
# Of these, the names Galaxy sets before it adds the job's parameters to the namespace, or never sets:
# a job parameter of the same name replaces them where it reaches the templates, which it does only
# for a tool that keeps the job parameters that are not inputs (a data source tool).
REPLACEABLE_SPECIALS = frozenset(
    "__datatypes_config__ GALAXY_DATATYPES_CONF_FILE __history_id__ __galaxy_url__ user_id __job_resource".split()
)
_USER_SPECIALS = "__user_email__ userEmail __user_name__ dbkey".split()

# Select-like parameter types whose values come from the user's data.
_USER_SELECT_TYPES = frozenset(("data_column", "group_tag", "genomebuild"))

# What a color param holds where Galaxy checks colour values: a name, bare hex or #RRGGBB; with rgb="true"
# it renders as a tuple such as (255, 0, 0).
_COLOR_CHARS: Chars = frozenset("#")
_RGB_COLOR_CHARS: Chars = frozenset("(), ")


@dataclass
class Model:
    root: Group
    sanitize: bool = True
    configfiles: dict[str, str] = field(default_factory=dict)
    specials: dict[str, Node] = field(default_factory=dict)
    # Template macros: Cheetah text the template can read in with `#include source=$name#`.
    templates: dict[str, str] = field(default_factory=dict)
    # The job parameters besides the tool's inputs that Galaxy passes to the templates
    # (`Tool.template_job_parameters`). None: any name, for a tool that keeps all its job parameters
    # (a data source tool) or a review that does not know the tool's.
    template_job_parameters: frozenset[str] | None = None
    keeps_undeclared_job_parameters: bool = False
    _job_parameters: dict[str, Opaque] = field(default_factory=dict, repr=False)

    def galaxy_path(self, name: str) -> bool:
        """Whether ``name`` is a path Galaxy sets, which no job parameter replaces."""
        return name in SAFE_SPECIALS and not (self.keeps_undeclared_job_parameters and name in REPLACEABLE_SPECIALS)

    def can_be_job_parameter(self, name: str) -> bool:
        """Whether a job parameter of this name, not a tool input, reaches the templates."""
        return self.template_job_parameters is None or name in self.template_job_parameters

    def job_parameter(self, name: str) -> AV:
        """A name that is not a tool input: only a job parameter of that name can give it a value.

        A regular tool's templates get its inputs, the job parameters in ``template_job_parameters``
        and the `<input>|__identifier__` names; a tool that keeps all its job parameters gets every
        request parameter, sanitized like a text parameter. A regular job only has the parameters of
        the tool's inputs, and the template fails where it reads any other name. The review still
        reads an unknown name as such a parameter, which over-reports at worst.
        """
        if name not in self._job_parameters:
            chars = default_chars(self.sanitize)
            value = tainted(chars, source(f"job parameter ${name}, which is not a tool input", SPECIAL, key=name))
            self._job_parameters[name] = Opaque(f"${name}", value)
        return AV(nodes=(self._job_parameters[name],))

    def sources(self, names: frozenset[str], looked_up: frozenset[str]) -> list[SourceRef]:
        """The user-controlled sources a template that mentions ``names`` can read: the tool's
        inputs, the account values and preferences it names (``key=None``: any preference), and the
        job parameters of the names it looks up in the namespace (``looked_up``)."""
        refs = dict.fromkeys(self.root.sources(names))
        for name in _USER_SPECIALS:
            if name in names:
                refs[SourceRef(SPECIAL, key=name)] = None
        if self.keeps_undeclared_job_parameters:
            for name in REPLACEABLE_SPECIALS & names:
                refs[SourceRef(SPECIAL, key=name)] = None
        for name in sorted(looked_up):
            # A job parameter of a name no input or Galaxy value holds, where one reaches the templates.
            if name not in self.specials and self.lookup(name) is None and self.can_be_job_parameter(name):
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


_PLAIN_OPTION = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")


def _static_options(input_source: InputSource, ptype: str) -> tuple[str, ...] | None:
    """The values of a select whose options the tool lists, when each is a plain name that its text renders
    unchanged, joined by commas."""
    if ptype != "select" or input_source.get("dynamic_options") or input_source.parse_dynamic_options() is not None:
        return None
    if input_source.parse_sanitizer_elem() is not None or (input_source.get("separator") or ",") != ",":
        return None
    values = tuple(value for _, value, _ in input_source.parse_static_options())
    if not values or not all(isinstance(value, str) and _PLAIN_OPTION.match(value) for value in values):
        return None
    return values


def _listed_chars(input_source: InputSource, ptype: str, rendered: Callable[[Chars], Chars]) -> Chars | None:
    """The probe characters of every text a boolean or a select whose options the tool lists can render."""
    if ptype == "boolean":
        texts = [input_source.get("truevalue") or "true", input_source.get("falsevalue") or "false"]
    elif ptype == "select" and not input_source.get("dynamic_options") and input_source.parse_dynamic_options() is None:
        texts = [str(value) for _, value, _ in input_source.parse_static_options()]
        texts.append(input_source.get("separator") or ",")
    else:
        return None
    chars = probe("".join(texts))
    return chars | rendered(chars)


def _escapes_single_quote(sanitizer: ToolParameterSanitizer | None) -> bool:
    """The sanitizer rewrites ' to the sequence that writes a quote inside a single-quoted shell word."""
    return sanitizer is not None and sanitizer.sanitize_param("'") in SINGLE_QUOTE_ESCAPES


def _value(
    input_source: InputSource, path: str, tool_sanitize: bool, wrapped: bool = True, colors_validated: bool = True
) -> Node:
    """``wrapped``: Galaxy writes the param through its parameter wrapper. Without one (a tool that does not
    check its values) the value is a string the default sanitizer cleans: the param's own sanitizer and
    attributes such as `.value` belong to the wrapper. ``colors_validated``: see :func:`build_model`."""
    ptype = input_source.get("type") or "text"
    if ptype in ("data", "hidden_data"):
        return Data(path, multiple=input_source.get_bool("multiple", False), sanitize=tool_sanitize)
    if ptype == "data_collection":
        types = [t.strip() for t in (input_source.get("collection_type") or "").split(",") if t.strip()]
        nested = any(":" in t for t in types) if types else None
        return Collection(path, nested=nested, sanitize=tool_sanitize)
    if ptype == "boolean":
        return Value(path, ptype, listed=_listed_chars(input_source, ptype, lambda chars: chars))
    if ptype in ("integer", "float", "rules") or (ptype == "baseurl" and wrapped):
        return Value(path, ptype)

    sanitizer_elem = input_source.parse_sanitizer_elem()
    sanitizer = ToolParameterSanitizer.from_element(sanitizer_elem) if sanitizer_elem is not None and wrapped else None

    def rendered(chars: Chars) -> Chars:
        return sanitized(chars, sanitizer) if tool_sanitize else chars

    if ptype in ("select", "drill_down") or ptype in _USER_SELECT_TYPES:
        reason = _user_select(input_source)
        if reason is None:
            listed = _listed_chars(input_source, ptype, rendered)
            return Value(path, ptype, options=_static_options(input_source, ptype), listed=listed)
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
    if ptype == "color" and wrapped and colors_validated:
        # The job's evaluation checks the value, and rendering it checks it again.
        checked = universe & _COLOR_CHARS
        text = AV(
            chars=_RGB_COLOR_CHARS if input_source.get_bool("rgb", False) else checked,
            sources=frozenset((source(f"color param '{path}'", TEXT, path),)),
            verbatim=True,
        )
        raw = AV(
            chars=checked, sources=frozenset((source(f"value of color param '{path}'", RAW, path),)), verbatim=True
        )
        return Value(path, ptype, as_text=text, as_raw=raw, text_like=True)
    if ptype in ("color", "directory_uri", "ftpfile") and wrapped:
        # These types return the submitted value as it is: no sanitizer runs when they are rendered.
        value = AV(
            chars=universe,
            # The rendered text is the submitted value.
            sources=frozenset((source(f"{ptype} param '{path}' (not sanitized)", RAW, path),)),
            lead=lead,
            words=words,
        )
        return Value(path, ptype, as_text=value, as_raw=value, text_like=True)
    # text, hidden, file (rendered by ToolParameter.to_param_dict_string, sanitized) and anything unknown.
    escaped = backslash_escaped(universe, sanitizer) if tool_sanitize and sanitizer is not None else NONE
    if tool_sanitize and _escapes_single_quote(sanitizer):
        quoted = "sq-escaped"
    else:
        quoted = "bs-escaped" if escaped else ""
    text = AV(
        chars=rendered(universe),
        sources=frozenset((source(f"{ptype} param '{path}'", TEXT, path),)),
        quoted=quoted,
        escaped=escaped if quoted == "bs-escaped" else NONE,
        lead=rendered(lead) if lead is not None else None,
        words=rendered(words) if words is not None else None,
        verbatim=True,
    )
    raw = AV(
        chars=universe,
        sources=frozenset((source(f"raw value of {ptype} param '{path}' (sanitizer bypassed)", RAW, path),)),
        lead=lead,
        words=words,
        verbatim=True,
    )
    return Value(path, ptype, as_text=text, as_raw=raw, text_like=True, wrapped=wrapped)


def _add_inputs(
    group: Group,
    input_sources: list[InputSource],
    prefix: str,
    tool_sanitize: bool,
    wrapped: bool,
    colors_validated: bool,
) -> None:
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
                item,
                input_source.parse_nested_inputs_source().parse_input_sources(),
                f"{path}.",
                tool_sanitize,
                wrapped,
                colors_validated,
            )
            group.add(name, Repeat(path, item))
        elif input_type == "section":
            section = Group(path)
            _add_inputs(
                section,
                input_source.parse_nested_inputs_source().parse_input_sources(),
                f"{path}.",
                tool_sanitize,
                wrapped,
                colors_validated,
            )
            group.add(name, section)
        elif input_type == "conditional" and not _has_test_param(input_source):
            # A conditional whose cases Galaxy builds at run time (value_from): any value of any name.
            group.add(name, Opaque(path, _DYNAMIC_CONDITIONAL))
        elif input_type == "conditional":
            test_source = input_source.parse_test_input_source()
            conditional = Group(path, selector=test_source.parse_name())
            _add_inputs(conditional, [test_source], f"{path}.", tool_sanitize, wrapped, colors_validated)
            values = []
            for value_name, case_source in input_source.parse_when_input_sources():
                values.append(str(value_name))
                case = Group(path)
                _add_inputs(
                    case, case_source.parse_input_sources(), f"{path}.", tool_sanitize, wrapped, colors_validated
                )
                for child_name, nodes in case.children.items():
                    for node in nodes:
                        conditional.add(child_name, node)
                        conditional.cases[node] = str(value_name)
            conditional.case_values = frozenset(values)
            group.add(name, conditional)
        elif input_type == "param":
            group.add(name, _value(input_source, path, tool_sanitize, wrapped, colors_validated))
            if (input_source.get("type") or "") in ("data", "hidden_data"):
                # Galaxy adds the dataset converted for a <conversion> next to the parameter.
                for conversion, _ in input_source.parse_conversion_tuples():
                    if conversion and conversion not in group.children:
                        group.add(conversion, Data(f"{prefix}{conversion}", sanitize=tool_sanitize))


def _has_test_param(input_source: InputSource) -> bool:
    elem = getattr(input_source, "input_elem", None)
    return elem is None or elem.find("param") is not None


def build_model(
    tool_source: ToolSource,
    template_job_parameters: frozenset[str] | None = None,
    keeps_undeclared_job_parameters: bool = False,
    colors_validated: bool = True,
) -> Model:
    """``keeps_undeclared_job_parameters``: the tool does not check its values (`check_values="false"`, a data
    source tool), so Galaxy passes it its job parameters as sent, and its inputs without parameter wrappers.
    ``colors_validated``: the Galaxy that runs the tool renders a color param only when it is a colour
    (release 25.1 and later), which the default assumes; an older one writes any value it is sent."""
    tool_sanitize = bool(tool_source.parse_sanitize())
    wrapped = not keeps_undeclared_job_parameters
    root = Group("")
    for page_source in tool_source.parse_input_pages().page_sources:
        _add_inputs(root, page_source.parse_input_sources(), "", tool_sanitize, wrapped, colors_validated)
    model = Model(
        root=root,
        sanitize=tool_sanitize,
        template_job_parameters=None if keeps_undeclared_job_parameters else template_job_parameters,
        keeps_undeclared_job_parameters=keeps_undeclared_job_parameters,
    )

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
        if keeps_undeclared_job_parameters and name in REPLACEABLE_SPECIALS:
            chars = default_chars(tool_sanitize)
            text = f"${name}, which a job parameter of a tool that keeps all its job parameters replaces"
            model.specials[name] = Special(name, value=tainted(chars, source(text, SPECIAL, key=name)))
    for name in _USER_SPECIALS:
        chars = default_chars(tool_sanitize)
        model.specials[name] = Special(name, value=tainted(chars, source(f"${name}", SPECIAL, key=name)))

    model.specials["__user__"] = User()
    model.specials["__app__"] = Special("__app__", opaque=CLEAN)
    return model
