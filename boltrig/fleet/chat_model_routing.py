"""Bounded model-routing event projection for conversational clients."""

from __future__ import annotations

from typing import Any


def publish_model_routing(
    relay: Any,
    run_id: str,
    requested_profile: str | None,
    result: dict[str, Any],
    *,
    requested_choice: str | None = None,
) -> None:
    """Publish the selected governed choice while withholding provider topology."""
    output = result.get("output")
    route = output.get("model_route") if isinstance(output, dict) else None
    if not isinstance(route, dict):
        return
    selected = str(route.get("choice_id") or route.get("profile") or "policy-default")
    requested = requested_choice or requested_profile
    relay.publish(
        run_id,
        {
            "type": "model_routing",
            "run_id": run_id,
            "selected_profile_id": selected,
            # Kept under the existing wire key for backward-compatible clients;
            # its value is now either the opaque chat choice or legacy profile.
            "requested_profile_id": requested,
            "routing_class": str(route.get("runtime") or "governed"),
            "reason": (
                "approved model choice selected"
                if requested_choice and selected == requested_choice
                else "approved profile selected"
                if requested_profile and selected == requested_profile
                else "Boltrig policy selected the route"
            ),
            "overridden": bool(requested and selected != requested),
        },
    )
