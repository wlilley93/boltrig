"""Verb schemas for the ``distill`` adapter (decision 0023).

Bounded JSON Schemas with ``additionalProperties: false`` throughout - the
train schema's closed shape is itself load-bearing (DIS-4): no field exists to
name a starting point other than the composed base pin, so adapter-on-adapter
training is unrepresentable at the contract, not merely refused at runtime.
"""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import VerbSpec

ADAPTER_KINDS = ("craft", "register")
_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64,
           "pattern": "^[0-9a-f]{64}$"}
# A model name is an adapter id or an HF-style repo path - never a filesystem
# escape. The sidecar enforces its own boundary too (defence in depth).
_MODEL_NAME = {"type": "string", "minLength": 1, "maxLength": 256,
               "pattern": "^(?!.*\\.\\.)[A-Za-z0-9][A-Za-z0-9._@/-]*$"}


def corpus_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "target_endpoint_id": {"type": "string", "minLength": 1, "maxLength": 128},
        },
        "required": ["target_endpoint_id"],
        "additionalProperties": False,
    }


def train_schema() -> dict[str, Any]:
    # Deliberately NO base/adapter/resume field (DIS-4).
    return {
        "type": "object",
        "properties": {
            "corpus_digest": _DIGEST,
            "adapter_kind": {"type": "string", "enum": list(ADAPTER_KINDS)},
        },
        "required": ["corpus_digest", "adapter_kind"],
        "additionalProperties": False,
    }


def gate_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "corpus_digest": _DIGEST,
            "adapter_kind": {"type": "string", "enum": list(ADAPTER_KINDS)},
            "candidate_model": _MODEL_NAME,
            "incumbent_model": _MODEL_NAME,
        },
        "required": ["corpus_digest", "adapter_kind", "candidate_model",
                     "incumbent_model"],
        "additionalProperties": False,
    }


def night_schema() -> dict[str, Any]:
    # One night in one verb: build -> ship -> train -> gate. Promotion stays a
    # separate act unless auto_promote is explicitly set (default off).
    return {
        "type": "object",
        "properties": {
            "target_endpoint_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "adapter_kind": {"type": "string", "enum": list(ADAPTER_KINDS)},
            "incumbent_model": _MODEL_NAME,
            "auto_promote": {"type": "boolean"},
            "price_micros_per_token": {"type": "number", "minimum": 0, "maximum": 1000},
        },
        "required": ["target_endpoint_id", "adapter_kind", "incumbent_model"],
        "additionalProperties": False,
    }


def promote_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "endpoint_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "corpus_digest": _DIGEST,
            "price_micros_per_token": {"type": "number", "minimum": 0, "maximum": 1000},
        },
        "required": ["endpoint_id", "corpus_digest", "price_micros_per_token"],
        "additionalProperties": False,
    }


def verb_specs() -> list[VerbSpec]:
    """The adapter's five verbs, as declared to the kernel.

    Lives here rather than on the adapter because it is a pure function of
    the schemas above and never touches instance state -- and because
    adapter.py sits against the 400-line structural ratchet, which is what
    moved it.
    """
    any_out = {"type": "object"}
    return [
        VerbSpec(
            "distill.corpus.build",
            "distill",
            corpus_schema(),
            any_out,
            "low",
            "Derive the tenant's training corpus from the governed record "
            "(erasure-filtered, PII-scrubbed, digest-pinned) and ship it to "
            "the local trainer sidecar.",
            idempotency_mode="disabled",  # re-derives; the digest is the identity
        ),
        VerbSpec(
            "distill.train",
            "distill",
            train_schema(),
            any_out,
            "high",
            "Train a candidate LoRA from the PINNED BASE over a shipped "
            "corpus. There is no field to name any other starting point.",
            idempotency_mode="disabled",
        ),
        VerbSpec(
            "distill.gate",
            "distill",
            gate_schema(),
            any_out,
            "low",
            "Score a candidate against the incumbent, mechanically: eval "
            "cases for craft, held-out likelihood for register. Writes an "
            "audit row whether it promotes or holds.",
            idempotency_mode="disabled",
        ),
        VerbSpec(
            "distill.promote",
            "distill",
            promote_schema(),
            any_out,
            "high",
            "Activate a candidate endpoint that holds a passing gate "
            "receipt, and price it in the same act.",
            idempotency_mode="disabled",
        ),
        VerbSpec(
            "distill.night",
            "distill",
            night_schema(),
            any_out,
            "high",
            "One night of sleep distillation: build the corpus, train from "
            "the pinned base, gate mechanically. Does NOT promote unless "
            "auto_promote is set; a passing gate leaves the receipt for a "
            "separate distill.promote.",
            idempotency_mode="disabled",
        ),
    ]
