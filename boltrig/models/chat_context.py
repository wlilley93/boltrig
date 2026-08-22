"""Where the caller was when they sent a chat turn (A2).

A host application's chat is not a bare message box: Opbox's is attached to a
matter, a document or a table, and a person can @-mention an entity in it.
Boltrig's chat carried only ``{message, conversation_id}``, so moving that chat
here would have dropped page awareness, plan mode and @-mentions.

THE DATA LIVES HERE AND THE RENDERING DOES NOT. ``boltrig.models`` may import
only ``boltrig.models`` (the architecture gate's innermost layer), and turning
this into prompt text needs the untrusted-text envelope, which is outside. So
this module is the CONTRACT - what a caller may send and what survives
validation - and ``boltrig/fleet/chat_caller_context.py`` is what a turn does
with it. The split is also honest: the request body is the kernel's business,
composing a task is the fleet's.

A REFERENCE IS A POINTER, NEVER A GRANT. Naming ``matter:m-1`` says the person
was looking at it; it does not entitle the agent to read it. The agent still
fetches through a granted verb and the chokepoint still decides. If this could
confer reach, a caller could name any id and have it fetched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Modes the kernel understands. A CLOSED SET, which is what makes a mode safe
# to place in the trusted band: the caller picks a name the kernel wrote rather
# than supplying prose.
CHAT_MODE_CHAT = "chat"
CHAT_MODE_PLAN = "plan"
CHAT_MODES = (CHAT_MODE_CHAT, CHAT_MODE_PLAN)

# Bounds, because this is caller-supplied and lands in every turn's context. A
# reference list is a mention bar, not a bulk import.
MAX_REFERENCES = 25
MAX_REFERENCE_TEXT = 200


def normalised_mode(raw: Any) -> str:
    """A known mode, else plain chat. Never a reason to refuse a message."""
    return raw if raw in CHAT_MODES else CHAT_MODE_CHAT


@dataclass(frozen=True)
class CallerContext:
    """The three host-supplied fields, carried as ONE value.

    Bundled deliberately: a chat turn crosses six layers between the door and
    the task composer, and threading three parameters through each of them is
    three chances to drop one silently. It is also the honest shape - they are
    one idea, "where the caller was when they said this".
    """

    page_context: dict[str, Any] | None = None
    references: tuple[dict[str, Any], ...] = ()
    mode: str = CHAT_MODE_CHAT

    @classmethod
    def from_body(cls, body: Any) -> "CallerContext | None":
        """Build one from a chat request body, or None if it carried nothing."""
        return cls.from_request(
            getattr(body, "page_context", None),
            getattr(body, "references", None),
            getattr(body, "mode", None),
        )

    @classmethod
    def from_request(
        cls, page_context: Any, references: Any, mode: Any
    ) -> "CallerContext | None":
        """Build one, or None when the caller sent nothing.

        None means "byte-identical to a turn sent before this existed", which is
        what keeps every current caller unaffected.
        """
        # Capped HERE, at the boundary, not only where it renders. A value that
        # holds 200 references and shows 25 is a value whose other readers
        # disagree with the one that clips.
        refs = tuple(r for r in (references or []) if isinstance(r, dict))[:MAX_REFERENCES]
        resolved = normalised_mode(mode)
        if not isinstance(page_context, dict) and not refs and resolved == CHAT_MODE_CHAT:
            return None
        return cls(
            page_context=page_context if isinstance(page_context, dict) else None,
            references=refs,
            mode=resolved,
        )
