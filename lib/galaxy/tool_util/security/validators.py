"""What the validators of a text parameter leave of a submitted value.

Galaxy rejects a value its validators do not accept, so a validator narrows what can reach
the template: the probe characters the value may contain, and those it may begin with.
Two kinds are read: ``regex`` (applied with ``re.match``) and ``expression`` (a Python
expression over ``value``). An expression is read from its syntax tree and never evaluated;
any form that is not recognised leaves the value unconstrained.

Galaxy does not evaluate ``expression`` validators of tools it loads as untrusted, so what
is read from them here holds for tools installed by an administrator only.
"""

import ast
import warnings
from typing import NamedTuple

from galaxy.tool_util.parser.interface import InputSource
from galaxy.tool_util_models.parameter_validators import (
    ExpressionParameterValidatorModel,
    RegexParameterValidatorModel,
)
from .charsets import (
    Chars,
    NONE,
    probe,
    PROBE,
    regex_first,
    regex_universe,
)


class Constraint(NamedTuple):
    chars: Chars = PROBE  # probe characters the value may contain
    lead: Chars = PROBE  # probe characters the value may begin with

    def both(self, other: "Constraint") -> "Constraint":
        return Constraint(self.chars & other.chars, self.lead & other.lead)

    def either(self, other: "Constraint") -> "Constraint":
        return Constraint(self.chars | other.chars, self.lead | other.lead)

    def allowing(self, extra: Chars) -> "Constraint":
        return Constraint(self.chars | extra, self.lead | extra)


ANY = Constraint()
EMPTY = Constraint(NONE, NONE)
_WHITESPACE: Chars = frozenset(" \t\n")

# str predicates that are false for every probe character, except the ones listed.
_PREDICATES: dict[str, Chars] = {
    "isalnum": NONE,
    "isalpha": NONE,
    "isdigit": NONE,
    "isnumeric": NONE,
    "isdecimal": NONE,
    "isidentifier": frozenset("_"),
    "isprintable": PROBE - frozenset("\t\n"),
}


def _text(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _texts(node: ast.AST) -> list[str] | None:
    """The strings of a constant, or of a tuple, list or set of constants."""
    text = _text(node)
    if text is not None:
        return [text]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        texts = [_text(elt) for elt in node.elts]
        if all(t is not None for t in texts):
            return [t for t in texts if t is not None]
    return None


def _is_value(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "value"


def _subject(node: ast.AST) -> Chars | None:
    """``value``, or ``value`` with characters taken out first: the characters taken out.

    ``value.replace(':', '').isalnum()`` accepts a value of letters, digits and colons.
    Returns None when the expression is about something other than the value.
    """
    if _is_value(node):
        return NONE
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return None
    inner = _subject(node.func.value)
    if inner is None:
        return None
    name = node.func.attr
    if name in ("strip", "lstrip", "rstrip") and not node.keywords:
        stripped = _text(node.args[0]) if node.args else " \t\n"
        return inner | probe(stripped) if stripped is not None and len(node.args) <= 1 else None
    if name == "replace" and len(node.args) == 2 and not node.keywords:
        old, new = _text(node.args[0]), _text(node.args[1])
        if old is not None and new == "":
            return inner | probe(old)
    if name in ("lower", "upper", "casefold"):
        return inner
    return None


def _is_first_character(node: ast.AST) -> bool:
    return isinstance(node, ast.Subscript) and _is_value(node.value) and _text_or_int(node.slice) == 0


def _text_or_int(node: ast.AST) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _without(characters: str) -> Constraint:
    gone = probe(characters)
    return Constraint(PROBE - gone, PROBE - gone)


def _absent(needle: ast.AST, haystack: ast.AST) -> Constraint:
    """``needle not in haystack``."""
    text = _text(needle)
    if text is not None and len(text) == 1 and _is_value(haystack):
        return _without(text)
    excluded = _text(haystack)
    if excluded is not None and _is_first_character(needle):
        return Constraint(PROBE, PROBE - probe(excluded))
    return ANY


def _present(needle: ast.AST, haystack: ast.AST) -> Constraint:
    """``needle in haystack``."""
    allowed = _texts(haystack)
    if allowed is None or not _is_value(needle):
        return ANY
    if isinstance(haystack, ast.Constant):
        # `value in "text"`: the value is a piece of the text.
        return Constraint(probe(allowed[0]), probe(allowed[0]))
    return Constraint(probe("".join(allowed)), probe("".join(text[:1] for text in allowed)))


def _comprehension(node: ast.AST) -> tuple[ast.expr, ast.comprehension] | None:
    if isinstance(node, (ast.GeneratorExp, ast.ListComp)) and len(node.generators) == 1:
        generator = node.generators[0]
        if not generator.ifs and isinstance(generator.target, ast.Name):
            return node.elt, generator
    return None


def _quantified(node: ast.Call, negated: bool) -> Constraint:
    """``all(c in "ACGT" for c in value)``, ``all(c not in value for c in ";|")`` and ``not any(...)``."""
    found = _comprehension(node.args[0]) if len(node.args) == 1 else None
    if found is None:
        return ANY
    element, generator = found
    name = generator.target.id if isinstance(generator.target, ast.Name) else ""
    if not (isinstance(element, ast.Compare) and len(element.ops) == 1):
        return ANY
    left, op, right = element.left, element.ops[0], element.comparators[0]
    is_all = isinstance(node.func, ast.Name) and node.func.id == "all" and not negated
    is_none = isinstance(node.func, ast.Name) and node.func.id == "any" and negated
    over = _text(generator.iter)
    if isinstance(left, ast.Name) and left.id == name and _is_value(right) and over is not None:
        # for c in "<characters>": c (not) in value
        if (is_all and isinstance(op, ast.NotIn)) or (is_none and isinstance(op, ast.In)):
            return _without(over)
    listed = _text(right)
    if isinstance(left, ast.Name) and left.id == name and _is_value(generator.iter) and listed is not None:
        # for c in value: c (not) in "<characters>"
        if is_all and isinstance(op, ast.In):
            return Constraint(probe(listed), probe(listed))
        if (is_all and isinstance(op, ast.NotIn)) or (is_none and isinstance(op, ast.In)):
            return _without(listed)
    return ANY


def _call(node: ast.Call, negated: bool) -> Constraint:
    func = node.func
    if isinstance(func, ast.Name) and func.id in ("all", "any"):
        return _quantified(node, negated)
    if isinstance(func, ast.Attribute):
        if func.attr == "startswith" and _is_value(func.value) and len(node.args) == 1 and negated:
            prefixes = _texts(node.args[0])
            if prefixes is not None:
                return Constraint(PROBE, PROBE - probe("".join(p for p in prefixes if len(p) == 1)))
        if func.attr in _PREDICATES and not node.args and not negated:
            removed = _subject(func.value)
            if removed is not None:
                return Constraint(_PREDICATES[func.attr], _PREDICATES[func.attr]).allowing(removed)
        if (
            func.attr == "match"
            and isinstance(func.value, ast.Name)
            and func.value.id == "re"
            and len(node.args) == 2
            and _is_value(node.args[1])
            and not negated
        ):
            pattern = _text(node.args[0])
            if pattern is not None:
                return regex_constraint(pattern)
    return ANY


def _expression(node: ast.AST, negated: bool = False) -> Constraint:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _expression(node.operand, not negated)
    if isinstance(node, ast.BoolOp):
        parts = [_expression(value, negated) for value in node.values]
        # De Morgan: a negated `or` holds when every operand is false.
        conjunction = isinstance(node.op, ast.And) != negated
        out = parts[0]
        for part in parts[1:]:
            out = out.both(part) if conjunction else out.either(part)
        return out
    if _is_value(node):
        # `value` is true for any text; `not value` only for the empty one.
        return EMPTY if negated else ANY
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left, op, right = node.left, node.ops[0], node.comparators[0]
        if isinstance(op, (ast.NotIn, ast.In)):
            absent = isinstance(op, ast.NotIn) != negated
            return _absent(left, right) if absent else _present(left, right)
        equal = (
            isinstance(op, (ast.Eq, ast.Is)) != negated
            if isinstance(op, (ast.Eq, ast.Is, ast.NotEq, ast.IsNot))
            else None
        )
        if equal is True and _is_value(left):
            text = _text(right)
            if text is not None:
                return Constraint(probe(text), probe(text[:1]))
            if isinstance(right, ast.Constant) and right.value is None:
                return EMPTY
        if equal is False and _is_first_character(left):
            text = _text(right)
            if text is not None and len(text) == 1:
                return Constraint(PROBE, PROBE - probe(text))
        return ANY
    if isinstance(node, ast.Call):
        return _call(node, negated)
    return ANY


def expression_constraint(expression: str) -> Constraint:
    """What a value accepted by an ``expression`` validator may contain."""
    try:
        with warnings.catch_warnings():
            # An expression may hold a regex with escapes Python warns about; it is only read here.
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(expression.strip(), mode="eval")
    except (SyntaxError, ValueError):
        return ANY
    return _expression(tree.body)


def regex_constraint(expression: str) -> Constraint:
    chars = regex_universe(expression)
    return Constraint(chars, regex_first(expression) if chars == PROBE else regex_first(expression) & chars)


def text_constraint(input_source: InputSource) -> Constraint:
    """What the validators of a text-like parameter leave of the submitted value."""
    constraint = ANY
    for validator in input_source.parse_validators():
        if isinstance(validator, RegexParameterValidatorModel) and not validator.negate:
            constraint = constraint.both(regex_constraint(validator.expression))
        elif isinstance(validator, ExpressionParameterValidatorModel) and not validator.negate:
            constraint = constraint.both(expression_constraint(validator.expression))
    return constraint
