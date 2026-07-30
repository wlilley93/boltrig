"""Governed evaluation-case control operations."""

from __future__ import annotations

import uuid
from typing import Any

from boltrig.models import EVAL_TARGET_KINDS, EvalCase


async def upsert_eval_case(
    store: Any, tenant_id: str, params: dict[str, Any], context: Any
) -> dict:
    from .control_approval import require_unchanged_approval_context
    from .control_channel_approval import require_channel_author

    require_channel_author(context)
    await require_unchanged_approval_context(
        store, None, "control.eval_case.upsert", params, context
    )
    target_kind = str(params["target_kind"])
    target_ref = str(params["target_ref"]).strip()
    if target_kind not in EVAL_TARGET_KINDS:
        raise ValueError(f"target_kind must be one of {', '.join(EVAL_TARGET_KINDS)}")
    if not target_ref:
        raise ValueError("target_ref is required")
    case = EvalCase(
        id=params.get("id") or uuid.uuid4().hex,
        tenant_id=tenant_id,
        target_kind=target_kind,
        target_ref=target_ref,
        input=params.get("input", {}),
        assertions=params.get("assertions", {}),
        labels=params.get("labels", []),
    )
    await store.upsert_eval_case(case)
    current = await store.get_eval_case(tenant_id, case.id)
    return {
        "id": case.id,
        "target": case.target_ref,
        "eval_case_status": (
            "active" if current is None or current.is_active else "archived"
        ),
    }


async def _set_eval_case_lifecycle(
    store: Any,
    tenant_id: str,
    params: dict[str, Any],
    context: Any,
    *,
    verb: str,
) -> dict:
    from .control_approval import require_unchanged_approval_context
    from .control_channel_approval import require_channel_author

    require_channel_author(context)
    await require_unchanged_approval_context(store, None, verb, params, context)
    active = verb.endswith(".restore")
    if not await store.set_eval_case_active(tenant_id, str(params["id"]), active):
        raise LookupError("evaluation case not found")
    return {
        "id": str(params["id"]),
        "eval_case_status": "active" if active else "archived",
    }


async def archive_eval_case(
    store: Any, tenant_id: str, params: dict[str, Any], context: Any
) -> dict:
    return await _set_eval_case_lifecycle(
        store,
        tenant_id,
        params,
        context,
        verb="control.eval_case.archive",
    )


async def restore_eval_case(
    store: Any, tenant_id: str, params: dict[str, Any], context: Any
) -> dict:
    return await _set_eval_case_lifecycle(
        store,
        tenant_id,
        params,
        context,
        verb="control.eval_case.restore",
    )
