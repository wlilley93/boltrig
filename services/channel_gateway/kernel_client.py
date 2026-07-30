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
import itertools
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
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout
        )
        self._rpc_ids = itertools.count(1)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def has_token(self) -> bool:
        """Whether a token is currently loaded, without exposing its value."""
        return bool(self._token)

    def with_token(self, token: str) -> "KernelClient":
        """A non-owning view over the same transport with a narrower token."""
        return KernelClient("", token, client=self._client)

    def set_token(self, token: str) -> bool:
        """Replace this private client's short-lived run token.

        Return whether the value changed so the supervisor can distinguish a
        real file rotation from rereading the same expired token.
        """
        if not token or token == self._token:
            return False
        self._token = token
        return True

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

    async def reconcile_channels(self) -> dict:
        """Fetch this token's current desired channel specs.

        Resolved credentials are returned only over this authenticated link and
        remain in this daemon's memory.
        """
        return await self._link_get("/v1/channels/gateway/reconcile")

    async def heartbeat_channels(self, observations: list[dict[str, Any]]) -> dict:
        """Report bounded desired/observed convergence evidence to the kernel."""
        return await self._link_post(
            "/v1/channels/gateway/heartbeat",
            {"observations": observations},
        )

    async def ack_outbox(self, message_id: str) -> bool:
        resp = await self._link_post(f"/v1/channels/gateway/outbox/{message_id}/ack", {})
        return resp.get("status") == "ok"

    async def fail_outbox(self, message_id: str, error: str) -> bool:
        resp = await self._link_post(
            f"/v1/channels/gateway/outbox/{message_id}/fail", {"error": error}
        )
        return resp.get("status") == "ok"

    async def mcp_call(self, method: str, params: dict) -> dict:
        """One JSON-RPC call over the kernel's MCP face (``POST /v1/mcp``) on
        the SAME run-scoped token seam as link (b). This is how a socket-class
        adapter (the voice surface) discovers and invokes verbs: every call
        runs the kernel's unchanged chokepoint. Returns the full JSON-RPC
        response; raises KernelAuthError on 401, KernelLinkError otherwise."""
        return await self._link_post(
            "/v1/mcp",
            {
                "jsonrpc": "2.0",
                "id": next(self._rpc_ids),
                "method": method,
                "params": params,
            },
        )

    async def claim_call_media(self, call_id: str, media_token: str) -> dict:
        """Redeem the browser bearer once, under this token's channel ceiling."""
        return await self._link_post(
            "/v1/calls/gateway/claim",
            {"call_id": call_id, "media_token": media_token},
        )

    async def append_call_event(
        self,
        call_id: str,
        event_type: str,
        payload: dict,
        *,
        participant_id: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {"type": event_type, "payload": payload}
        if participant_id is not None:
            body["participant_id"] = participant_id
        return await self._link_post(f"/v1/calls/gateway/{call_id}/events", body)

    async def set_call_state(self, call_id: str, status: str) -> dict:
        return await self._link_post(
            f"/v1/calls/gateway/{call_id}/state", {"status": status}
        )

    async def get_call_hitl(self, call_id: str, request_id: str) -> dict:
        return await self._link_get(
            f"/v1/calls/gateway/{call_id}/hitl/{request_id}"
        )

    async def _link_get(self, path: str) -> dict:
        try:
            resp = await self._client.get(path, headers=self._token_headers())
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
