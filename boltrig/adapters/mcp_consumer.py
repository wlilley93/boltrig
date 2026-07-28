"""Consume an external MCP server as a Boltrig adapter (Round Two, US-MCP-03).

An ``mcp`` adapter connects to an external MCP server, registers its tools as
verbs via ``describe()``, and routes calls back out over MCP. Like any adapter,
its calls run the kernel chokepoint (grants, credentials, audit). A newly
registered MCP server is inert until reviewed and activated (the Round One review
gate, SEC-22): ``execute`` refuses until ``review_and_activate`` is called.

The bearer the adapter presents is NEVER held on the instance: it is resolved by
the kernel per call, from the credential seam, and handed to ``execute`` as
``credential`` (SEC-04/05, K-20 - credentials resolve inside the kernel only). A
call with no credential FAILS CLOSED rather than posting an empty bearer.

## Verb namespacing

Many apps register consumed servers under ONE kernel, so tool names are never
published verbatim: every discovered tool becomes ``<adapter_id>.<tool_name>``
(adapter ``opbox`` consuming ``matter.list`` publishes the verb
``opbox.matter.list`` under the noun ``opbox``). This keeps a consumed server
out of every other app's namespace and out of the reserved core prefixes
(``system.`` et al., ``control_safety._RESERVED_VERB_PREFIXES``) by
construction. Tools that cannot form a verb id after prefixing - empty, or
carrying characters outside the verb-id charset (the ``control_safety``
identifier convention: ASCII alphanumerics plus ``. _ -``) such as a ``/`` or
whitespace - are SKIPPED with a warning, never published: that honestly drops
presentation-layer meta-tools like Opbox's ``opbox/expand_tools``, which is
not a real verb. ``execute`` maps the prefixed verb id back to the BARE tool
name for ``tools/call``; the server never sees the prefix.

The HTTP mechanics - the dual credential headers, the lazy Streamable-HTTP
handshake, the server-issued session id, SSE decoding, and the
``allow_internal`` egress opt-in for operator-vetted internal servers - live in
``boltrig.adapters.mcp_transport``; this module is the adapter: verb mapping,
the review gate, and the error taxonomy.

httpx is imported lazily so the module is import-safe offline; a transport can be
injected for tests (and to let Boltrig consume its own MCP face).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from boltrig.adapters.base import (
    AdapterError,
    Credential,
    ErrorClass,
    Result,
    VerbSpec,
    bearer_token,
)
from boltrig.adapters.mcp_transport import McpHttpRefusal, StreamableHttp
from boltrig.addons import consequence_hint_for
from boltrig.models import Consequence, CredentialResolution, InvocationContext

log = logging.getLogger(__name__)

# rpc(request: dict) -> response: dict  (a JSON-RPC round-trip to the MCP server)
Rpc = Callable[[dict], Awaitable[dict]]

# The verb-id charset, mirroring the control_safety identifier convention
# (ASCII alphanumerics plus . _ -): applied to the PREFIXED id, so a tool name
# with a '/' (a presentation meta-tool like opbox/expand_tools), whitespace, or
# an empty name can never publish.
_TOOL_VERB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

# A consumed server may declare a per-tool ``consequence`` hint in the tool
# descriptor. The ceiling is the Consequence enum itself ("high" - the same
# ceiling generated adapters live under, where only mutating verbs reach high):
# an absent or unrecognised hint defaults to "low", so nothing a consumed server
# declares can push a verb above it.
_CONSEQUENCE_HINTS = frozenset({Consequence.LOW.value, Consequence.HIGH.value})

# A consumed server that declares no ``consequence`` field may still carry its own
# risk vocabulary somewhere in its tool projection. Reading THAT vocabulary is
# integration-specific KNOWLEDGE, so the regex lives in an addon
# (``boltrig.addons``) rather than in this module, which ships in every boltrig.
#
# It is consulted from every REGISTERED addon, not only the activated ones. A
# reading can only raise a consequence, so gating it on ``BOLTRIG_ADDONS`` bought
# no safety and cost the approval gate: measured, an opbox tool carrying
# ``riskClass=DESTRUCTIVE`` registered as ``low`` wherever the flag was unset.


def _status_error(status: int) -> ErrorClass:
    if status in (401, 403):
        return ErrorClass.UNAUTHORISED
    if status == 404:
        return ErrorClass.NOT_FOUND
    if status == 429:
        return ErrorClass.RATE_LIMITED
    if status >= 500:
        return ErrorClass.UNAVAILABLE
    return ErrorClass.INVALID


def _addon_hint(tool: dict) -> str | None:
    """The consumed server's own risk vocabulary, per every addon this build ships.

    REGISTERED, not active: a reading can only RAISE a consequence, so gating it on
    ``BOLTRIG_ADDONS`` bought nothing and cost the approval gate. See
    ``consequence_hint_for``.
    """
    return consequence_hint_for(None, tool)


def _annotations_hint(tool: dict) -> str | None:
    """Standard MCP tool annotations: destructiveHint -> high, readOnlyHint -> low."""
    annotations = tool.get("annotations")
    if not isinstance(annotations, dict):
        return None
    if annotations.get("destructiveHint") is True:
        return Consequence.HIGH.value
    return Consequence.LOW.value if annotations.get("readOnlyHint") is True else None


def _consequence_hint(tool: dict) -> str:
    # An explicit ``consequence`` declaration is the server's own contract and
    # wins outright (an unrecognised value clamps low, fail-closed).
    if tool.get("consequence") is not None:
        hint = str(tool.get("consequence") or "").lower()
        return hint if hint in _CONSEQUENCE_HINTS else Consequence.LOW.value
    # Otherwise take the HIGHEST of the remaining signals, never the first.
    # ``high`` is the tier that can require human approval (US-HIL-01), so
    # first-wins precedence let an addon's mapping return ``low`` for a tool whose
    # own MCP annotations declared ``destructiveHint: true`` and quietly drop it
    # below the approval gate. An addon is a reading of a server's vocabulary, not
    # an authority over it: it may RAISE a consequence and must never lower one.
    # No path returns above the Consequence ceiling.
    signals = (_addon_hint(tool), _annotations_hint(tool))
    if any(hint == Consequence.HIGH.value for hint in signals):
        return Consequence.HIGH.value
    return Consequence.LOW.value


class _McpFailure(Exception):
    """Internal carrier so a mapped error can bubble to ``execute``.

    ``AdapterError`` is a plain dataclass, so ``raise AdapterError(...)`` is a
    ``TypeError``, not a refusal. Mirrors ``http_base._HttpFailure``, which is the
    established way to carry one out of a helper and convert it at the boundary.
    """

    def __init__(self, error: AdapterError) -> None:
        super().__init__(error.message)
        self.error = error


class McpConsumerAdapter:
    runtime = "mcp"

    def __init__(
        self,
        id: str,
        *,
        url: str | None = None,
        rpc: Rpc | None = None,
        version: str = "1.0.0",
        source: str = "manual",
        allow_internal: bool = False,
    ) -> None:
        self.id = id
        self.version = version
        self.source = source
        self.activated = False  # review gate (SEC-22)
        self._url = url
        self._rpc = rpc
        self._specs: list[VerbSpec] = []
        # Prefixed verb id -> the server's BARE tool name (the namespacing map;
        # rebuilt by every connect()). Rebuilt per discovery, so a re-sync can
        # never leave a stale mapping.
        self._tools: dict[str, str] = {}
        # allow_internal is the registration-time, human-reviewed opt-in for an
        # operator-vetted INTERNAL server (SEC-22); it relaxes exactly one
        # egress check (see mcp_transport.StreamableHttp).
        self._transport = StreamableHttp(
            url or "", client_version=version, allow_internal=allow_internal
        )

    async def connect(self, credential: Credential | None = None) -> list[VerbSpec]:
        """Discover the external server's tools and map them to VerbSpecs.

        Discovery runs at ACTIVATION (``control.adapter.activate`` wires it), OUTSIDE
        a dispatch call, so no per-call credential exists yet: the caller passes one
        it resolved through the same kernel seam (``kernel.credentials.resolve_for_adapter``)
        that dispatch uses, after binding the adapter's credential. There is
        deliberately no instance-held token to fall back on, so this path cannot
        become a back door around the per-call credential. Each tool's declared
        ``consequence`` hint propagates to its VerbSpec (see ``_consequence_hint``).
        """
        resp = await self._call(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            bearer_token(credential),
        )
        tools = (resp.get("result") or {}).get("tools", [])
        specs: list[VerbSpec] = []
        self._tools = {}
        for t in tools:
            name = str(t.get("name") or "")
            verb_id = f"{self.id}.{name}"  # namespaced: see the module docstring
            if not name or not _TOOL_VERB_ID.fullmatch(verb_id):
                log.warning(
                    "mcp server '%s' tool %r skipped: not a verb id after "
                    "namespacing (a presentation meta-tool or an unsafe charset)",
                    self.id,
                    name,
                )
                continue
            self._tools[verb_id] = name
            specs.append(
                VerbSpec(
                    verb_id=verb_id,
                    noun_id=self.id,  # one noun per consumed server (opbox.*)
                    input_schema=t.get("inputSchema", {}),
                    # An MCP tool returns arbitrary JSON - an array, a string and a
                    # number are all legal results. Asserting `{"type": "object"}`
                    # here rejected every list-shaped tool at OUTPUT validation with
                    # `invalid output for '<verb>'`, long after the call had already
                    # succeeded downstream: opbox's `list_matters` really did return
                    # the caller's matters and the kernel then threw the answer away.
                    # Honour the server's own `outputSchema` when it declares one,
                    # otherwise accept any JSON rather than inventing a constraint
                    # the protocol does not make.
                    output_schema=t.get("outputSchema") or {},
                    description=t.get("description", ""),
                    consequence=_consequence_hint(t),
                )
            )
        self._specs = specs
        return self._specs

    def describe(self) -> list[VerbSpec]:
        return list(self._specs)

    def review_and_activate(self, reviewer: str) -> "McpConsumerAdapter":
        """Human review gate (SEC-22): activate the consumed server for dispatch."""
        self.activated = True
        return self

    async def execute(
        self, verb: str, params: dict, credential: Credential | None, context: InvocationContext
    ) -> Result:
        try:
            return await self._execute(verb, params, credential)
        except _McpFailure as failure:
            return Result.failure(failure.error)
        except Exception as exc:  # a bad adapter must never crash the kernel (US-ADP-06)
            return Result.failure(
                AdapterError(ErrorClass.INTERNAL, f"adapter error: {type(exc).__name__}")
            )

    async def _execute(
        self, verb: str, params: dict, credential: Credential | None
    ) -> Result:
        if not self.activated:  # inert until reviewed (defence in depth, SEC-22)
            return Result.failure(
                AdapterError(ErrorClass.UNAVAILABLE, "mcp server pending review")
            )
        # The kernel-resolved credential is the ONLY bearer source: no instance
        # token, so rotation and per-run scoping are live and a missing
        # credential fails closed rather than posting an empty bearer.
        if self._rpc is None and bearer_token(credential) is None:
            return Result.failure(
                AdapterError(ErrorClass.UNAUTHORISED, "mcp credential missing")
            )
        # The prefixed verb id maps back to the server's BARE tool name - the
        # server never sees the namespace. The prefix strip is deterministic,
        # so a boot-rehydrated consumer (activated, not yet re-connected) also
        # calls correctly before any re-discovery.
        name = self._tools.get(verb) or (
            verb[len(self.id) + 1:] if verb.startswith(f"{self.id}.") else verb
        )
        resp = await self._call(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": name, "arguments": params}},
            bearer_token(credential),
        )
        result = resp.get("result") or {}
        boltrig = result.get("_boltrig") or {}
        if result.get("isError"):
            return Result.failure(
                AdapterError(ErrorClass.INVALID, boltrig.get("reason") or "mcp tool error")
            )
        output = boltrig.get("output")
        if output is None:
            # A non-Boltrig MCP server returns the standard content array, not a
            # _boltrig envelope: fall back to mapping its text blocks into output.
            texts = [
                block["text"]
                for block in result.get("content") or []
                if isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ]
            output = {"text": "\n".join(texts)} if texts else {}
        return Result.success(output)

    async def health(self) -> str:
        return "ok" if self._specs else "unknown"

    async def _call(self, request: dict, bearer: str | None) -> dict:
        if self._rpc is not None:
            # Injected in-process transport (tests, self-consumption): it owns its
            # own auth, so no bearer is derived or sent here.
            return await self._rpc(request)
        if not bearer:
            # Fail closed (defence in depth behind execute's own check, and the
            # guard for connect()): never post an empty bearer, which would be an
            # unauthenticated request.
            raise CredentialResolution(f"no mcp credential resolved for '{self.id}'")
        from boltrig.adapters.egress import EgressBlocked

        # SSRF (SEC-61, H2): pin the connection to the vetted IP before
        # posting - this path carries the MCP bearer token, so httpx re-resolving
        # to internal space would both reach internal services AND leak the token.
        # pinned_async_client forces follow_redirects=False. allow_internal (the
        # reviewed registration opt-in) is the ONLY waiver, for an
        # operator-vetted internal server.
        try:
            client = self._transport.pinned_client()
        except EgressBlocked as exc:
            raise _McpFailure(
                AdapterError(ErrorClass.INVALID, str(exc), retryable=False)
            ) from exc
        async with client:
            try:
                return await self._transport.call(client, request, bearer)
            except McpHttpRefusal as refusal:
                raise _McpFailure(
                    AdapterError(
                        _status_error(refusal.status),
                        str(refusal),  # status only - the body never crosses
                        retryable=refusal.status == 429 or refusal.status >= 500,
                    )
                ) from refusal


def build() -> Any:  # loader hook; real config comes from the mcp_servers table
    return McpConsumerAdapter(id="mcp-consumer")
