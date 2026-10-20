"""Base model classes for tool utilities."""

from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
)


class ToolSourceBaseModel(BaseModel):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_collection_type(v: str) -> str:
    if len(v) == 0:
        raise ValueError("Invalid empty collection_type specified.")
    for level in v.split(":"):
        if level not in ("list", "paired", "paired_or_unpaired", "record", "sample_sheet"):
            raise ValueError(f"Invalid collection_type specified [{v}]")
    return v


def check_collection_type_prefix(v: str) -> str:
    _check_collection_type(v)
    for level in v.split(":"):
        if level in ("sample_sheet", "record"):
            raise ValueError(f"{level} is not allowed in type_prefix [{v}]")
    return v


CollectionType = Annotated[str | None, AfterValidator(_check_collection_type)]
