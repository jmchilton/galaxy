"""Type utilities for building pydantic models for tool parameters.

Lots of mypy exceptions in here - this code is all well tested and the exceptions
are fine otherwise because we're using the typing system to interact with pydantic
and build runtime models not to use mypy to type check static code.
"""

from typing import (
    cast,
    List,
    Optional,
    Type,
    Union,
)


def optional_if_needed(type: Type, is_optional: bool) -> Type:
    return_type: Type = type
    if is_optional:
        return_type = Optional[type]  # type: ignore[assignment]
    return return_type


def union_type(args: List[Type]) -> Type:
    return Union[tuple(args)]  # type: ignore[return-value]


def list_type(arg: Type) -> Type:
    return List[arg]  # type: ignore[valid-type]


def cast_as_type(arg) -> Type:
    return cast(Type, arg)
