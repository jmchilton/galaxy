"""Pydantic setup used only by the ORM metadata fallback."""

from pydantic import (
    BaseModel,
    RootModel,
)


def defer_pydantic_model_builds():
    BaseModel.model_config["defer_build"] = True
    RootModel.model_config["defer_build"] = True


__all__ = ("defer_pydantic_model_builds",)
