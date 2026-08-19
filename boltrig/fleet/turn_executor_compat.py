"""Compatibility call adapter for injected chat turn executors."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

# Newer-than-legacy optional kwargs: passed through when the injected executor
# declares them, dropped for a legacy signature that predates them (so an older
# executor never chokes on an unexpected keyword). ``on_behalf_bearer`` is the
# permission-parity passthrough (2026); scope/workspace_id predate it. ``origin``
# is the channel label (2026-07-28, fleet/chat_origin) and was added here only
# after it was added to the CALL: passing it unconditionally raised TypeError
# inside every legacy-signature executor, which _safe_exec degrades rather than
# raises, so the turn answered "(turn error: TypeError)" and nothing said why.
# Anything threaded into the executor call belongs in this set the same day.
# ``caller_context`` (2026-08-19, fleet/chat_caller_context) is the host's page
# and @-references. It was added to the CALL first and not here, and the file's
# own warning above described what happened next exactly: every legacy-signature
# executor raised TypeError, _safe_exec degraded instead of raising, and the
# integration chat tests failed with no statement of why.
_OPTIONAL_KWARGS = frozenset({
    "scope", "workspace_id", "on_behalf_bearer", "origin", "model_profile_id",
    "model_choice_id", "caller_context",
})
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
