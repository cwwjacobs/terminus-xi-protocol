"""Deterministic check implementations and their registry.

A check implementation is a pure function::

    def impl(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> list[Finding]

``inputs`` maps the contract's declared pointer roles to the resolved values.
Implementations must not perform I/O, consult a clock, or call a model.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator, Mapping, Sequence

from ..results import Finding

__all__ = [
    "CheckImpl",
    "CheckNotRegistered",
    "get",
    "is_builtin",
    "is_registered",
    "register",
    "registered_names",
    "temporary",
    "unregister",
]

CheckImpl = Callable[[Mapping[str, Any], Mapping[str, Any]], Sequence[Finding]]

_REGISTRY: dict[str, CheckImpl] = {}
_BUILTIN_NAMES: frozenset[str] = frozenset()


class CheckNotRegistered(KeyError):
    pass


def register(name: str, impl: CheckImpl, *, replace: bool = False) -> CheckImpl:
    if name in _REGISTRY and not replace:
        if _REGISTRY[name] is impl:
            return impl
        raise ValueError(f"check implementation already registered: {name!r}")
    _REGISTRY[name] = impl
    return impl


def get(name: str) -> CheckImpl:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise CheckNotRegistered(name) from None


def is_registered(name: str) -> bool:
    return name in _REGISTRY


def registered_names() -> list[str]:
    return sorted(_REGISTRY)


def is_builtin(name: str) -> bool:
    return name in _BUILTIN_NAMES


def unregister(name: str) -> None:
    """Remove one non-builtin registration. Builtins are frozen."""
    if name in _BUILTIN_NAMES:
        raise ValueError(f"builtin check implementation cannot be unregistered: {name!r}")
    _REGISTRY.pop(name, None)


@contextmanager
def temporary(name: str, impl: CheckImpl) -> Iterator[CheckImpl]:
    """Register an implementation for the duration of a block.

    Scoped so that removing a test double cannot take a consumer's registration
    with it: only ``name`` is touched, and any implementation it displaced is
    put back.
    """
    if name in _BUILTIN_NAMES:
        raise ValueError(f"builtin check implementation cannot be replaced: {name!r}")
    previous = _REGISTRY.get(name)
    _REGISTRY[name] = impl
    try:
        yield impl
    finally:
        if previous is None:
            _REGISTRY.pop(name, None)
        else:
            _REGISTRY[name] = previous


from . import builtin as _builtin  # noqa: E402  (registers builtin implementations)

_BUILTIN_NAMES = frozenset(_REGISTRY)
