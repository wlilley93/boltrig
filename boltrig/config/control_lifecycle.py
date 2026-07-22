"""Governed adapter suspension and removal - the inverse of activation (SEC-22).

``control.adapter.activate`` publishes a reviewed adapter's verbs; this module
is its governed reverse, run as ordinary high-consequence control verbs so
validation, grants, the HITL gate, and the audit chain apply like any other
mutation (ONE chokepoint):

- ``control.adapter.deactivate`` suspends a LIVE adapter: the verb + binding
  rows it published are removed (along with any noun the removal orphans), so
  dispatch refuses exactly as it does for a never-registered verb, and the
  adapter record flips back to ``activated=False``. Re-activation re-runs the
  review gate and republishes.
- ``control.adapter.delete`` removes an adapter that is NOT live (inert or
  deactivated), reversing exactly what registration + activation persisted:
  the adapter row, its owned verb/binding rows, the nouns those verbs left
  unreferenced, and the credential ref registration bound (only when nothing
  else references it). A LIVE adapter is refused - deactivate first, so the
  state machine stays one-step-at-a-time and fail-closed.

Ownership follows the activation convention (``control_safety``): a verb is
the adapter's own iff its binding's ``target_ref`` is the adapter id, so a
delete can never strip verbs another target owns. Reserved core ids (the
``control`` adapter itself) are refused outright.
"""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import AdapterError, ErrorClass, Result
from boltrig.models import Verb

from .control_approval import require_unchanged_approval_context
from .control_safety import _RESERVED_ADAPTER_IDS, ControlConflict

__all__ = ["execute_adapter_lifecycle"]


async def _unpublish_owned_verbs(
    store: Any, tenant_id: str, adapter_id: str
) -> list[Verb]:
    """Remove the verb + binding rows the adapter published.

    Reverses ``KernelRegistry.register_adapter_verbs`` per-verb effects for the
    verbs the adapter OWNS (binding target_ref == adapter id, the activation
    ownership convention). Nouns are left for the caller: they may be shared.
    """
    owned: list[Verb] = []
    for verb in await store.list_verbs(tenant_id):
        binding = await store.get_binding(tenant_id, verb.id)
        if binding is not None and binding.target_ref == adapter_id:
            owned.append(verb)
    for verb in owned:
        await store.delete_binding(tenant_id, verb.id)
        await store.delete_verb(tenant_id, verb.id)
    return owned


async def _drop_orphaned_nouns(store: Any, tenant_id: str, removed: list[Verb]) -> None:
    """Delete the nouns a removal left unreferenced.

    Activation creates a noun only when absent, so a noun no remaining verb
    references is exactly what activation added; a noun other verbs still use
    is not this adapter's to remove.
    """
    for noun_id in sorted({verb.noun_id for verb in removed}):
        if not await store.list_verbs(tenant_id, noun_id):
            await store.delete_noun(tenant_id, noun_id)


async def _deactivate(
    store: Any, loader: Any, tenant_id: str, adapter_id: str
) -> Result:
    record = await store.get_adapter(tenant_id, adapter_id)
    if record is None:
        raise LookupError("adapter not found")
    if not record.activated:
        # Inert or already suspended: a clean idempotent no-op (mirrors the
        # already-revoked invitation idiom), not an error.
        return Result.success({"id": adapter_id, "activated": False, "verbs": []})
    removed = await _unpublish_owned_verbs(store, tenant_id, adapter_id)
    await _drop_orphaned_nouns(store, tenant_id, removed)
    record.activated = False
    await store.upsert_adapter(record)
    adapter = loader.peek(tenant_id, adapter_id)
    if adapter is not None and hasattr(adapter, "activated"):
        # Defence in depth behind the removed rows: a live instance that
        # carries the review-gate flag is flipped back to inert, so even a
        # stale reference cannot execute (SEC-22, mirrors review_and_activate).
        adapter.activated = False
    return Result.success(
        {"id": adapter_id, "activated": False, "verbs": [verb.id for verb in removed]}
    )


async def _release_credential(
    store: Any, credentials: Any, tenant_id: str, adapter_id: str
) -> str | None:
    """Unbind and delete the credential ref registration created, if unshared.

    The resolver's adapter->credential binding is the primary record of WHICH
    ref an adapter used, so it is read as it is removed (a re-registered
    adapter must never silently inherit a deleted adapter's credential). That
    binding is in-memory, so after a restart it is gone: fall back to the
    default id convention registration used (``<adapter_id>-mcp-token``) when
    its ref row persists. The row itself is deleted only when nothing else
    references it - no other adapter binding and no AI-config row names it; a
    shared ref is left in place.
    """
    bindings = getattr(credentials, "_adapter_cred", None) if credentials else None
    cred_id = bindings.pop((tenant_id, adapter_id), None) if isinstance(bindings, dict) else None
    if cred_id is None:
        derived = f"{adapter_id}-mcp-token"  # bind_mcp_credential's default id
        if await store.get_credential_ref(tenant_id, derived) is not None:
            cred_id = derived
    if cred_id is None:
        return None
    other_bindings = bindings.values() if isinstance(bindings, dict) else ()
    shared = cred_id in other_bindings or any(
        config.credential_ref == cred_id for config in await store.list_ai_configs(tenant_id)
    )
    if not shared:
        await store.delete_credential_ref(tenant_id, cred_id)
    return cred_id


async def _delete(
    store: Any, loader: Any, credentials: Any, tenant_id: str, adapter_id: str
) -> Result:
    record = await store.get_adapter(tenant_id, adapter_id)
    if record is None:
        raise LookupError("adapter not found")
    if record.activated:
        raise ControlConflict("adapter is live; deactivate it before delete")
    removed = await _unpublish_owned_verbs(store, tenant_id, adapter_id)
    await _drop_orphaned_nouns(store, tenant_id, removed)
    await store.delete_adapter(tenant_id, adapter_id)
    loader.unload(tenant_id, adapter_id)
    credential_ref = await _release_credential(store, credentials, tenant_id, adapter_id)
    return Result.success(
        {
            "id": adapter_id,
            "deleted": True,
            "verbs": [verb.id for verb in removed],
            "credential_ref": credential_ref,
        }
    )


async def execute_adapter_lifecycle(
    store: Any,
    loader: Any,
    credentials: Any,
    verb: str,
    params: dict[str, Any],
    context: Any,
) -> Result:
    """Execute ``control.adapter.deactivate`` / ``control.adapter.delete``."""
    await require_unchanged_approval_context(store, loader, verb, params, context)
    if loader is None:
        return Result.failure(AdapterError(ErrorClass.UNAVAILABLE, "adapter loader not wired"))
    adapter_id = str(params["adapter_id"])
    if adapter_id in _RESERVED_ADAPTER_IDS:
        raise ControlConflict("adapter id is reserved")
    if verb == "control.adapter.deactivate":
        return await _deactivate(store, loader, context.tenant_id, adapter_id)
    return await _delete(store, loader, credentials, context.tenant_id, adapter_id)
