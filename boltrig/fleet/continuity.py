"""Cross-turn conversation continuity (Round Six, gap 3.1).

This module said "for the pi lane" until 2026-08-02. That lane was retired by decision
0020 and the docstring outlived it; composition in fact happens BEFORE a runtime is
selected (`chat_turn_execution._turn_task`, then `spawner.spawn`), and the `Runtime`
protocol takes a flat prompt string, so every lane receives the identical text.

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

* **No new authority.** It reads only rows the caller's tenant- and conversation-scoped
  store read already returned. It introduces no credential, no tool, and no
  cross-conversation read - the loader is handed exactly one conversation's messages
  (SEC-49). This cited SEC-27 until 2026-08-02; SEC-27 is a Round Two invariant about no
  verb CREDENTIAL reaching a runtime, which a value-free render does not engage, so the
  citation claimed slightly more than the invariant says.

* **A closed allowlist at THIS boundary, never inherited.** Persistence is not
  prompt-eligibility ([2026] VJS-CC-BOLTRIG-CONTINUITY-TOOL-WORK-001). Message *text*
  crosses, plus a bounded tool-work line built from an enumerated set of fields defined
  below in this module. It is deliberately NOT derived from `chat_event_projection`, which
  is a browser-safety projection and bounds nothing here.

It lives in the fleet layer and imports only models; the kernel and the pi
sidecar import nothing from it (SEC-28).
"""

from __future__ import annotations

import os
import re
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


# --------------------------------------------------------------------------- #
# The tool-work projection ([2026] VJS-CC-BOLTRIG-CONTINUITY-TOOL-WORK-001, D1)
#
# THE RATIO THIS IMPLEMENTS: persistence is not prompt-eligibility. A datum's presence on
# `message.events` confers no entitlement to enter a prompt. The prompt is a distinct
# boundary with a distinct reader, so what may cross it is enumerated HERE, in the module
# that composes the prompt, and is NOT inherited from `chat_event_projection`.
#
# WHY NOT INHERITED, measured at the sitting rather than assumed. That module is a
# BROWSER-safety projection and does not bound this at all: its cardinality cap is not in it
# (MAX_PARAM_KEYS lives two modules upstream in `run_event_projection`), `_summarise_output`
# has no cap whatever, no key-name length is bounded anywhere in the chain, the same events
# list carries `text_delta.delta` (the whole reply), `subagent.task` (unbounded) and
# `hitl.question` as free text, and `held_write_resume` writes frames straight onto the row
# without passing through it. "Structured, therefore safe" is not an argument.
#
# `scripts/check_continuity_projection.py` holds these four sets to exactly what the order
# fixed, so widening one is a gate failure and not a code review question.
# --------------------------------------------------------------------------- #

_TOOL_WORK_FRAME_TYPES = frozenset({"tool_call", "tool_result"})
# RENDERED: reaches the model. `tool` is admitted as a NAME whose provenance is a registry
# (a first-party verb, or a publisher's tool id at MCP import) rather than the conversation.
# Its range is NOT closed at build time, so it is capped and charset-normalised. That is a
# RECORDED LIMIT, not a safety proof (order D10).
_TOOL_WORK_RENDERED_FIELDS = frozenset({"tool", "status"})
# READ but never rendered. An identifier may be read to derive an admitted fact and must not
# be emitted (order corollary (d)): `call_id` joins a call to its result inside this module
# and the join alone is what reaches the prompt.
_TOOL_WORK_READ_FIELDS = frozenset({"type", "tool", "status", "call_id"})
# Closed at build time. Anything else - including a missing or non-string status - renders
# as the fixed token below. Enforced by
# tests/security/test_continuity_carries_text_only.py::test_a_status_outside_the_closed_allowlist_renders_unknown,
# which seeds a credential-shaped status and a nested object, and carries the control that a
# status INSIDE the allowlist still crosses as itself.
_TOOL_WORK_STATUSES = frozenset({"ok", "error", "degraded", "pending_human"})
_TOOL_WORK_UNKNOWN_STATUS = "unknown"
_TOOL_WORK_NAME_SAFE = re.compile(r"[^A-Za-z0-9._:-]")


def _tool_work_caps(config: Any = None) -> tuple[int, int]:
    """The two caps, as data. Never call-site constants (order, forbidden list)."""
    chat = getattr(config, "chat", config)
    name_chars = getattr(chat, "continuity_tool_name_chars", None)
    pairs = getattr(chat, "continuity_tool_pairs_per_turn", None)
    return (
        int(name_chars) if isinstance(name_chars, int) and name_chars > 0 else 64,
        int(pairs) if isinstance(pairs, int) and pairs > 0 else 10,
    )


def _tool_work_line(message: ConversationMessage, config: Any = None) -> str | None:
    """A bounded, value-free statement of what this turn's tools did, or ``None``.

    ``None`` whenever the row carries no admitted frame, so a turn without tool work renders
    BYTE-IDENTICALLY to how it rendered before this existed. That is the order's one
    exception and it is what keeps every prior content-only assertion true on its merits.
    """
    name_chars, max_pairs = _tool_work_caps(config)
    calls: list[tuple[str, str]] = []  # (call_id, tool)
    statuses: dict[str, str] = {}
    for event in message.events or []:
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind not in _TOOL_WORK_FRAME_TYPES:
            # Every other frame type is neither read nor rendered. `subagent`, `hitl`,
            # `question` and `text_delta` all carry free text on this same list.
            continue
        call_id = event.get("call_id")
        call_id = call_id if isinstance(call_id, str) else ""
        if kind == "tool_call":
            raw = event.get("tool")
            name = raw if isinstance(raw, str) and raw else "unnamed"
            name = _TOOL_WORK_NAME_SAFE.sub("_", name)[:name_chars]
            calls.append((call_id, name))
        else:
            status = event.get("status")
            statuses[call_id] = (
                status if isinstance(status, str) and status in _TOOL_WORK_STATUSES
                else _TOOL_WORK_UNKNOWN_STATUS
            )
    if not calls:
        return None

    # The TRUE count, exact and never capped, however many pairs are elided below. A count
    # that saturates at the cap is a number that has stopped being a fact (schema-ledger D7).
    total = len(calls)
    tally: dict[tuple[str, str], int] = {}
    for call_id, name in calls:
        key = (name, statuses.get(call_id, _TOOL_WORK_UNKNOWN_STATUS))
        tally[key] = tally.get(key, 0) + 1
    ordered = sorted(tally.items())
    shown, elided = ordered[:max_pairs], len(ordered) - max_pairs
    parts = [f"{n} {s}" + (f" x{c}" if c > 1 else "") for (n, s), c in shown]
    if elided > 0:
        parts.append(f"+{elided} more")
    return f"{total} tool call(s): " + "; ".join(parts)


def _render_message(message: ConversationMessage, config: Any = None) -> str:
    label = _message_label(message)
    # A fixed, content-stable frame per message. The label ("User:" / "Assistant:")
    # is trusted framing we add; the message *body* is untrusted conversation data,
    # so it is wrapped in a typed envelope (M1 / SEC-72) - a prior turn cannot smuggle
    # instructions into a later turn's prompt. Wrapping per message keeps the render
    # deterministic and append-only (prefix stable), so SEC-46 still holds.
    body = wrap_untrusted("conversation_turn", label.lower(), message.content or "")
    # The tool-work line rides in its OWN envelope, because a tool name at MCP import is
    # chosen by a third-party publisher and is therefore untrusted payload, not our framing.
    # Charset normalisation above is a SECOND line behind this one, never a substitute:
    # which of the two is load-bearing is proved by the D8 test, not asserted here.
    work = _tool_work_line(message, config)
    if work is not None:
        body += " " + wrap_untrusted("tool_work", "prior_turn", work)
    return f"{label}: {body}\n\n"


def _message_label(message: ConversationMessage) -> str:
    """Trusted framing that preserves who handled each historical turn.

    Agent addresses are registry-validated routing identifiers. They remain
    framing rather than message content, so a newly selected peer never inherits
    another peer's old assistant prose as though it authored it.
    """
    role = _ROLE_LABEL.get(message.role, str(getattr(message.role, "value", message.role)))
    if message.role == MessageRole.USER and message.recipient_agent_address:
        return f"{role} to {message.recipient_agent_address}"
    if message.author_agent_address:
        return f"{role} by {message.author_agent_address}"
    return role


def render_transcript(messages: list[ConversationMessage], config: Any = None) -> str:
    """Render an ordered message list as an append-only transcript.

    ``render_transcript(messages)`` is, by construction, a prefix of
    ``render_transcript(messages + more)`` - the guarantee the gateway cache
    relies on. The messages must already be ordered oldest-first (the store's
    ``list_messages`` returns them ``created_at ASC``)."""
    return "".join(_render_message(m, config) for m in messages)


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


def summarize_messages(messages: list[ConversationMessage], config: Any = None) -> str:
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
        label = _message_label(m)
        snippet = " ".join((m.content or "").split())
        if len(snippet) > _SUMMARY_SNIPPET_CHARS:
            snippet = snippet[: _SUMMARY_SNIPPET_CHARS - 3].rstrip() + "..."
        # D3: the tool-work line is carried across the compaction boundary, and the
        # snippet truncation above applies to the CONTENT ONLY and never to it. Without
        # this a turn's tool work would silently evaporate the moment the turn aged past
        # the threshold - the line would be present for a while and then quietly stop
        # being true, which is the same false-silence defect one boundary further on.
        work = _tool_work_line(m, config)
        lines.append(f"- {label}: {snippet}" + (f" [{work}]" if work else ""))
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
            return render_summary_block(summary.summary) + render_transcript(tail, config)
    return render_transcript(live, config)
