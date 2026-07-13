"""Governed control-plane registration contract for deep readiness."""

from __future__ import annotations

from typing import Any

from boltrig.kernel import Kernel
from boltrig.models import TargetType

REQUIRED_CONTROL_VERBS = frozenset(
    {
        "control.workflow.upsert",
        "control.capability.upsert",
        "control.model_endpoint.upsert",
        "control.skill.upsert",
        "control.noun.define",
        "control.verb.define",
        "control.binding.set",
        "control.mcp_server.register",
        "control.config.upsert",
        "control.workflow.schedule",
        "control.workflow.trigger",
        "control.workflow.execute",
        "control.adapter.generate",
        "control.adapter.activate",
        "control.config.rollback",
        "control.user.update",
        "control.user.deactivate",
        "control.invitation.create",
        "control.notification.route",
    }
)


async def control_plane_check(kernel: Kernel, tenant_id: str) -> dict[str, Any]:
    """Require live wiring plus matching persisted verbs and control bindings."""
    adapter = kernel.loader.peek(tenant_id, "control")
    if adapter is None:
        return {"status": "failed", "required": True, "reason": "not_registered"}
    try:
        registered = {str(item.verb_id) for item in adapter.describe()}
    except Exception:
        return {"status": "failed", "required": True, "reason": "probe_failed"}
    missing = REQUIRED_CONTROL_VERBS - registered
    persisted = 0
    invalid_bindings = 0
    for verb_id in REQUIRED_CONTROL_VERBS:
        verb = await kernel.store.get_verb(tenant_id, verb_id)
        binding = await kernel.store.get_binding(tenant_id, verb_id)
        if verb is None or binding is None:
            continue
        persisted += 1
        if (
            verb.noun_id != "control"
            or binding.target_type != TargetType.ADAPTER
            or binding.target_ref != "control"
        ):
            invalid_bindings += 1
    record = await kernel.store.get_adapter(tenant_id, "control")
    try:
        collaborators = adapter.readiness_collaborators(kernel)
    except Exception:
        collaborators = {}
    required_collaborators = {"store", "loader", "registry", "admin", "workflows"}
    missing_collaborators = sum(
        1 for name in required_collaborators if collaborators.get(name) is not True
    )
    ready = (
        not missing
        and persisted == len(REQUIRED_CONTROL_VERBS)
        and invalid_bindings == 0
        and record is not None
        and record.activated
        and missing_collaborators == 0
    )
    result: dict[str, Any] = {
        "status": "ok" if ready else "failed",
        "required": True,
        "registered": len(registered),
        "persisted": persisted,
        "expected": len(REQUIRED_CONTROL_VERBS),
    }
    if missing:
        result["reason"] = "incomplete_registration"
    elif persisted != len(REQUIRED_CONTROL_VERBS) or record is None:
        result["reason"] = "incomplete_persistence"
    elif invalid_bindings:
        result["reason"] = "invalid_bindings"
    elif not record.activated:
        result["reason"] = "inactive_adapter"
    elif missing_collaborators:
        result["reason"] = "collaborators_unavailable"
    return result
