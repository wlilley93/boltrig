"""Browser-safe work-item projections shared by list and detail routes."""

from __future__ import annotations

from typing import Any

from boltrig.work.channel_provenance import public_channel_provenance


def work_item_view(item: Any, *, detail: bool = False) -> dict[str, Any]:
    """Project work without its private constraints or remote provider IDs."""

    view = {
        "id": item.id,
        "intent": item.intent,
        "status": item.status.value,
        "confidence": item.confidence,
        "convergent": item.convergent,
        "owner_member": item.owner_member,
        "source": item.source,
        "parent_id": item.parent_id,
        "hatchet_run_id": item.hatchet_run_id,
        "provenance": public_channel_provenance(item),
    }
    if detail:
        view["on_behalf_of"] = item.on_behalf_of
    return view


__all__ = ["work_item_view"]
