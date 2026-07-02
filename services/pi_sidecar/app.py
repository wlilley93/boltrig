"""The Pi sidecar service (Round Two, Epic RUN; SRS S5.3).

A STANDALONE reasoning-loop service reached over HTTP by Boltrig's PiRuntime.
It is deliberately NOT part of the ``boltrig`` package: ``boltrig/kernel`` and
``boltrig/models`` import nothing from here (severability, court-blessed). The
only coupling is the wire protocol below.

What it is (US-RUN-02, US-RUN-03)
    A thin agent loop: call a pinned model, let it either speak (text) or call a
    tool, run the tool over a scoped MCP connection, feed the result back, repeat
    up to ``limits.max_steps``, then return a ``final`` event.

Sandboxing (SEC-24, SEC-27)
    The sidecar's ONLY tools are kernel verbs reached through the run-scoped MCP
    connection. It has no native filesystem / process / credential / network
    tools of its own. It never receives a tool credential, only a model key and
    a run-scoped MCP token; neither is ever echoed into an event or a log. Egress
    must be restricted (at the container / network layer) to the kernel MCP
    endpoint and the model endpoint only.

Offline-safety (P9, US-RUN-05)
    A missing / unreachable model endpoint, a missing api key, or an unreachable
    MCP face never crashes a request. The loop degrades to a clearly-marked
    ``final`` event and always returns 200 with a well-formed stream.

Where a real Pi loop slots in
    ``run_loop`` is the integration point. A real Pi open-source agent loop would
    replace the body of ``run_loop`` while keeping the same inputs (the composed
    prompt, the MCP-derived tool list, the model config) and emitting the same
    event stream. We implement the loop directly so the service works with no
    external Pi package installed.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import re
import socket
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Tunables (offline-safe defaults; no secrets here).
# ---------------------------------------------------------------------------

_MCP_TIMEOUT = float(os.environ.get("PI_SIDECAR_MCP_TIMEOUT", "30"))
_MODEL_TIMEOUT = float(os.environ.get("PI_SIDECAR_MODEL_TIMEOUT", "60"))
_DEFAULT_MAX_STEPS = 12
# Rough cost so accounting is never blank when the model reports usage but no
# price. Best-effort only (cost may legitimately be 0). Millionths per token.
_MICROS_PER_TOKEN = int(os.environ.get("PI_SIDECAR_MICROS_PER_TOKEN", "0"))

_MCP_TOKEN_HEADER = "x-boltrig-mcp-token"

# The shared secret for POST /run (M2 / SEC-73). When set, every /run request must
# carry a matching bearer. When UNSET the sidecar runs open in dev only; under a
# production signal it fails closed (mirrors the kernel's BOLTRIG_DEV_AUTH posture).
_RUN_TOKEN_ENV = "PI_SIDECAR_TOKEN"
_PROD_SIGNALS = {"prod", "production", "live"}


# ---------------------------------------------------------------------------
# M1 (SEC-72): the untrusted-input envelope, vendored locally.
#
# A tool result comes from an external MCP verb / the open web via web.fetch and is
# attacker-controllable, so it is wrapped in a typed envelope before it is fed back
# to the model as a tool message. This is a deliberate local copy of the fleet's
# ``wrap_untrusted`` helper: the sidecar is a SEVERED service and must NOT import
# ``boltrig.*`` (SEC-28), so the ~10 lines are duplicated rather than shared.
# ---------------------------------------------------------------------------

_UNTRUSTED_TAG_RE = re.compile(r"<(?=\s*/?\s*untrusted\b)", re.IGNORECASE)
_ATTR_UNSAFE_RE = re.compile(r'[<>"\r\n]')


def _wrap_untrusted(kind: str, source: str, content: str) -> str:
    """Wrap an untrusted span in ``<untrusted kind=".." source="..">..</untrusted>``,
    defanging any literal ``untrusted`` delimiter inside the payload so it cannot
    break out of the envelope (M1). The governance floor (req.system) tells the model
    envelope content is data, never instructions."""
    body = _UNTRUSTED_TAG_RE.sub("&lt;", content or "")
    safe_kind = _ATTR_UNSAFE_RE.sub("_", str(kind))
    safe_source = _ATTR_UNSAFE_RE.sub("_", str(source))
    return f'<untrusted kind="{safe_kind}" source="{safe_source}">{body}</untrusted>'


# ---------------------------------------------------------------------------
# M2 (SEC-73): request auth + a local egress guard.
#
# The egress guard is likewise a minimal local implementation (no ``boltrig``
# import): before the sidecar connects to a caller-supplied mcp.url / model.endpoint
# it refuses any host that resolves to metadata / loopback / private / link-local /
# reserved space, closing an SSRF pivot from the sidecar's network position.
# ---------------------------------------------------------------------------


def _production_signal() -> str | None:
    """A best-effort production signal (mirrors the kernel's detection)."""
    if (os.environ.get("BOLTRIG_PRODUCTION") or "").strip().lower() in {"1", "true", "yes", "on"}:
        return "BOLTRIG_PRODUCTION"
    for key in ("ENV", "BOLTRIG_ENV", "APP_ENV"):
        val = (os.environ.get(key) or "").strip().lower()
        if val in _PROD_SIGNALS:
            return f"{key}={val}"
    return None


def check_run_auth(request: Request) -> JSONResponse | None:
    """Authenticate a /run request against the shared secret (M2 / SEC-73).

    Returns a refusal response, or ``None`` when the request may proceed. Uses a
    constant-time compare so a bearer cannot be discovered by timing."""
    token = os.environ.get(_RUN_TOKEN_ENV)
    if not token:
        # No shared secret configured: open in dev, fail CLOSED under a prod signal.
        signal = _production_signal()
        if signal is not None:
            return JSONResponse(
                {"error": f"sidecar auth not configured under a production signal ({signal})"},
                status_code=503,
            )
        return None  # dev default (documented): unauthenticated /run is dev-only
    header = request.headers.get("authorization", "")
    presented = header[7:] if header[:7].lower() == "bearer " else header
    if not presented or not hmac.compare_digest(presented, token):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


def _is_metadata_or_loopback_ip(ip: str) -> bool:
    """The always-unsafe subset: link-local (incl. 169.254.169.254 cloud metadata),
    loopback, unspecified. NEVER a legitimate sidecar target, so it is refused even
    for an allow-listed host. Unparseable fails closed."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_link_local or addr.is_loopback or addr.is_unspecified


def _is_blocked_ip(ip: str) -> bool:
    """True if an address must be refused by default: private / loopback / link-local
    (incl. 169.254.169.254 cloud metadata) / reserved / multicast / unspecified. An
    unparseable address fails closed."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


def _egress_allowlist() -> set[str]:
    """Operator-configured hosts permitted on the private network (the kernel MCP
    face and the model endpoint). Comma-separated in ``PI_SIDECAR_EGRESS_ALLOW``.
    The metadata/loopback subset is refused even for an allow-listed host."""
    raw = os.environ.get("PI_SIDECAR_EGRESS_ALLOW", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def egress_refusal(url: str | None) -> str | None:
    """Return a refusal reason if ``url`` is not a safe outbound target, else None
    (M2 / SEC-73). Refuses non-http(s) schemes, unresolvable hosts (fail-closed),
    metadata/loopback always, and every other internal/private address unless the
    host is on the operator allow-list (the sidecar's legitimate kernel-MCP / model
    targets live on a private container network, so a blanket RFC1918 block would
    break normal runs; the allow-list is the documented, fail-safe escape hatch)."""
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return f"unsupported scheme '{parsed.scheme}'"
    host = parsed.hostname
    if not host:
        return "no host in url"
    host_l = host.lower()
    allow = _egress_allowlist()
    allowlisted = any(host_l == a or host_l.endswith("." + a) for a in allow)
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return "host did not resolve"
    ips = {info[4][0] for info in infos}
    if not ips:
        return "host did not resolve"
    for ip in ips:
        if _is_metadata_or_loopback_ip(ip):
            return f"target resolves to a metadata/loopback address ({ip})"
        if not allowlisted and _is_blocked_ip(ip):
            return f"target resolves to a non-routable/internal address ({ip})"
    return None


def check_run_egress(req: RunRequest) -> JSONResponse | None:
    """Refuse a /run whose mcp.url or model.endpoint resolves to internal space,
    BEFORE any outbound connection is made (M2 / SEC-73)."""
    for label, url in (("mcp.url", req.mcp.url), ("model.endpoint", req.model.endpoint)):
        reason = egress_refusal(url)
        if reason:
            return JSONResponse(
                {"error": f"egress refused for {label}: {reason}"}, status_code=403
            )
    return None


# ---------------------------------------------------------------------------
# Request models (SRS S5.3 POST /run body).
# ---------------------------------------------------------------------------


class McpConfig(BaseModel):
    """The run-scoped MCP connection the kernel issued for this run (SEC-23)."""

    url: str
    token: str


class ModelConfig(BaseModel):
    """The pinned model for this run (P4). ``endpoint`` / ``api_key`` may be null."""

    endpoint: str | None = None
    name: str = ""
    api_key: str | None = None


class Limits(BaseModel):
    """Per-run guardrails (US-RUN-03)."""

    max_steps: int = _DEFAULT_MAX_STEPS


class RunRequest(BaseModel):
    """The ``POST /run`` request body (SRS S5.3)."""

    prompt: str
    # kernel-composed governance floor + tier character; prepended to the loop
    # system prompt so the cage is authoritative on the agentic lane (Corporate
    # Brain III/V). None when the caller is a human / has no agent character.
    system: str | None = None
    mcp: McpConfig
    model: ModelConfig = Field(default_factory=ModelConfig)
    limits: Limits = Field(default_factory=Limits)


# ---------------------------------------------------------------------------
# The MCP client (JSON-RPC 2.0 over HTTP; the ONLY tool surface, SEC-24).
# ---------------------------------------------------------------------------


class McpError(Exception):
    """The MCP face was unreachable or returned a transport-level error."""


class McpClient:
    """A thin JSON-RPC 2.0 client for the kernel MCP face.

    The connection is scoped by ``token`` (skill grants intersect tenant ceiling,
    SEC-23): the tool list and every ``tools/call`` are least-privilege by
    construction. The token is sent only in the ``x-boltrig-mcp-token`` header and
    is never logged or placed into an event (SEC-27).
    """

    def __init__(self, url: str, token: str) -> None:
        self._url = url
        self._token = token
        self._client = httpx.AsyncClient(timeout=_MCP_TIMEOUT)
        self._next_id = 0

    async def __aenter__(self) -> McpClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _rpc_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def _call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """One JSON-RPC round trip. Raises ``McpError`` on transport failure."""
        body = {"jsonrpc": "2.0", "id": self._rpc_id(), "method": method, "params": params or {}}
        try:
            resp = await self._client.post(
                self._url, json=body, headers={_MCP_TOKEN_HEADER: self._token}
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except Exception as exc:  # network / TLS / parse -> a clean MCP error
            raise McpError(type(exc).__name__) from exc
        if "error" in data and data["error"]:
            err = data["error"]
            raise McpError(f"{err.get('code')}: {err.get('message')}")
        return data.get("result") or {}

    async def initialize(self) -> dict[str, Any]:
        """MCP ``initialize`` then the ``notifications/initialized`` nudge."""
        result = await self._call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "boltrig-pi-sidecar", "version": "0.1.0"},
            },
        )
        try:  # best-effort; the kernel face treats it as a no-op
            await self._call("notifications/initialized")
        except McpError:
            pass
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        """``tools/list`` -> the granted-only tool set (FR-MCP-02, SEC-23)."""
        result = await self._call("tools/list")
        tools = result.get("tools") or []
        return [t for t in tools if isinstance(t, dict) and t.get("name")]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """``tools/call`` -> the raw MCP result (includes ``_boltrig``)."""
        return await self._call("tools/call", {"name": name, "arguments": arguments})


def _tool_outcome(mcp_result: dict[str, Any]) -> tuple[str, Any]:
    """Map a raw MCP ``tools/call`` result to ``(status, payload)``.

    The kernel face annotates every result with ``_boltrig.status`` (one of
    ``ok`` / ``pending_human`` / ``denied`` / ``degraded`` / ``error``). We honour
    that as the source of truth and pull the matching payload field so the loop
    can surface it (a ``tool_result`` event) and the model can read it back.
    """
    meta = mcp_result.get("_boltrig") or {}
    status = str(meta.get("status") or ("error" if mcp_result.get("isError") else "ok"))
    if status == "ok":
        return "ok", meta.get("output")
    if status == "pending_human":
        return "pending_human", {"hitl_request_id": meta.get("hitl_request_id")}
    if status == "degraded":
        return "degraded", {"output": meta.get("output")}
    # denied / error / anything else: a reason string is the useful payload.
    return status, {"reason": meta.get("reason") or _content_text(mcp_result)}


def _content_text(mcp_result: dict[str, Any]) -> str:
    """Best-effort flatten of MCP ``content`` blocks to a string for the model."""
    out: list[str] = []
    for block in mcp_result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            out.append(str(block.get("text", "")))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The model client (OpenAI-compatible chat/completions with tools).
# ---------------------------------------------------------------------------


class ModelError(Exception):
    """The model endpoint was unreachable or returned an error."""


def _to_openai_tools(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert MCP tools into OpenAI ``tools`` function specs (the ONLY tools)."""
    tools: list[dict[str, Any]] = []
    for t in mcp_tools:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description") or t["name"],
                    "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
                },
            }
        )
    return tools


async def _chat_completion(
    model: ModelConfig, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
) -> dict[str, Any]:
    """One OpenAI-compatible ``{endpoint}/chat/completions`` call.

    The api key is sent only as a Bearer header, never logged. Raises
    ``ModelError`` on any transport / status / parse failure so the caller can
    degrade (P9).
    """
    if not model.endpoint:
        raise ModelError("no_endpoint")
    url = f"{model.endpoint.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {"model": model.name, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    headers = {"Content-Type": "application/json"}
    if model.api_key:
        headers["Authorization"] = f"Bearer {model.api_key}"
    try:
        async with httpx.AsyncClient(timeout=_MODEL_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:  # network / status / parse -> degrade upstream
        raise ModelError(type(exc).__name__) from exc


def _parse_choice(data: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Return ``(assistant_message, total_tokens)`` from a chat response."""
    try:
        message: dict[str, Any] = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        message = {"role": "assistant", "content": ""}
    usage = data.get("usage") or {}
    tokens = int(usage.get("total_tokens") or 0)
    return message, tokens


# ---------------------------------------------------------------------------
# Event helpers (newline-delimited JSON; SRS S5.3 event shapes).
# ---------------------------------------------------------------------------


def _event(payload: dict[str, Any]) -> str:
    """Serialise one event as a newline-delimited JSON line."""
    return json.dumps(payload, separators=(",", ":")) + "\n"


def _final_event(
    *,
    output: Any,
    summary: str,
    tokens_used: int = 0,
    cost_micros: int = 0,
    new_work_items: list[Any] | None = None,
) -> str:
    return _event(
        {
            "type": "final",
            "output": output,
            "summary": summary,
            "tokens_used": tokens_used,
            "cost_micros": cost_micros,
            "new_work_items": new_work_items or [],
        }
    )


# ---------------------------------------------------------------------------
# The reasoning loop (US-RUN-02, US-RUN-03) + offline-safe degrade (US-RUN-05).
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a Boltrig worker agent. Your only available tools are the kernel "
    "verbs provided to you. Use them to accomplish the task, then give a short "
    "final answer. Do not assume any other capabilities."
)


async def run_loop(req: RunRequest) -> AsyncIterator[str]:
    """Drive the agent loop and yield newline-delimited JSON events.

    This is the Pi integration point (see module docstring). It NEVER raises to
    the client: every failure path yields a well-formed ``final`` event.
    """
    # 1) Connect to the MCP face and discover the (only) tools (SEC-24).
    mcp = McpClient(req.mcp.url, req.mcp.token)
    try:
        await mcp.initialize()
        mcp_tools = await mcp.list_tools()
    except McpError as exc:
        await mcp.aclose()
        yield _final_event(
            output={"_degraded": {"reason": "mcp_unreachable", "detail": str(exc)}},
            summary="MCP face unreachable; nothing was done.",
        )
        return

    tool_names = [t["name"] for t in mcp_tools]

    # 2) Offline-safe path: no model endpoint or no api key -> deterministic
    #    degrade. We still surfaced the tool list, so the caller learns what the
    #    run *could* have done (P9, US-RUN-05).
    if not req.model.endpoint or not req.model.api_key:
        reason = "no_model" if not req.model.endpoint else "no_api_key"
        yield _event(
            {
                "type": "reasoning_delta",
                "delta": (
                    "No reachable model (" + reason + "); running in degraded, "
                    "no-model mode. Available tools: " + ", ".join(tool_names) + "."
                ),
            }
        )
        await mcp.aclose()
        yield _final_event(
            output={"_degraded": {"reason": "no_model", "available_tools": tool_names}},
            summary="Degraded: no model configured; listed tools only.",
        )
        return

    # 3) The live loop. The kernel-composed floor + character (req.system) is
    # authoritative and comes FIRST, then the sidecar's own loop mechanics.
    openai_tools = _to_openai_tools(mcp_tools)
    system_content = f"{req.system}\n\n{_SYSTEM_PROMPT}" if req.system else _SYSTEM_PROMPT
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": req.prompt},
    ]
    tokens_used = 0
    new_work_items: list[Any] = []
    max_steps = max(1, req.limits.max_steps)
    last_text = ""

    try:
        for _step in range(max_steps):
            try:
                data = await _chat_completion(req.model, messages, openai_tools)
            except ModelError as exc:
                yield _final_event(
                    output={"_degraded": {"reason": "model_unreachable", "detail": str(exc)}},
                    summary="Model became unreachable mid-run; stopped.",
                    tokens_used=tokens_used,
                )
                return

            message, step_tokens = _parse_choice(data)
            tokens_used += step_tokens

            reasoning = message.get("reasoning_content") or message.get("reasoning")
            if reasoning:
                yield _event({"type": "reasoning_delta", "delta": str(reasoning)})

            tool_calls = message.get("tool_calls") or []
            text = message.get("content") or ""

            if not tool_calls:
                # The model produced a final answer.
                if text:
                    last_text = str(text)
                    yield _event({"type": "text_delta", "delta": last_text})
                break

            # Record the assistant turn (with its tool calls) before the results.
            messages.append(message)

            paused = False
            for call in tool_calls:
                fn = (call.get("function") or {}) if isinstance(call, dict) else {}
                verb = str(fn.get("name") or "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    arguments = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except (ValueError, TypeError):
                    arguments = {}

                yield _event(
                    {"type": "tool_call", "verb": verb, "input": arguments, "status": "running"}
                )

                try:
                    mcp_result = await mcp.call_tool(verb, arguments)
                except McpError as exc:
                    status, payload = "error", {"reason": str(exc)}
                    mcp_result = {}
                else:
                    status, payload = _tool_outcome(mcp_result)

                yield _event(
                    {"type": "tool_result", "verb": verb, "status": status, "output": payload}
                )

                if status == "ok" and "create" in verb:
                    new_work_items.append({"verb": verb, "output": payload})

                # Feed the result back to the model as a tool message. The result is
                # attacker-controllable (an external MCP verb / web.fetch output), so
                # it is wrapped in a typed untrusted envelope (M1 / SEC-72): the model
                # treats it as DATA per the governance floor and a hostile payload
                # (e.g. an embedded "</untrusted>") cannot break out of the envelope.
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") if isinstance(call, dict) else None,
                        "name": verb,
                        "content": _wrap_untrusted(
                            "tool_result",
                            verb,
                            json.dumps({"status": status, "output": payload}),
                        ),
                    }
                )

                if status == "pending_human":
                    paused = True
                    last_text = (
                        "Paused for human approval (request "
                        + str((payload or {}).get("hitl_request_id"))
                        + ")."
                    )
                    break

            if paused:
                yield _final_event(
                    output={
                        "_paused": {
                            "reason": "pending_human",
                            "hitl_request_id": (payload or {}).get("hitl_request_id"),
                            "verb": verb,
                        }
                    },
                    summary=last_text,
                    tokens_used=tokens_used,
                    cost_micros=tokens_used * _MICROS_PER_TOKEN,
                    new_work_items=new_work_items,
                )
                return
        else:
            # max_steps exhausted with no final answer from the model.
            last_text = last_text or "Step budget exhausted before a final answer."

        yield _final_event(
            output={"text": last_text},
            summary=last_text[:256],
            tokens_used=tokens_used,
            cost_micros=tokens_used * _MICROS_PER_TOKEN,
            new_work_items=new_work_items,
        )
    except Exception as exc:  # last-resort guard: never raise to the client (P9)
        yield _final_event(
            output={"_degraded": {"reason": "sidecar_error", "detail": type(exc).__name__}},
            summary="Unexpected sidecar error; degraded.",
            tokens_used=tokens_used,
            new_work_items=new_work_items,
        )
    finally:
        await mcp.aclose()


# ---------------------------------------------------------------------------
# FastAPI surface. Importing / instantiating the app needs no live kernel or
# model (those are per-request only); the app is runnable via `uvicorn app:app`.
# ---------------------------------------------------------------------------

app = FastAPI(title="Boltrig Pi Sidecar", version="0.1.0")


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness probe (no kernel / model dependency)."""
    return JSONResponse({"status": "ok"})


@app.post("/run")
async def run(req: RunRequest, request: Request) -> Response:
    """Run one agent loop and stream newline-delimited JSON events (SRS S5.3).

    Two security gates run BEFORE any work (M2 / SEC-73): the shared-secret bearer
    check, then the egress guard over the caller-supplied mcp.url / model.endpoint.
    Either gate returns a refusal (401 / 403 / 503) with no outbound connection. A
    permitted run then streams as before - always 200 with a well-formed stream;
    backend failures degrade into the final event rather than raise (P9, US-RUN-05).
    """
    auth_refusal = check_run_auth(request)
    if auth_refusal is not None:
        return auth_refusal
    egress_refusal_resp = check_run_egress(req)
    if egress_refusal_resp is not None:
        return egress_refusal_resp
    return StreamingResponse(run_loop(req), media_type="application/x-ndjson")
