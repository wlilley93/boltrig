"""The typed memory typology (decision 0029): planes, slots, authority, decisions.

Memory type is determined by how information must BEHAVE, not by what it says.
Five planes are recognised; three are writable through the typed write gate:

  * semantic   - current facts, one active value per slot, supersession (state);
  * episodic   - completed experience, append-only, retrieved by the problem
                 representation (experience);
  * procedural - governing policy, versioned, activated only by review
                 (authority).

Source knowledge stays in the knowledge/document ingestion paths (kind
``document_chunk`` / ``knowledge_segment``) and working state is NEVER memory -
it lives in the runtime (Hatchet checkpoints, conversation state) and merely
passes through a bundle (MEM-TYP-05).

This module is pure vocabulary + deterministic validation. It performs no I/O
and knows nothing about engines or stores, so every rule here is testable
offline.
"""

from __future__ import annotations

# --- planes ------------------------------------------------------------------
SEMANTIC = "semantic"
EPISODIC = "episodic"
PROCEDURAL = "procedural"
WRITABLE_PLANES = frozenset({SEMANTIC, EPISODIC, PROCEDURAL})

# --- closed predicate registries (a fact must occupy a known slot) -----------
SUBJECT_TYPES = frozenset({"repository", "project", "workspace", "user", "agent", "customer"})

PREDICATES: dict[str, frozenset[str]] = {
    "repository": frozenset(
        {
            "package_manager",
            "default_branch",
            "test_command",
            "build_command",
            "primary_language",
            "deployment_target",
            "owner_team",
            "other",
        }
    ),
    "project": frozenset({"deployment_target", "jurisdiction", "owner_team", "other"}),
    "workspace": frozenset({"jurisdiction", "approval_policy", "retention_policy", "other"}),
    "user": frozenset({"locale", "timezone", "working_hours", "preferred_language", "other"}),
    "agent": frozenset({"model_route", "verbosity", "tool_policy", "other"}),
    "customer": frozenset({"plan", "jurisdiction", "registered_address", "other"}),
}


def semantic_memory_key(subject_type: str, subject_id: str, predicate: str, owner_scope: str) -> str:
    """The stable logical slot for a semantic fact.

    Independent of the natural-language wording; ``owner_scope`` trails so the
    per-subject prefix (``{subject_type}::{subject_id}::``) drives deterministic
    lookup, while the unique index on (tenant, memory_key) still yields exactly
    one active value per owner+subject+predicate.
    """

    return "::".join([subject_type, subject_id, predicate, owner_scope])


def procedure_memory_key(procedure_key: str, owner_scope: str) -> str:
    return f"procedure::{procedure_key}::{owner_scope}"


# --- source authority (precedence; a lower rank never silently wins) ---------
SOURCE_AUTHORITY: dict[str, int] = {
    "authoritative_system": 5,
    "verified_integration": 4,
    "human_statement": 3,
    "approved_agent_inference": 2,
    "unverified_inference": 1,
}
DEFAULT_AUTHORITY = "unverified_inference"


def authority_rank(name: str | None) -> int:
    return SOURCE_AUTHORITY.get(str(name or DEFAULT_AUTHORITY), SOURCE_AUTHORITY[DEFAULT_AUTHORITY])


# --- write-gate decisions ------------------------------------------------------
ACCEPT_NEW = "ACCEPT_NEW"
CONFIRM_EXISTING = "CONFIRM_EXISTING"
SUPERSEDE_EXISTING = "SUPERSEDE_EXISTING"
REJECT_TRANSIENT = "REJECT_TRANSIENT"
REJECT_UNSUPPORTED = "REJECT_UNSUPPORTED"
REJECT_INVALID_PREDICATE = "REJECT_INVALID_PREDICATE"
REJECT_LOWER_AUTHORITY = "REJECT_LOWER_AUTHORITY"
REJECT_NOT_TERMINAL = "REJECT_NOT_TERMINAL"
REJECT_UNSUPPORTED_PLANE = "REJECT_UNSUPPORTED_PLANE"
REQUEST_HUMAN_REVIEW = "REQUEST_HUMAN_REVIEW"

ACCEPTED_DECISIONS = frozenset({ACCEPT_NEW, CONFIRM_EXISTING, SUPERSEDE_EXISTING})
REJECTED_DECISIONS = frozenset(
    {
        REJECT_TRANSIENT,
        REJECT_UNSUPPORTED,
        REJECT_INVALID_PREDICATE,
        REJECT_LOWER_AUTHORITY,
        REJECT_NOT_TERMINAL,
        REJECT_UNSUPPORTED_PLANE,
    }
)

# --- deterministic first-pass screens ------------------------------------------
# Transient wording: a present symptom is working state or episode material,
# never a durable semantic fact. The caller (an extraction model or a human)
# may assert durability explicitly with is_durable=true; the marker scan then
# only rejects when the caller made no such assertion.
TRANSIENT_MARKERS: tuple[str, ...] = (
    "this morning",
    "right now",
    "at the moment",
    "currently down",
    "temporarily",
    "still running",
    "is down",
    "is failing",
    "just now",
    "as of today",
    "today only",
    "since yesterday",
    "for now",
)

CONFIDENCE_ACCEPT = 0.75  # at or above: auto-accepted (authority permitting)
CONFIDENCE_REVIEW = 0.50  # at or above: candidate for human review; below: rejected

EPISODE_OUTCOMES = frozenset({"succeeded", "partially_succeeded", "failed", "abandoned"})


def predicate_allowed(subject_type: str, predicate: str) -> bool:
    registry = PREDICATES.get(subject_type)
    return registry is not None and predicate in registry


def looks_transient(statement: str) -> str | None:
    """Return the transient marker if the statement reads as present state."""

    low = (statement or "").lower()
    for marker in TRANSIENT_MARKERS:
        if marker in low:
            return marker
    return None


def valid_procedure_key(procedure_key: str) -> bool:
    """``<scope>::<role>::<workflow>[:<domain>]`` - non-empty parts, no spaces."""

    if not procedure_key or len(procedure_key) > 160:
        return False
    parts = procedure_key.split("::")
    return len(parts) >= 3 and all(part.strip() for part in parts)


__all__ = [
    "ACCEPTED_DECISIONS",
    "ACCEPT_NEW",
    "CONFIDENCE_ACCEPT",
    "CONFIDENCE_REVIEW",
    "CONFIRM_EXISTING",
    "DEFAULT_AUTHORITY",
    "EPISODIC",
    "EPISODE_OUTCOMES",
    "PREDICATES",
    "PROCEDURAL",
    "REJECTED_DECISIONS",
    "REJECT_INVALID_PREDICATE",
    "REJECT_LOWER_AUTHORITY",
    "REJECT_NOT_TERMINAL",
    "REJECT_UNSUPPORTED",
    "REJECT_UNSUPPORTED_PLANE",
    "REJECT_TRANSIENT",
    "REQUEST_HUMAN_REVIEW",
    "SEMANTIC",
    "SOURCE_AUTHORITY",
    "SUBJECT_TYPES",
    "SUPERSEDE_EXISTING",
    "WRITABLE_PLANES",
    "authority_rank",
    "looks_transient",
    "predicate_allowed",
    "procedure_memory_key",
    "semantic_memory_key",
    "valid_procedure_key",
]
