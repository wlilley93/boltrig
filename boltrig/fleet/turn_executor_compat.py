"""Compatibility call adapter for injected chat turn executors."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

# Newer-than-legacy optional kwargs: passed through when the injected executor
# declares them, dropped for a legacy signature that predates them (so an older
# executor never chokes on an unexpected keyword). ``on_behalf_bearer`` is the
# permission-parity passthrough (2026); scope/workspace_id predate it.
_OPTIONAL_KWARGS = frozenset({"scope", "workspace_id", "on_behalf_bearer"})
_KEYWORD_KINDS = frozenset(
    {
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }
)


def _supported_optional_kwargs(executor: Callable[..., Awaitable[Any]]) -> frozenset[str]:
    """Return the optional kwargs an injected executor can accept safely."""
    try:
        parameters = inspect.signature(executor).parameters
    except (TypeError, ValueError):
        return _OPTIONAL_KWARGS
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return _OPTIONAL_KWARGS
    return frozenset(
        name
        for name in _OPTIONAL_KWARGS
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
    supported = _supported_optional_kwargs(executor)
    for name in _OPTIONAL_KWARGS - supported:
        call_kwargs.pop(name, None)
    return await executor(**call_kwargs)
