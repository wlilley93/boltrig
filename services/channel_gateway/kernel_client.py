"""The channel gateway's two kernel links (decision 0003, Phase 2).

A SEVERED client: this module must NOT import ``boltrig.*`` (SEC-28), so the
~15 lines of canonical-JSON HMAC are a deliberate local copy of the kernel's
``adapters/builtin/inbound_webhook.py`` scheme - the gateway signs intake POSTs
exactly like a webhook sender, so the kernel keeps ONE intake path.

Link (a) - inbound: POST normalized platform messages to
``/v1/channels/{id}/inbound``, signed with the connect-time secret (injected
into the gateway's environment at spawn, NEVER logged and never sent anywhere
but into the HMAC).

Link (b) - outbound: claim / ack / fail the kernel's durable channel outbox
over the run-scoped token (the ``x-boltrig-mcp-token`` header, the same token
seam as the kernel's MCP face). The token authenticates the gateway; it carries
no verb authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx


def _canonical_body(payload: dict[str, Any]) -> bytes:
    """Deterministic byte form of a payload (sorted keys, tight separators)."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def signature_header(secret: str, payload: dict[str, Any], *, ts: int | None = None) -> str:
    """The Stripe-style ``t=<unix>,v1=<hex>`` header: the timestamp is bound
    INTO the signed bytes so a captured signature cannot be replayed under a
    rewritten ``t`` (M3/SEC-66, same scheme as the kernel's webhook intake)."""
    ts = ts if ts is not None else int(time.time())
    signed = f"{ts}.".encode("utf-8") + _canonical_body(payload)
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


class KernelLinkError(Exception):
    """A kernel link call failed at the transport or status level."""


class KernelAuthError(KernelLinkError):
    """The run-scoped token was refused (401): expired or revoked. The
    supervisor treats this as fatal so a respawn re-injects a fresh token."""


class KernelClient:
    """A thin async client for the two links. ``client`` is injectable so tests
    can drive an in-process kernel (an ASGI transport) without a listener."""

    def __init__(
        self, base_url: str, token: str | None, *, client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._token = token
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _token_headers(self) -> dict[str, str]:
        return {"x-boltrig-mcp-token": self._token or ""}

    async def post_inbound(self, channel_id: str, secret: str, body: dict) -> tuple[int, dict]:
        """Link (a): one signed intake POST. Returns (status, response json).
        The secret only ever feeds the HMAC; it is never logged or sent."""
        try:
            resp = await self._client.post(
                f"/v1/channels/{channel_id}/inbound",
                json=body,
                headers={"x-boltrig-signature": signature_header(secret, body)},
            )
        except Exception as exc:
            raise KernelLinkError(type(exc).__name__) from exc
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {}

    async def claim_outbox(self, *, limit: int = 10, lease_seconds: int = 30) -> list[dict]:
        """Link (b): claim a batch of due outbound deliveries for this token's
        channels. Raises KernelAuthError on 401, KernelLinkError otherwise."""
        resp = await self._link_post(
            "/v1/channels/gateway/outbox/claim",
            {"limit": limit, "lease_seconds": lease_seconds},
        )
        return list(resp.get("messages") or [])

    async def ack_outbox(self, message_id: str) -> bool:
        resp = await self._link_post(f"/v1/channels/gateway/outbox/{message_id}/ack", {})
        return resp.get("status") == "ok"

    async def fail_outbox(self, message_id: str, error: str) -> bool:
        resp = await self._link_post(
            f"/v1/channels/gateway/outbox/{message_id}/fail", {"error": error}
        )
        return resp.get("status") == "ok"

    async def _link_post(self, path: str, body: dict) -> dict:
        try:
            resp = await self._client.post(path, json=body, headers=self._token_headers())
        except Exception as exc:
            raise KernelLinkError(type(exc).__name__) from exc
        if resp.status_code == 401:
            raise KernelAuthError("run-scoped token refused")
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400:
            raise KernelLinkError(f"{path} -> {resp.status_code}")
        return data
