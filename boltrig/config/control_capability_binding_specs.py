"""Verb specs for capability-binding review (SPEC §5, doctrine step 4).

Its own module rather than an addition to ``control_compat_specs``, which is
pinned at its structural ratchet: a ratchet is never raised, so a file at one
is a file that has to stop growing. These are also not compatibility verbs -
they are the doctrine's own review surface - so the split says something true
rather than only satisfying a counter.
"""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import VerbSpec

_STRING: dict[str, Any] = {"type": "string"}


def _review_spec(verb_id: str, description: str) -> VerbSpec:
    return VerbSpec(
        verb_id=verb_id,
        noun_id="control",
        input_schema={
            "type": "object",
            "properties": {"binding_id": _STRING},
            "required": ["binding_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        description=description,
        # HIGH, and deliberately: approving a binding is what makes a canonical
        # verb callable by a model, which is the whole of what "publish" means
        # here. Rejecting is high for the same reason in reverse - it withdraws
        # a route an agent may already be relying on.
        consequence="high",
    )


def capability_binding_specs() -> list[VerbSpec]:
    return [
        _review_spec(
            "control.capability_binding.approve",
            "Approve a proposed capability binding, making its canonical verb routable",
        ),
        _review_spec(
            "control.capability_binding.reject",
            "Refuse a proposed capability binding, keeping the record of the claim",
        ),
    ]
