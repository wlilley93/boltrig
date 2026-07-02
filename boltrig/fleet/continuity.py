"""Cross-turn conversation continuity for the pi lane (Round Six, gap 3.1).

The chat turn path persists the incoming user message, then drives the turn with
only that single message: prior turns were never composed into the prompt handed
to ``spawn()``, so a continuing conversation ran with no memory of itself beyond
whatever the new message text happened to restate.

This module closes that gap by rendering the already-persisted, owner-scoped
conversation transcript into the task string before the spawn. Two properties are
load-bearing and are both proven by tests:

* **Deterministic + append-only (prefix stability).** The transcript is a plain
  per-message concatenation, so turn N+1's rendering is exactly turn N's
  rendering with the previous reply and the new user message appended. Turn N's
  task is a prefix of turn N+1's task. That is what lets an upstream model
  gateway keep a warm prompt cache across the turns of one conversation (gap 3.2,
  ``model_gateway``).

* **No new authority (SEC-27 preserved).** It reads only persisted conversation
  *text* through the caller's tenant- and conversation-scoped store read. It
  introduces no credential, no tool, and no cross-conversation read - the loader
  is handed exactly one conversation's messages (SEC-49).

It lives in the fleet layer and imports only models; the kernel and the pi
sidecar import nothing from it (SEC-28).
"""

from __future__ import annotations

import os

from boltrig.models import ConversationMessage, MessageRole

from .prompt_stack import wrap_untrusted

_ROLE_LABEL = {
    MessageRole.USER: "User",
    MessageRole.ASSISTANT: "Assistant",
    MessageRole.TOOL: "Tool",
    MessageRole.SYSTEM: "System",
}


def continuity_enabled() -> bool:
    """Continuity is config-as-data (P7): on by default, ``BOLTRIG_CONTINUITY=0``
    restores the prior single-message behaviour exactly."""
    return os.environ.get("BOLTRIG_CONTINUITY", "1") != "0"


def _render_message(message: ConversationMessage) -> str:
    label = _ROLE_LABEL.get(message.role, str(getattr(message.role, "value", message.role)))
    # A fixed, content-stable frame per message. The label ("User:" / "Assistant:")
    # is trusted framing we add; the message *body* is untrusted conversation data,
    # so it is wrapped in a typed envelope (M1 / SEC-72) - a prior turn cannot smuggle
    # instructions into a later turn's prompt. Wrapping per message keeps the render
    # deterministic and append-only (prefix stable), so SEC-46 still holds. Empty
    # content (e.g. a turn that produced only tool/HITL events) still renders
    # deterministically as an empty envelope.
    body = wrap_untrusted("conversation_turn", label.lower(), message.content or "")
    return f"{label}: {body}\n\n"


def render_transcript(messages: list[ConversationMessage]) -> str:
    """Render an ordered message list as an append-only transcript.

    ``render_transcript(messages)`` is, by construction, a prefix of
    ``render_transcript(messages + more)`` - the guarantee the gateway cache
    relies on. The messages must already be ordered oldest-first (the store's
    ``list_messages`` returns them ``created_at ASC``)."""
    return "".join(_render_message(m) for m in messages)


def compose_turn_task(messages: list[ConversationMessage], current_message: str) -> str:
    """The task string for ``spawn()``.

    ``messages`` is the conversation's full ordered transcript, which already
    ends with the just-persisted current user turn, so rendering it yields the
    whole context terminating in the current message. When there is no history
    (continuity off, or a store that did not persist), fall back to the bare
    current message so behaviour is identical to the pre-continuity path.

    Superseded messages are FILTERED before rendering ([2026] VJS-COUNTY 4, D4): a
    reply that a regenerate replaced (``superseded_by`` set) is never composed into
    a prompt, so it can neither be presented as live nor re-enter the model context.
    Because a supersede only ever replaces the LAST assistant reply with a fresh one
    APPENDED at the end, the surviving (non-superseded) set stays append-structured,
    so ``render_transcript`` remains prefix-stable over it (the gateway-cache
    guarantee, SEC-46) - a superseded message is dropped, never edited in place."""
    live = [m for m in messages if getattr(m, "superseded_by", None) is None]
    if not live:
        return current_message
    return render_transcript(live)
