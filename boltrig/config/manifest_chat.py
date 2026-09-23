"""Fleet-manifest chat config (moved from config/manifest.py): the ChatConfig
dataclass, its DEFAULT_* caps and the ``_parse_chat``/``_parse_heartbeat``
parsers. Re-exported via ``manifest.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


DEFAULT_MAX_ATTACHMENTS = 8
DEFAULT_MAX_ATTACHMENT_BYTES = 256 * 1024  # 256 KiB per attachment (decoded)
DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES = 1024 * 1024  # 1 MiB total per turn (decoded)

# SSE keepalive (US-CHAT-11): a live chat stream emits a heartbeat frame every N
# seconds while a run is producing nothing, so a slow-but-alive run never trips a
# client idle-timeout. Conservative default (well under a typical 30-60s proxy /
# browser idle window) and it stops the moment the stream reaches a terminal
# event. 0 (or below) disables the keepalive entirely.
DEFAULT_HEARTBEAT_SECONDS = 15.0

# Long-conversation compaction (append-only derived summaries). Past
# ``compaction_threshold`` LIVE (non-superseded) messages the continuity composer
# sends [summary of older turns] + [the most recent ``compaction_keep_recent``
# verbatim turns] instead of the whole history, so a long thread stays cheap while
# a stable summary + a growing tail keep the gateway prompt-cache warm (prefix
# stability holds between compactions). Conservative NON-ZERO defaults: on by
# default, but 40 messages is well clear of a short thread, so ordinary
# conversations are never compacted. ``compaction_threshold = 0`` (or a keep-recent
# not strictly below the threshold) disables compaction entirely and restores the
# full-verbatim continuity behaviour exactly.
DEFAULT_COMPACTION_THRESHOLD = 40
DEFAULT_COMPACTION_KEEP_RECENT = 12

# Conversation list + search pagination (US-CONV-09). Conservative NON-ZERO code
# defaults: ``conversation_page_size`` is the page size used when a caller asks for
# none, and ``conversation_max_page_size`` is the HARD ceiling on how many rows any
# single page may return (a caller-supplied ``limit`` is clamped down to it, so an
# unbounded scan is impossible). Both are tighten-only ceilings like the attachment
# caps: a manifest may only LOWER them (a smaller, more conservative page), never
# grow a page past the code ceiling.
# Continuity tool-work projection caps ([2026] VJS-CC-BOLTRIG-CONTINUITY-TOOL-WORK-001
# D2). Tighten-only, like every cap above. The NAME cap is the schema-ledger D7 segment
# length; the PAIR cap is its per-row cap. The true tool-call COUNT is deliberately NOT
# capped and is not a knob: D7 requires the true count be reported however many pairs are
# elided, because a count that silently saturates is a number that stops being a fact.
DEFAULT_CONTINUITY_TOOL_NAME_CHARS = 64
DEFAULT_CONTINUITY_TOOL_PAIRS_PER_TURN = 10
DEFAULT_CONVERSATION_PAGE_SIZE = 25
DEFAULT_CONVERSATION_MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class ChatConfig:
    """Bare chat-turn authority ([2026] VJS-COUNTY 1): which skill set a bare
    chat turn spawns with, per caller role. The turn executor selects
    ``skills_by_role.get(role, default_skills)``; the shipped author-role
    mapping is carried by manifest.example.yaml (policy-as-data, P7), so these
    code defaults stay empty and a manifest-less boot is fail-closed.

    It also carries the inline-attachment caps ([2026] VJS-COUNTY 3): typed data
    with conservative NON-ZERO code defaults. ``_parse_chat`` lets a manifest only
    tighten each cap below its default, never loosen it, so the code default is a
    hard ceiling on how much a turn may carry."""

    # The capability that owns the direct conversational turn. Without this
    # pin, a skill-less chat makes every active capability eligible and the
    # generic cheapest-capability selector can pick an unrelated integration or
    # test script. None keeps manifest-less/test composition fail-closed and
    # backwards compatible; shipped manifests name the conversational worker.
    default_capability: str | None = None
    skills_by_role: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    default_skills: tuple[str, ...] = ()
    max_attachments: int = DEFAULT_MAX_ATTACHMENTS
    max_attachment_bytes: int = DEFAULT_MAX_ATTACHMENT_BYTES
    max_total_attachment_bytes: int = DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES
    # SSE keepalive interval in seconds (US-CHAT-11). Data, not a call-site
    # constant; a manifest may retune it. 0 or below disables the heartbeat.
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS
    # Long-conversation compaction knobs (append-only derived summaries). Config
    # -as-data (P7): the composer compacts past ``compaction_threshold`` live
    # messages, keeping ``compaction_keep_recent`` recent turns verbatim. 0 (or a
    # keep-recent not below the threshold) disables it, restoring full-verbatim
    # continuity exactly.
    compaction_threshold: int = DEFAULT_COMPACTION_THRESHOLD
    compaction_keep_recent: int = DEFAULT_COMPACTION_KEEP_RECENT
    # Conversation list + search pagination (US-CONV-09). ``conversation_page_size``
    # is the conservative default page; ``conversation_max_page_size`` is the hard
    # ceiling a caller-supplied limit is clamped down to. Both are tighten-only.
    conversation_page_size: int = DEFAULT_CONVERSATION_PAGE_SIZE
    conversation_max_page_size: int = DEFAULT_CONVERSATION_MAX_PAGE_SIZE
    # The tool-work line's bounds (CONTINUITY-TOOL-WORK-001 D2). Held here rather than at
    # the call site because that order's forbidden list names
    # `expressing_any_cap_as_a_call_site_constant`, following [2026] VJS-COUNTY 3.
    continuity_tool_name_chars: int = DEFAULT_CONTINUITY_TOOL_NAME_CHARS
    continuity_tool_pairs_per_turn: int = DEFAULT_CONTINUITY_TOOL_PAIRS_PER_TURN

    def resolve_page_size(self, requested: int | None) -> int:
        """The effective page size for one conversation list/search page.

        The max page size is the hard ceiling (US-CONV-09): a caller-supplied
        ``limit`` is clamped DOWN into ``[1, conversation_max_page_size]`` so no
        page can ever exceed the ceiling, and ``None`` falls back to the
        conservative default (itself clamped under the ceiling). The floor of 1
        keeps a page from degenerating to zero rows and stalling pagination."""
        ceiling = max(1, self.conversation_max_page_size)
        if requested is None:
            return max(1, min(self.conversation_page_size, ceiling))
        try:
            value = int(requested)
        except (TypeError, ValueError):
            return max(1, min(self.conversation_page_size, ceiling))
        return max(1, min(value, ceiling))


def _parse_chat(raw: Mapping[str, Any]) -> ChatConfig:
    # Lazy: parse helpers live in manifest_parse, which imports this module's
    # types (no module-level cycle).
    from .manifest_parse import _as_tuple, _tighten_cap
    skills_by_role = {
        str(role): _as_tuple(skills)
        for role, skills in (raw.get("skills_by_role") or {}).items()
    }
    caps = raw.get("attachments") or {}
    compaction = raw.get("compaction") or {}
    pagination = raw.get("pagination") or {}
    tool_work = raw.get("tool_work") or {}
    default_capability_raw = raw.get("default_capability")
    default_capability = (
        default_capability_raw.strip()
        if isinstance(default_capability_raw, str) and default_capability_raw.strip()
        else None
    )
    return ChatConfig(
        default_capability=default_capability,
        skills_by_role=skills_by_role,
        default_skills=_as_tuple(raw.get("default_skills")),
        max_attachments=_tighten_cap(DEFAULT_MAX_ATTACHMENTS, caps.get("max_count")),
        max_attachment_bytes=_tighten_cap(
            DEFAULT_MAX_ATTACHMENT_BYTES, caps.get("max_bytes")
        ),
        max_total_attachment_bytes=_tighten_cap(
            DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES, caps.get("max_total_bytes")
        ),
        heartbeat_seconds=_parse_heartbeat(raw.get("heartbeat_seconds")),
        # Compaction is tighten-only ([2026] VJS-COUNTY 3 caps model): a manifest may
        # only LOWER the threshold (compact sooner - cheaper) or keep FEWER recent
        # turns verbatim, never grow the verbatim window past the code ceiling. 0
        # disables that knob.
        compaction_threshold=_tighten_cap(
            DEFAULT_COMPACTION_THRESHOLD, compaction.get("threshold")
        ),
        compaction_keep_recent=_tighten_cap(
            DEFAULT_COMPACTION_KEEP_RECENT, compaction.get("keep_recent")
        ),
        # Pagination is tighten-only (US-CONV-09): a manifest may only shrink the
        # default/ceiling page, never grow a page past the code ceiling.
        conversation_page_size=_tighten_cap(
            DEFAULT_CONVERSATION_PAGE_SIZE, pagination.get("page_size")
        ),
        conversation_max_page_size=_tighten_cap(
            DEFAULT_CONVERSATION_MAX_PAGE_SIZE, pagination.get("max_page_size")
        ),
        # Tool-work projection is tighten-only: a manifest may only SHORTEN a rendered
        # tool name or show FEWER pairs, never widen what reaches a model's prompt.
        continuity_tool_name_chars=_tighten_cap(
            DEFAULT_CONTINUITY_TOOL_NAME_CHARS, tool_work.get("name_chars")
        ),
        continuity_tool_pairs_per_turn=_tighten_cap(
            DEFAULT_CONTINUITY_TOOL_PAIRS_PER_TURN, tool_work.get("pairs_per_turn")
        ),
    )


def _parse_heartbeat(raw_value: Any) -> float:
    """Resolve the SSE keepalive interval (US-CHAT-11). A malformed/absent value
    keeps the conservative code default; a supplied value is honoured as given (0
    or below disables the heartbeat)."""
    if raw_value is None:
        return DEFAULT_HEARTBEAT_SECONDS
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_HEARTBEAT_SECONDS
