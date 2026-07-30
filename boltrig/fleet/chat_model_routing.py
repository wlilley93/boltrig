"""Bounded model-routing event projection for conversational clients."""

from __future__ import annotations

from typing import Any


def publish_model_routing(
    relay: Any,
    run_id: str,
    requested_profile: str | None,
    result: dict[str, Any],
) -> None:
    """Publish the selected public profile/class while withholding its provider route."""
    output = result.get("output")
    route = output.get("model_route") if isinstance(output, dict) else None
    if not isinstance(route, dict):
        return
    selected = str(route.get("profile") or "policy-default")
    relay.publish(
        run_id,
        {
            "type": "model_routing",
            "run_id": run_id,
            "selected_profile_id": selected,
            "requested_profile_id": requested_profile,
            "routing_class": str(route.get("runtime") or "governed"),
            "reason": (
                "approved profile selected"
                if selected == requested_profile
                else "Boltrig policy selected the route"
            ),
            "overridden": bool(requested_profile and selected != requested_profile),
        },
    )
