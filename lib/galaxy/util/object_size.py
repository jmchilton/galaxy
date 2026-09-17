"""Helpers for estimating the in-memory size of nested values."""

from collections import deque
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from itertools import chain
from sys import getsizeof
from typing import Any


def total_size(value: Any, handlers: Mapping[type, Callable[[Any], Iterable[Any]]] | None = None) -> int:
    """Return the approximate memory footprint of a nested Python value."""
    handlers = handlers or {}

    def dict_handler(mapping):
        return chain.from_iterable(mapping.items())

    all_handlers: dict[type, Callable[[Any], Iterable[Any]]] = {
        tuple: iter,
        list: iter,
        deque: iter,
        dict: dict_handler,
        set: iter,
        frozenset: iter,
    }
    all_handlers.update(handlers)
    seen = set()
    default_size = getsizeof(0)

    def sizeof(item):
        if id(item) in seen:
            return 0
        seen.add(id(item))
        size = getsizeof(item, default_size)
        for value_type, handler in all_handlers.items():
            if isinstance(item, value_type):
                size += sum(map(sizeof, handler(item)))
                break
        return size

    return sizeof(value)


__all__ = ("total_size",)
