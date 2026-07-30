"""Compose the severed channel-gateway links.

The gateway owns no policy or grants. Its show-once, no-verb MCP run token is
bounded to explicit socket channels; a durable per-channel lease elects the one
owner allowed to receive resolved provider credentials, report observations,
claim durable outbox work, or serve realtime call links.
"""

from __future__ import annotations

from .channel_gateway_outbox_routes import register_gateway_outbox_routes
from .channel_gateway_reconcile_routes import register_gateway_reconcile_routes
from .channel_gateway_session_routes import register_gateway_session_route
from .channel_gateway_specs import channel_desired_revision


def register_channel_gateway_routes(
    app, *, principal_dep, get_kernel
) -> None:
    register_gateway_session_route(
        app, principal_dep=principal_dep, get_kernel=get_kernel
    )
    register_gateway_reconcile_routes(app, get_kernel=get_kernel)
    register_gateway_outbox_routes(app, get_kernel=get_kernel)


__all__ = ["channel_desired_revision", "register_channel_gateway_routes"]
