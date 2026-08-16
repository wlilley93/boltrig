"""Declarative verb surface for the governed memory adapter."""

from boltrig.adapters.base import VerbSpec
from boltrig.store.base import MAX_INGEST_ITEMS

_OBJECT: dict = {"type": "object"}


def memory_verb_specs() -> list[VerbSpec]:
    return [
        _remember_spec(),
        _ingest_spec(),
        _recall_spec(),
        _improve_spec(),
        _forget_spec(),
        _propose_spec(),
        _bundle_spec(),
        _resolve_spec(),
        _review_spec(),
    ]


def _remember_spec():
    return VerbSpec(
        verb_id="memory.remember",
        noun_id="memory",
        input_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "owner_scope": {"type": "string"},
                "kind": {"type": "string"},
                "source_kind": {"type": "string"},
                "source_ref": {"type": "string"},
                "data_class": {"type": "string"},
                "relates_to": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["content"],
        },
        output_schema=_OBJECT,
        consequence="low",
        description="Commit a fact to memory (scoped, provenance-tagged)",
    )


def _ingest_spec():
    return VerbSpec(
        verb_id="memory.ingest",
        noun_id="memory",
        input_schema={
            "type": "object",
            "properties": {
                "source_kind": {"type": "string"},
                "source_ref": {"type": "string"},
                "owner_scope": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": MAX_INGEST_ITEMS,
                },
            },
            "required": ["source_kind", "source_ref"],
        },
        output_schema=_OBJECT,
        consequence="low",
        description="Screen and commit one exact source as a governed memory batch",
    )


def _recall_spec():
    return VerbSpec(
        verb_id="memory.recall",
        noun_id="memory",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "mode": {"type": "string"},
                "limit": {"type": "integer"},
                "owner_scope": {"type": "string"},
            },
            "required": ["query"],
        },
        output_schema=_OBJECT,
        consequence="low",
        description="Recall facts from the caller's permitted scopes, with provenance",
    )


def _improve_spec():
    return VerbSpec(
        verb_id="memory.improve",
        noun_id="memory",
        input_schema={
            "type": "object",
            "properties": {
                "signal": {"type": "string", "minLength": 1, "maxLength": 128},
                "target": {"type": "string", "minLength": 1, "maxLength": 256},
            },
            "required": ["signal", "target"],
        },
        output_schema=_OBJECT,
        consequence="low",
        description="Reweight memory from a usage/feedback signal",
    )


def _forget_spec():
    # Erasure is a compliance right, so it is not HITL-gated but is always
    # ledgered and audited.
    return VerbSpec(
        verb_id="memory.forget",
        noun_id="memory",
        input_schema={
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "source_ref": {"type": "string"},
            },
        },
        output_schema=_OBJECT,
        consequence="low",
        description="Erase a fact/source and its derived edges (complete, ledgered)",
    )


def _propose_spec():
    return VerbSpec(
        verb_id="memory.propose",
        noun_id="memory",
        input_schema={
            "type": "object",
            "properties": {
                "plane": {
                    "type": "string",
                    "enum": ["semantic", "episodic", "procedural"],
                },
                "owner_scope": {"type": "string"},
                # semantic
                "subject_type": {"type": "string"},
                "subject_id": {"type": "string"},
                "predicate": {"type": "string"},
                "value": {},
                "statement": {"type": "string"},
                "is_durable": {"type": "boolean"},
                "source_authority": {
                    "type": "string",
                    "enum": [
                        "authoritative_system",
                        "verified_integration",
                        "human_statement",
                        "approved_agent_inference",
                        "unverified_inference",
                    ],
                },
                # episodic
                "title": {"type": "string"},
                "retrieval_text": {"type": "string"},
                "situation": {"type": "string"},
                "attempted": {"type": "array", "items": {"type": "string"}},
                "failed_attempts": {"type": "array", "items": {"type": "string"}},
                "root_cause": {"type": "string"},
                "resolution": {"type": "string"},
                "outcome": {"type": "string"},
                "is_terminal": {"type": "boolean"},
                "task_family": {"type": "string"},
                "tools_used": {"type": "array", "items": {"type": "string"}},
                "environment": {"type": "object"},
                "outcome_evidence": {"type": "array", "items": {"type": "string"}},
                # procedural
                "procedure_key": {"type": "string"},
                "summary": {"type": "string"},
                "body_markdown": {"type": "string"},
                "applies_to_roles": {"type": "array", "items": {"type": "string"}},
                "applies_to_workflows": {"type": "array", "items": {"type": "string"}},
                "invariants": {"type": "array", "items": {"type": "string"}},
                "prohibited_actions": {"type": "array", "items": {"type": "string"}},
                # shared
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "source_kind": {"type": "string"},
                "source_ref": {"type": "string"},
            },
            "required": ["plane"],
        },
        output_schema=_OBJECT,
        consequence="low",
        description=(
            "Propose a typed memory candidate; the deterministic write gate "
            "decides (accept/supersede/confirm/reject/request review)"
        ),
    )


def _bundle_spec():
    return VerbSpec(
        verb_id="memory.bundle",
        noun_id="memory",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "subjects": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "id": {"type": "string"},
                        },
                        "required": ["type", "id"],
                    },
                },
                "agent_role": {"type": "string"},
                "workflow": {"type": "string"},
                "working_context": {"type": "array", "items": {"type": "string"}},
                "owner_scope": {"type": "string"},
                "config": {"type": "object"},
            },
        },
        output_schema=_OBJECT,
        consequence="low",
        description=(
            "Assemble the typed memory bundle (procedures/facts/sources/episodes/"
            "working state) plus the authority-wrapped prompt"
        ),
    )


def _resolve_spec():
    return VerbSpec(
        verb_id="memory.resolve",
        noun_id="memory",
        input_schema={
            "type": "object",
            "properties": {
                "subject_type": {"type": "string"},
                "subject_id": {"type": "string"},
                "predicates": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["subject_type", "subject_id"],
        },
        output_schema=_OBJECT,
        consequence="low",
        description="Deterministic current-value lookup: the active facts for a subject",
    )


def _review_spec():
    # Activating governance (a procedure, a conflicted fact) is a high-
    # consequence act: it changes what governs future agent runs.
    return VerbSpec(
        verb_id="memory.candidates.review",
        noun_id="memory",
        input_schema={
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string"},
                "decision": {"type": "string", "enum": ["approve", "reject"]},
            },
            "required": ["candidate_id", "decision"],
        },
        output_schema=_OBJECT,
        consequence="high",
        description="Approve or reject a memory candidate (the only activation path)",
    )


__all__ = ["memory_verb_specs"]
