"""Governed review of capability bindings (SPEC §5, doctrine step 4).

The queue this drains is real and had no drain. Level-1 declarations from a
non-first-party plugin, and every level-2 mapping-pack claim, land ``proposed``
and are ineligible for any route. Until this existed nothing could move one, so
a pack proposing six Opbox capabilities filled an inbox with no door.

APPROVAL IS A GOVERNED WRITE, not a status edit. It is the act that makes a
verb callable by a model, so it goes through the same approval context every
other high-consequence control verb does, and it records WHO approved it on the
binding. "A declaration is evidence, never the authority to publish itself" is
the rule this enforces; someone has to be the authority.
"""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import Result
from boltrig.models import InvocationContext

from .control_approval import require_unchanged_approval_context

# Disable rather than delete. A retired mapping is evidence about what was once
# published, and the review queue should be able to show that a claim was seen
# and refused rather than losing the fact that it was ever made.
_VERBS = {
    "control.capability_binding.approve": "approved",
    "control.capability_binding.reject": "disabled",
}


async def execute_capability_binding_operation(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> Result | None:
    status = _VERBS.get(verb)
    if status is None:
        return None
    await require_unchanged_approval_context(store, loader, verb, params, context)
    binding = await store.set_capability_binding_status(
        context.tenant_id, params["binding_id"], status, context.actor
    )
    if binding is None:
        # Not a silent success. An approval naming a binding that does not exist
        # is usually a stale review queue, and answering "ok" to it would leave
        # an operator believing they had published something.
        raise LookupError("capability binding not found")
    return Result.success(
        {
            "binding_id": binding.binding_id,
            "capability": binding.ref,
            "source_operation_id": binding.source_operation_id,
            "binding_status": binding.status,
            "reviewed_by": binding.reviewed_by,
        }
    )
