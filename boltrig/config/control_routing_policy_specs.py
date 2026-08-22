"""Verb specs for routing policies (SPEC §8, doctrine step 6, the route half).

``RoutingPolicy`` has had a model, a table and a store since the routing shard
landed, and ZERO routes, verbs or SDK methods. Selection therefore fell through
to binding priority every time, and the doctrine's "under these circumstances
select this binding" was expressible in the schema and unreachable from outside
the process. These are the verbs that make it authorable.

Its own module for the same reason ``control_capability_binding_specs`` is:
``control_compat_specs`` sits at its structural ratchet, and a ratchet is never
raised.
"""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import VerbSpec
from boltrig.models.capability_routing import OPERATION_CLASSES, POLICY_SCOPES

_STRING: dict[str, Any] = {"type": "string"}

#: Lives here rather than beside the executor because ``control_approval`` has
#: to name it to route the approval-context hook, and the executor imports
#: ``control_approval``. A leaf module is the only place both can reach.
ROUTING_POLICY_ACTIONS = frozenset(
    {"control.routing_policy.upsert", "control.routing_policy.delete"}
)


def routing_policy_specs() -> list[VerbSpec]:
    return [
        VerbSpec(
            verb_id="control.routing_policy.upsert",
            noun_id="control",
            input_schema={
                "type": "object",
                "properties": {
                    "id": _STRING,
                    "capability_id": _STRING,
                    "binding_id": _STRING,
                    "operation_class": {
                        "type": "string",
                        "enum": list(OPERATION_CLASSES),
                    },
                    "capability_version": {"type": "integer"},
                    "scope": {"type": "string", "enum": list(POLICY_SCOPES)},
                    "workspace_id": _STRING,
                    "precedence": {"type": "integer"},
                },
                "required": ["id", "capability_id", "binding_id"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            description=(
                "Author or replace the routing policy that selects a binding "
                "for a capability"
            ),
            # HIGH. A policy decides WHICH implementation a canonical verb
            # reaches, so editing one silently redirects calls an agent is
            # already making - the same consequence as approving the binding,
            # arrived at from the other side.
            consequence="high",
        ),
        VerbSpec(
            verb_id="control.routing_policy.delete",
            noun_id="control",
            input_schema={
                "type": "object",
                "properties": {"id": _STRING},
                "required": ["id"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            description="Remove a routing policy, returning selection to binding priority",
            consequence="high",
        ),
    ]
