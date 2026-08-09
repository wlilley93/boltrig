"""Verb schemas for the ``distill`` adapter (decision 0023).

Bounded JSON Schemas with ``additionalProperties: false`` throughout - the
train schema's closed shape is itself load-bearing (DIS-4): no field exists to
name a starting point other than the composed base pin, so adapter-on-adapter
training is unrepresentable at the contract, not merely refused at runtime.
"""

from __future__ import annotations

from typing import Any

ADAPTER_KINDS = ("craft", "register")
_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64,
           "pattern": "^[0-9a-f]{64}$"}


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
            "candidate_model": {"type": "string", "minLength": 1, "maxLength": 256},
            "incumbent_model": {"type": "string", "minLength": 1, "maxLength": 256},
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
            "incumbent_model": {"type": "string", "minLength": 1, "maxLength": 256},
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
