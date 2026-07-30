"""Namespace ownership checks for generated and consumed control adapters."""

from __future__ import annotations

import re
from typing import Any

_RESERVED_ADAPTER_IDS = frozenset({"control"})
_RESERVED_VERB_PREFIXES = ("boltrig.", "chat.", "control.", "kernel.", "system.")
_ADAPTER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class ControlConflict(Exception):
    """A control-plane create/activation would overwrite existing authority."""


async def ensure_adapter_id_available(
    store: Any, loader: Any, tenant_id: str, adapter_id: str
) -> None:
    if adapter_id in _RESERVED_ADAPTER_IDS or not _ADAPTER_ID.fullmatch(adapter_id):
        raise ControlConflict("adapter id is reserved or invalid")
    if loader.peek(tenant_id, adapter_id) is not None:
        raise ControlConflict("adapter id is already loaded")
    if await store.get_adapter(tenant_id, adapter_id) is not None:
        raise ControlConflict("adapter id already exists")
    for verb in await store.list_all_verbs(tenant_id):
        binding = await store.get_binding(tenant_id, verb.id)
        if binding is not None and binding.target_ref == adapter_id:
            raise ControlConflict("adapter id is already referenced by a binding")


async def ensure_activation_safe(store: Any, tenant_id: str, adapter_id: str, adapter: Any) -> None:
    verb_ids = [str(spec.verb_id) for spec in adapter.describe()]
    if len(verb_ids) != len(set(verb_ids)):
        raise ControlConflict("adapter declares duplicate verb ids")
    if any(verb.startswith(_RESERVED_VERB_PREFIXES) for verb in verb_ids):
        raise ControlConflict("adapter declares a reserved core verb")
    for verb_id in verb_ids:
        existing = await store.get_verb_any(tenant_id, verb_id)
        if existing is None:
            continue
        binding = await store.get_binding(tenant_id, verb_id)
        if binding is None or binding.target_ref != adapter_id:
            raise ControlConflict("adapter verb is already owned by another target")
