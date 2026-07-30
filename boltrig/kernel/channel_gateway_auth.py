"""Shared authentication for gateway-only kernel links."""

from __future__ import annotations

from fastapi import Request


GATEWAY_TOKEN_HEADER = "x-boltrig-mcp-token"


def gateway_run_token(request: Request, kernel):
    """Authenticate a gateway run token and bind its verified tenant for RLS."""
    token = kernel.mcp.lookup_run_token(
        request.headers.get(GATEWAY_TOKEN_HEADER)
    )
    if token is None or not (token.extra or {}).get("channel_gateway"):
        return None
    from boltrig.store.postgres import set_current_tenant

    set_current_tenant(token.tenant_id)
    return token


__all__ = ["GATEWAY_TOKEN_HEADER", "gateway_run_token"]
