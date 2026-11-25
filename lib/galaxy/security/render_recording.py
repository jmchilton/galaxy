"""Record the strings a template reads from objects whose values Galaxy does not sanitize.

While a tool's templates render inside :func:`recording`, the raw objects a template can reach
(``$input.unsanitized``, ``$x.unsanitized`` of a sanitized value, the user object of a tool that turns
the sanitizer off) are handed out as views: every attribute, item, element and call result is a view
too, and every string a view hands out is recorded with the path it was read by. The tool security
review checks the recorded strings once the templates have rendered, before the job runs. Outside
:func:`recording` the raw objects are handed out as they are.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import (
    dataclass,
    field,
)
from numbers import Number
from typing import (
    Any,
    Iterator,
    Optional,
)

# Where a recorded string comes from.
MODEL = "model"  # the dataset model behind $input.unsanitized
UNSANITIZED = "unsanitized"  # the object behind a sanitized value's .unsanitized
USER = "user"  # the user object of a tool that turns the sanitizer off


@dataclass(frozen=True)
class Read:
    origin: str
    # The attributes, items ("[key]"), elements ("[]") and calls ("()") the string was read by.
    path: tuple[str, ...]
    value: str


@dataclass
class Recording:
    reads: list[Read] = field(default_factory=list)


_ACTIVE: ContextVar[Optional[Recording]] = ContextVar("galaxy_render_recording", default=None)


@contextmanager
def recording() -> Iterator[Recording]:
    """Record what templates read from raw objects until the block ends."""
    active = Recording()
    token = _ACTIVE.set(active)
    try:
        yield active
    finally:
        _ACTIVE.reset(token)


def recorded_view(value: Any, origin: str, path: tuple[str, ...] = ()) -> Any:
    """``value`` as a template may read it: a recording view while :func:`recording` is active."""
    active = _ACTIVE.get()
    if active is None:
        return value
    return _view(value, active, origin, path)


def _view(value: Any, active: Recording, origin: str, path: tuple[str, ...]) -> Any:
    if isinstance(value, _View):
        return value
    if isinstance(value, str):
        active.reads.append(Read(origin, path, str(value)))
        return value
    if isinstance(value, (bytes, bytearray)):
        active.reads.append(Read(origin, path, bytes(value).decode("utf-8", "replace")))
        return value
    if value is None or isinstance(value, (bool, Number)):
        return value
    view_class = _CallableView if callable(value) else _View
    return view_class(value, active, origin, path)


def _unwrap(value: Any) -> Any:
    return object.__getattribute__(value, "_value") if isinstance(value, _View) else value


class _View:
    """A raw object that records every string read from it."""

    __slots__ = ("_value", "_active", "_origin", "_path")

    def __init__(self, value: Any, active: Recording, origin: str, path: tuple[str, ...]) -> None:
        object.__setattr__(self, "_value", value)
        object.__setattr__(self, "_active", active)
        object.__setattr__(self, "_origin", origin)
        object.__setattr__(self, "_path", path)

    def _then(self, value: Any, step: str) -> Any:
        return _view(value, self._active, self._origin, (*self._path, step))

    def _note(self, text: str, step: str) -> str:
        self._active.reads.append(Read(self._origin, (*self._path, step), text))
        return text

    def __getattr__(self, name: str) -> Any:
        return self._then(getattr(self._value, name), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._value, name, _unwrap(value))

    def __getitem__(self, key: Any) -> Any:
        # A model object that is not subscriptable raises TypeError: Cheetah then looks up an attribute.
        return self._then(self._value[_unwrap(key)], f"[{_unwrap(key)}]")

    def __iter__(self) -> Iterator[Any]:
        for item in self._value:
            yield self._then(item, "[]")

    def __len__(self) -> int:
        return len(self._value)

    def __bool__(self) -> bool:
        return bool(self._value)

    def __contains__(self, item: Any) -> bool:
        return _unwrap(item) in self._value

    def __eq__(self, other: Any) -> bool:
        return self._value == _unwrap(other)

    def __ne__(self, other: Any) -> bool:
        return self._value != _unwrap(other)

    def __lt__(self, other: Any) -> bool:
        return self._value < _unwrap(other)

    def __le__(self, other: Any) -> bool:
        return self._value <= _unwrap(other)

    def __gt__(self, other: Any) -> bool:
        return self._value > _unwrap(other)

    def __ge__(self, other: Any) -> bool:
        return self._value >= _unwrap(other)

    def __hash__(self) -> int:
        return hash(self._value)

    def __add__(self, other: Any) -> Any:
        return self._then(self._value + _unwrap(other), "+")

    def __radd__(self, other: Any) -> Any:
        return self._then(_unwrap(other) + self._value, "+")

    def __int__(self) -> int:
        return int(self._value)

    def __float__(self) -> float:
        return float(self._value)

    def __str__(self) -> str:
        return self._note(str(self._value), "str()")

    def __repr__(self) -> str:
        return self._note(repr(self._value), "repr()")

    def __format__(self, spec: str) -> str:
        return self._note(format(self._value, spec), "format()")

    def __dir__(self) -> list[str]:
        return dir(self._value)


class _CallableView(_View):
    __slots__ = ()

    def __call__(self, *args: Any, **kwds: Any) -> Any:
        unwrapped = {key: _unwrap(value) for key, value in kwds.items()}
        return self._then(self._value(*(_unwrap(a) for a in args), **unwrapped), "()")
