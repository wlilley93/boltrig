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


__all__ = ["memory_verb_specs"]
