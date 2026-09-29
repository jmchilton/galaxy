from typing import (
    Any,
    Literal,
)

from galaxy.schema.schema import Model

UnmetPreconditionKind = Literal["access"]


class UnmetPrecondition(Model):
    kind: UnmetPreconditionKind
    message: str
    details: dict[str, Any] = {}
    remedy_route: str | None = None
