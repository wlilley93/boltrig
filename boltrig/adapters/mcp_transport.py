"""The MCP Streamable-HTTP client transport the consumer speaks (US-MCP-03).

One HTTP shape serves strict MCP Streamable-HTTP servers AND plain JSON-RPC
doors (the Opbox kernel's ``POST /mcp`` and Boltrig's own MCP face are both the
plain kind):

  * Every POST carries ``Accept: application/json, text/event-stream`` and BOTH
    credential conventions for the same kernel-resolved token:
    ``Authorization: Bearer <token>`` (the spec convention - the only header the
    Opbox door reads) and ``x-boltrig-mcp-token: <token>`` (the Boltrig face's
    convention; it also accepts the bearer form). The token is never logged.
  * The handshake is LAZY: the plain call goes out first. Only a 400/404 - how
    a strict server says "no live session" (no ``initialize`` yet, or an
    expired/unknown ``Mcp-Session-Id``) - triggers the one handshake
    (``initialize`` + a best-effort ``notifications/initialized``) and ONE
    retry of the call. A server that answers plain calls never sees a
    handshake; a server that refuses ``initialize`` is used session-less. A
    session id returned as the ``Mcp-Session-Id`` response header is carried on
    every later POST.
  * A response framed ``text/event-stream`` (SSE) is decoded to the JSON-RPC
    payload it carries; a plain JSON body is read as before.
  * Any other HTTP refusal raises :class:`McpHttpRefusal` carrying only the
    STATUS - never the response body, which can echo the request (credential
    headers included) back. The caller maps the status onto its error taxonomy.

The transport holds NO credential: the bearer is passed per call. It holds only
the server-issued session id - transport state, not secret material.

httpx is imported lazily (via the egress module) so the module is import-safe
offline; a client can be injected for tests.
"""

from __future__ import annotations

import json
from typing import Any

# The protocol revision offered in `initialize`. A server answers with the
# revision IT speaks; the methods used here (initialize, tools/list, tools/call)
# are stable across the dated revisions, so the answer is not negotiated further.
_PROTOCOL_VERSION = "2025-06-18"

_ACCEPT = "application/json, text/event-stream"
_SESSION_HEADER = "mcp-session-id"

# How a strict Streamable-HTTP server says "no live session": no initialize yet
# (400) or an expired/unknown Mcp-Session-Id (404). Either earns ONE handshake +
# retry; any other status is a real refusal, surfaced as McpHttpRefusal.
_SESSION_STATUSES = frozenset({400, 404})


class McpHttpRefusal(Exception):
    """A final (post-retry) HTTP refusal, carrying ONLY the status code: the
    body can echo the request back, credential headers included, so it never
    crosses this boundary. The consumer maps the status onto ErrorClass."""

    def __init__(self, status: int) -> None:
        super().__init__(f"mcp server refused the call (HTTP {status})")
        self.status = status


def _decode_sse(body: str) -> dict:
    """The JSON-RPC response carried by an SSE-framed body: the last ``data``
    event holding a result/error (earlier events may be notifications)."""
    found: dict | None = None
    for event in body.split("\n\n"):
        data = "\n".join(
            line.removeprefix("data:").lstrip()
            for line in event.splitlines()
            if line.startswith("data:")
        )
        if not data:
            continue
        try:
            payload = json.loads(data)
        except ValueError:
            continue
        if isinstance(payload, dict) and ("result" in payload or "error" in payload):
            found = payload
    if found is None:
        raise ValueError("no JSON-RPC response in the mcp event stream")
    return found


class StreamableHttp:
    """One MCP server's HTTP transport: the pinned client, header conventions,
    the lazy handshake, the server-issued session id, and SSE decoding.

    ``allow_internal`` is the registration-time, human-reviewed opt-in for an
    operator-vetted INTERNAL service (``control.mcp_server.register`` + the
    SEC-22 review gate): it is forwarded to the egress guard, which otherwise
    refuses any internal target (SEC-61). It must never be set for an
    agent-influenced URL.

    ``network_config`` is the manifest NetworkConfig (air-gap / allow/block
    lists, SEC-52): the operator's egress posture binds the MCP server leg,
    which is ordinary outbound HTTP, not just web.fetch.
    """

    def __init__(
        self,
        url: str,
        *,
        client_version: str,
        allow_internal: bool = False,
        network_config: dict[str, Any] | None = None,
    ) -> None:
        self._url = url
        self._client_version = client_version
        self._allow_internal = allow_internal
        self._network_config = dict(network_config) if network_config else None
        self._session_id: str | None = None

    @property
    def allow_internal(self) -> bool:
        """Whether the reviewed internal-server egress waiver is on (read-only)."""
        return self._allow_internal

    def pinned_client(self) -> Any:
        """The SSRF-pinned client for this server (H2/SEC-61): vetted and pinned
        to the audited IP, ``follow_redirects=False``. Raise
        ``egress.EgressBlocked`` when the guard refuses the target. The config
        kwarg is passed ONLY when one is in effect (the manifest posture, the
        ``allow_internal`` opt-in, or both), so the plain call signature (and
        the guard's defaults) is unchanged for every other consumer."""
        from boltrig.adapters.egress import pinned_async_client

        config = dict(self._network_config or {})
        if self._allow_internal:
            config["allow_internal"] = True
        if config:
            return pinned_async_client(self._url, config, timeout=30.0)
        return pinned_async_client(self._url, timeout=30.0)

    async def call(self, client: Any, request: dict, bearer: str) -> dict:
        """One JSON-RPC round trip over an injected pinned client."""
        return await self._post(client, request, bearer)

    def _headers(self, bearer: str) -> dict:
        # BOTH credential conventions for the same kernel-resolved token: a spec
        # server reads Authorization (it is the only header the Opbox /mcp door
        # reads); the Boltrig face prefers its own header and also accepts the
        # bearer form. The token never enters a log line or an error message.
        headers = {
            "Accept": _ACCEPT,
            # A compressed body allocates its DECODED size inside httpx before
            # any application-level bound can see it, so a small response can
            # cost gigabytes of memory. ``http_response.bounded_http_response``
            # forces identity for every other outbound adapter for exactly this
            # reason; the MCP transport did not, and a page loop would multiply
            # the exposure by the page ceiling.
            "Accept-Encoding": "identity",
            "Authorization": f"Bearer {bearer}",
            "x-boltrig-mcp-token": bearer,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _post(self, client: Any, request: dict, bearer: str, *, retried: bool = False) -> dict:
        r = await client.post(self._url, json=request, headers=self._headers(bearer))
        if r.status_code < 400:
            session = r.headers.get(_SESSION_HEADER)
            if session:
                self._session_id = session
            return self._decode(r)
        if r.status_code in _SESSION_STATUSES and not retried:
            # No live session on a strict server: run the ONE handshake, then
            # retry the call once. The refused first attempt never executed
            # (the refusal is the transport's, ahead of dispatch), so the retry
            # is not a replay. Bounded by `retried`; a repeated refusal raises.
            self._session_id = None
            await self._handshake(client, bearer)
            return await self._post(client, request, bearer, retried=True)
        raise McpHttpRefusal(r.status_code)

    async def _handshake(self, client: Any, bearer: str) -> None:
        """The MCP handshake, run lazily when a server demands a session.

        A strict Streamable-HTTP server answers ``initialize`` with a result
        and usually an ``Mcp-Session-Id`` to carry from then on; a plain door
        that refuses or cannot answer it is used session-less. Never raises (a
        transport fault re-surfaces on the retried call, typed by the caller's
        catch-all) and never logs - the bearer is on the wire here too.
        """
        try:
            r = await client.post(
                self._url,
                json={
                    "jsonrpc": "2.0", "id": 0, "method": "initialize",
                    "params": {
                        "protocolVersion": _PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {
                            "name": "boltrig-mcp-consumer",
                            "version": self._client_version,
                        },
                    },
                },
                headers=self._headers(bearer),
            )
            payload = self._decode(r)
        except Exception:  # a refused/undecodable initialize: plain convention
            return
        if r.status_code >= 400 or not isinstance(payload, dict) or "result" not in payload:
            return
        session = r.headers.get(_SESSION_HEADER)
        if session:
            self._session_id = session
        try:  # best-effort: strict servers 202 it; a plain door may refuse it
            await client.post(
                self._url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=self._headers(bearer),
            )
        except Exception:  # the initialized notification is advisory
            pass

    @staticmethod
    def _decode(response: Any) -> dict:
        # A strict Streamable-HTTP server may frame the JSON-RPC payload as an
        # SSE stream instead of returning a plain JSON body.
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            return _decode_sse(response.text)
        return response.json()
