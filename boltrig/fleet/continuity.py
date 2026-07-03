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
from typing import Any

from boltrig.models import ConversationMessage, ConversationSummary, MessageRole

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


# --------------------------------------------------------------------------- #
# Long-conversation compaction (append-only DERIVED summaries).
#
# Past a threshold the composer replaces the OLDER verbatim turns with a single
# cheap derived summary, keeping only a recent verbatim tail:
#
#     [summary of older turns] + [recent tail of verbatim turns]
#
# The summary is DERIVED data (a ConversationSummary row), never a mutation of the
# frozen message record ([2026] VJS-COUNTY 4). Two properties are load-bearing and
# tested:
#
# * **Prefix stability between compactions.** With a fixed summary, the composed
#   task is ``render_summary_block(summary) + render_transcript(tail)``. The summary
#   block is byte-stable and the tail only ever grows by APPENDING (superseded
#   drops aside), so turn N's task stays a byte-prefix of turn N+1's - the gateway
#   prompt cache keeps hitting (SEC-46). A new compaction shifts the boundary and
#   is a deliberate cache-cold event (the "until the next compaction" caveat).
# * **Superseded stays excluded.** Both the summarised older set AND the verbatim
#   tail are drawn from the already-superseded-filtered ``live`` set, so a
#   regenerated-away reply is neither summarised into nor present in the tail.
# --------------------------------------------------------------------------- #

# The deterministic digest truncates each older turn to this many characters, so a
# summary of N turns is bounded regardless of how long the turns were.
_SUMMARY_SNIPPET_CHARS = 200


def compaction_enabled(config: Any) -> bool:
    """Compaction is config-as-data (P7). It engages only when the threshold is a
    positive count, a positive recent-tail is kept, and the tail is strictly
    smaller than the threshold (else there is nothing to compact). A zero/None
    config (or a config without the knobs) disables it, restoring full-verbatim
    continuity exactly."""
    if config is None:
        return False
    threshold = int(getattr(config, "compaction_threshold", 0) or 0)
    keep_recent = int(getattr(config, "compaction_keep_recent", 0) or 0)
    return threshold > 0 and keep_recent > 0 and keep_recent < threshold


def summarize_messages(messages: list[ConversationMessage]) -> str:
    """The DETERMINISTIC, offline summariser (no model) - the always-present
    fallback, mirroring how the department head keeps a deterministic decomposition
    fallback (P9). It produces a stable role-tagged digest: one bounded line per
    covered turn, whitespace-collapsed and truncated. Deterministic means the same
    covered set always yields the same summary text, which is exactly what keeps the
    summary block byte-stable (prefix stability) and the whole feature testable with
    no model wired.

    The caller passes the already-superseded-filtered older turns; this does not
    re-read the store or add authority - it only compresses text it was handed."""
    lines: list[str] = []
    for m in messages:
        label = _ROLE_LABEL.get(m.role, str(getattr(m.role, "value", m.role)))
        snippet = " ".join((m.content or "").split())
        if len(snippet) > _SUMMARY_SNIPPET_CHARS:
            snippet = snippet[: _SUMMARY_SNIPPET_CHARS - 3].rstrip() + "..."
        lines.append(f"- {label}: {snippet}")
    return "\n".join(lines)


def render_summary_block(summary_text: str) -> str:
    """Render the derived summary as a fixed, content-stable frame. The summary is
    derived from untrusted conversation bodies, so it is wrapped in a typed
    ``wrap_untrusted`` envelope (M1 / SEC-72) - it re-enters the task as DATA, never
    instructions. The frame is deterministic, so a fixed ``summary_text`` renders to
    byte-identical output across turns (prefix stability)."""
    body = wrap_untrusted("conversation_summary", "prior_turns", summary_text)
    return f"Summary of earlier conversation:\n{body}\n\n"


def plan_compaction(
    live: list[ConversationMessage], config: Any
) -> list[ConversationMessage] | None:
    """The OLDER turns a fresh compaction should summarise, or None when a fresh
    compaction is not due. ``live`` must already be superseded-filtered. A fresh
    compaction covers everything except the most recent ``keep_recent`` turns, and
    is due only once the live count reaches the threshold. The chat orchestration
    additionally gates re-compaction on the tail having regrown (so it does not
    rewrite an equivalent summary every turn)."""
    if not compaction_enabled(config):
        return None
    keep_recent = int(config.compaction_keep_recent)
    if len(live) < int(config.compaction_threshold):
        return None
    older = live[:-keep_recent]
    return older or None


def compose_turn_task(
    messages: list[ConversationMessage],
    current_message: str,
    *,
    summary: ConversationSummary | None = None,
    config: Any = None,
) -> str:
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
    guarantee, SEC-46) - a superseded message is dropped, never edited in place.

    Compaction (append-only derived summaries): when a ``summary`` exists and the
    live count has crossed the configured threshold, the OLDER turns it covers are
    replaced by the derived summary block and only the recent verbatim tail after
    the summary's boundary is rendered. BELOW the threshold (or with no summary /
    compaction disabled) the behaviour is UNCHANGED - the full verbatim history.
    The summary block is byte-stable and the tail appends, so the composed task
    stays prefix-stable across turns until the next compaction."""
    live = [m for m in messages if getattr(m, "superseded_by", None) is None]
    if not live:
        return current_message
    if (
        summary is not None
        and compaction_enabled(config)
        and len(live) >= int(config.compaction_threshold)
    ):
        # Split at the summary's boundary by id (robust to the tail's superseded
        # churn). If the boundary message is no longer live (an edge a supersede at
        # the boundary could create), idx is None and we fall through to the full
        # verbatim render - fail-safe, never a crash or a dropped turn.
        idx = next(
            (i for i, m in enumerate(live) if m.id == summary.up_to_message_id), None
        )
        if idx is not None and idx < len(live) - 1:
            tail = live[idx + 1 :]
            return render_summary_block(summary.summary) + render_transcript(tail)
    return render_transcript(live)
