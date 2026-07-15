"""Compatibility call adapter for injected chat turn executors."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

_SCOPE_KWARGS = frozenset({"scope", "workspace_id"})
_KEYWORD_KINDS = frozenset(
    {
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }
)


def _supported_scope_kwargs(executor: Callable[..., Awaitable[Any]]) -> frozenset[str]:
    """Return new scope kwargs an injected executor can accept safely."""
    try:
        parameters = inspect.signature(executor).parameters
    except (TypeError, ValueError):
        return _SCOPE_KWARGS
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return _SCOPE_KWARGS
    return frozenset(
        name
        for name in _SCOPE_KWARGS
        if (parameter := parameters.get(name)) is not None and parameter.kind in _KEYWORD_KINDS
    )


async def invoke_turn_executor(
    executor: Callable[..., Awaitable[Any]] | None,
    *,
    relay: Any,
    kwargs: dict[str, Any],
) -> Any:
    """Call current executors with scope and omit it for legacy signatures."""
    if executor is None:
        raise RuntimeError("turn executor is unavailable")
    call_kwargs = {"relay": relay, **kwargs}
    supported = _supported_scope_kwargs(executor)
    for name in _SCOPE_KWARGS - supported:
        call_kwargs.pop(name, None)
    return await executor(**call_kwargs)
