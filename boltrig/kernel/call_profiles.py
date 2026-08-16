"""Resolve caller-selected voice profiles into durable governed routes."""

from __future__ import annotations

from boltrig.config.model_profile_views import resolve_realtime_model_profile
from boltrig.models import derive_familiar_genotype


async def resolve_call_profiles(kernel, principal, body: dict):
    agent_id = str(body.get("agent_profile_id") or "").strip() or None
    model_id = str(body.get("model_profile_id") or "").strip() or None
    capability = None
    if agent_id:
        capability = next(
            (
                item for item in await kernel.store.list_capabilities(
                    principal.tenant_id
                )
                if item.name == agent_id
            ),
            None,
        )
        if capability is None:
            return None, "agent_profile_not_found"
        realtime_endpoint_id = capability.endpoint_for("realtime")
        if realtime_endpoint_id:
            bound_endpoint = await kernel.store.get_model_endpoint(
                principal.tenant_id, realtime_endpoint_id
            )
            if (
                bound_endpoint is None
                or not bound_endpoint.is_active
                or not bound_endpoint.supports("realtime")
            ):
                return None, "agent_model_endpoint_unavailable"

    route = resolve_realtime_model_profile(model_id) if model_id else None
    if model_id and route is None:
        return None, "model_profile_not_realtime_capable"
    realtime_endpoint_id = capability.endpoint_for("realtime") if capability else None
    if route is None and capability is not None and realtime_endpoint_id:
        endpoint = await kernel.store.get_model_endpoint(
            principal.tenant_id, realtime_endpoint_id
        )
        if (
            endpoint is not None
            and endpoint.is_active
            and endpoint.supports("realtime")
            and endpoint.kind.lower() in {"xai", "x.ai", "grok"}
        ):
            route = {
                "provider": "xai",
                "model": endpoint.model,
                "endpoint_id": endpoint.id,
            }
    if capability is not None and route is None:
        return None, "agent_profile_not_realtime_capable"
    if route is not None and capability is not None:
        route = {
            **route,
            "agent_profile_id": capability.name,
            "agent_runtime": capability.runtime,
        }

    participants = [{"id": principal.subject, "label": "You", "kind": "user"}]
    if capability is not None:
        participants.append({
            "id": capability.name,
            "label": capability.name.replace("-", " ").replace("_", " ").title(),
            "kind": "agent",
            "familiar_genotype": derive_familiar_genotype(
                capability.name
            ).as_view(),
        })
    return {
        "agent_profile_id": agent_id,
        "model_profile_id": model_id,
        "provider_route": route,
        "participants": participants,
    }, None
