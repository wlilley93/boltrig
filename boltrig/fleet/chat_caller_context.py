"""Rendering a caller's context into a turn (A2).

The CONTRACT is ``boltrig/models/chat_context.py``; this is what a turn does
with it. Split because models may import only models and this needs the
untrusted-text envelope.

WHICH BAND EACH PIECE LANDS IN IS THE WHOLE DESIGN. A page title or an entity
label is chosen by whoever named the record, which on a shared system need not
be this caller, so both go through ``wrap_untrusted`` exactly as an
attachment's text does. A mode does not, because it is a closed enum: the
caller picks a name the kernel wrote and never supplies the prose.
"""

from __future__ import annotations

from typing import Any

from boltrig.models.chat_context import (
    CHAT_MODE_PLAN,
    MAX_REFERENCE_TEXT,
    CallerContext,
    normalised_mode,
)
from boltrig.text_envelope import wrap_untrusted

_PLAN_DIRECTIVE = (
    "The person has asked for a PLAN. Set out the steps you would take and what "
    "each would change, and stop there. Do not perform them."
)


def mode_directive(mode: str) -> str:
    """The trusted-band instruction for a mode, if it has one."""
    return _PLAN_DIRECTIVE if normalised_mode(mode) == CHAT_MODE_PLAN else ""


def _clip(value: Any) -> str:
    return str(value or "")[:MAX_REFERENCE_TEXT]


def _describe(item: Any) -> str | None:
    """One reference as ``type:id`` plus its label, or None if unusable."""
    if not isinstance(item, dict):
        return None
    kind, ident = _clip(item.get("type")), _clip(item.get("id"))
    if not kind or not ident:
        return None
    label = _clip(item.get("label"))
    return f"{kind}:{ident}" + (f" ({label})" if label else "")


def caller_context_supplement(page_context: Any, references: Any) -> str:
    """The untrusted-band block describing where the caller was and what they cited.

    Empty string when there is nothing to say, so a turn without context is
    byte-identical to one sent before this existed.
    """
    parts: list[str] = []
    if isinstance(page_context, dict):
        described = _describe(page_context)
        if described:
            parts.append(
                wrap_untrusted(
                    "page-context",
                    "host",
                    "The person is looking at " + described + ". This is where "
                    "they are, not permission to read it.",
                )
            )
    named = [d for d in (_describe(i) for i in (references or [])) if d]
    if named:
        parts.append(
            wrap_untrusted(
                "references",
                "host",
                "The person referred to: " + "; ".join(named) + ". Fetch anything "
                "you need through a tool; being named here grants nothing.",
            )
        )
    return "".join(parts)


def rendered_context(caller_context: CallerContext | None) -> tuple[str, str]:
    """``(trusted directive, untrusted supplement)`` for a turn, or two empties."""
    if caller_context is None:
        return "", ""
    return (
        mode_directive(caller_context.mode),
        caller_context_supplement(
            caller_context.page_context, list(caller_context.references)
        ),
    )
