"""Enforce a cell's tool ceiling on the model-call wire, and bridge Codex's MCP
tool namespace across a gateway that cannot carry it (the one chokepoint).

Codex 0.144.3 offers its built-in tools (``exec_command``, ``write_stdin``,
``update_plan``, ``request_user_input``, ``view_image``) on every turn, and
``config.toml`` cannot suppress them: the reviewed ``[tools]`` table accepts only
``web_search`` and ``experimental_request_user_input``. So a cell configured
``approval_policy = "never"`` would hand the model an unapproved shell inside the
kernel container, and any shell child - being a descendant of the App Server -
also satisfies the ancestry attestation on the bearer ingress. The per-cell
loopback proxy is the only point both sides must traverse, so the ceiling is
applied here rather than trusted to the runtime's own config. Fail-closed: a body
we cannot parse is a body whose tool set we cannot verify, so it is rejected.

The MCP-namespace bridge (why this module also rewrites, not just filters):
Codex presents the kernel's MCP server to the model as ONE Responses entry
``{"type":"namespace","name":"mcp__boltrig","tools":[<function tools>]}``. A
gateway that translates the Responses API to a provider with no namespace concept
(here Bifrost -> the Anthropic-shaped z.ai endpoint) COLLAPSES that whole
namespace into a single opaque ``mcp__boltrig`` tool, so the model never sees the
individual verbs. This module FLATTENS the namespace on the request - it spreads
the ceiling-kept nested function tools as ordinary top-level function tools, which
the gateway forwards intact and the model can call by name.

Flattening alone is not enough, because Codex resolves the returned call by a
STRICT ``ToolName{name, namespace}`` match (codex-rs: ``tools/router.rs`` builds
``ToolName::new(namespace, name)`` from the response ``function_call`` item, whose
``namespace`` is a distinct field - ``protocol/src/models.rs``; the boltrig verbs
register as ``ToolName::namespaced("mcp__boltrig", "<verb>")`` -
``codex-mcp/src/tools.rs``). A flat ``function_call`` with no ``namespace`` field
is an "unsupported call". So :class:`CodexResponseStreamProcessor` reattaches
``namespace = "mcp__boltrig"`` onto every in-ceiling ``function_call`` item on the
response stream. Both edits change only the wire SHAPE; the ceiling (which verbs
are allowed, built-ins stripped) is unchanged - this stays inside VJS-CC-VJS 4.
"""

from __future__ import annotations

import json

from .codex_kernel_tools_phase import CODEX_MCP_NAMESPACE_NAME
from .codex_native_collaboration_wire import (
    CODEX_NATIVE_COLLAB_NAMESPACE_NAME,
    CODEX_NATIVE_COLLAB_TOOLS,
    NativeCollaborationWireGate,
)
from .model_proxy_ceiling_errors import (
    ModelCeilingViolation,
    ReasoningEffortCeilingViolation,
    ToolCeilingViolation,
)
from .model_proxy_request_ceiling import (
    MAX_MODEL_CALL_BODY_BYTES,
    enforce_model_ceiling,
    enforce_reasoning_effort_ceiling,
)

# The Responses API tool-call item type; SSE frames that carry one contain it, so
# it is the cheapest exact marker to decide whether an event needs inspection.
_FUNCTION_CALL_MARKER = b"function_call"
# An SSE event is terminated by a blank line. The current upstream (bifrost) uses
# LF, but the wire spec permits CRLF, and a gateway/provider change to CRLF must
# not silently break the lane: a ``\r\n\r\n`` frame contains no ``\n\n`` substring,
# so without this the whole response would buffer, never emit, and the tool call
# would be lost. We therefore split on EITHER terminator, taking the earliest.
_EVENT_DELIMITERS = (b"\r\n\r\n", b"\n\n")
# The separators Codex may use between the namespace and a nested tool name if the
# model ever returns a qualified call; every prefix stripped is the pinned boltrig
# namespace ONLY, so a qualified name can never smuggle a tool from elsewhere.
_NAMESPACE_SEPARATORS = ("/", ".", "__")

def enforce_tool_ceiling(
    body: bytes,
    allowed: frozenset[str],
    *,
    allow_native_collaboration: bool = False,
) -> bytes:
    """Return ``body`` with the tool set flattened + narrowed to the ceiling.

    An empty body passes through (a GET carries no tool set). Any other body must
    be JSON we can parse, or it is refused. The boltrig MCP namespace is flattened
    into its ceiling-kept nested function tools (spread to the top level); function
    / built-in tools survive only if their name is in the ceiling. When nothing
    survives the ``tools`` key is dropped entirely, along with ``tool_choice``, so
    the upstream sees a plain reasoning call rather than an empty-tools edge case.
    """

    if type(body) is not bytes:
        raise TypeError("body must be exact bytes")
    if type(allowed) is not frozenset:
        raise TypeError("allowed must be an exact frozenset")
    if type(allow_native_collaboration) is not bool:
        raise TypeError("allow_native_collaboration must be an exact bool")
    if not body:
        return body
    if len(body) > MAX_MODEL_CALL_BODY_BYTES:
        raise ToolCeilingViolation("model-call body exceeds the verifiable size cap")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ToolCeilingViolation("model-call body is not parseable JSON") from error
    if not isinstance(payload, dict) or "tools" not in payload:
        return body
    declared = payload.get("tools")
    if not isinstance(declared, list):
        raise ToolCeilingViolation("model-call tools is not a list")
    kept: list[object] = []
    seen: set[str] = set()
    for tool in declared:
        for surviving in _surviving_tools(
            tool, allowed, allow_native_collaboration=allow_native_collaboration
        ):
            name = _tool_name(surviving)
            if name is None or name in seen:
                continue
            seen.add(name)
            kept.append(surviving)
    if kept == declared:
        return body
    if kept:
        payload["tools"] = kept
    else:
        payload.pop("tools", None)
        payload.pop("tool_choice", None)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _surviving_tools(
    tool: object,
    allowed: frozenset[str],
    *,
    allow_native_collaboration: bool,
) -> list[object]:
    """The top-level tools one declared entry contributes after the ceiling.

    A function / built-in survives as itself iff its name is in the ceiling. The
    boltrig kernel NAMESPACE is FLATTENED: its ceiling-kept nested function tools
    (already exact function-tool objects: ``{type, name, description, parameters,
    strict}``) are spread as individual top-level function tools, so a gateway
    without a namespace concept cannot collapse them. Any other namespace, and any
    entry we cannot name, contributes nothing.
    """

    if not isinstance(tool, dict):
        return []
    if tool.get("type") == "namespace":
        nested = tool.get("tools")
        if not isinstance(nested, list):
            return []
        if tool.get("name") == CODEX_MCP_NAMESPACE_NAME:
            return [item for item in nested if _tool_name(item) in allowed]
        if (
            allow_native_collaboration
            and tool.get("name") == CODEX_NATIVE_COLLAB_NAMESPACE_NAME
        ):
            return [
                item
                for item in nested
                if isinstance(item, dict)
                and item.get("type") == "function"
                and _tool_name(item) in CODEX_NATIVE_COLLAB_TOOLS
            ]
        return []
    return [tool] if _tool_name(tool) in allowed else []


class CodexResponseStreamProcessor:
    """Enforce the ceiling on the RESPONSE and reattach the MCP namespace.

    ``enforce_tool_ceiling`` bounds what the model is OFFERED; it does not bound
    what comes back. An unsolicited ``function_call`` in the response would still
    be executed by the App Server, conferring a capability by a path that never
    crossed the request ceiling ([2026] VJS-CC-VJS 4). So every returned
    ``function_call`` item is checked against the ceiling and a call outside it
    truncates the stream (fail-closed: status and headers are already with the
    cell, so truncation is the only move left). When the ceiling is empty (the
    read-only lane) ANY function call is a violation.

    On top of enforcement it BRIDGES the namespace: because the request was
    flattened, the model returns a bare-named ``function_call`` with no
    ``namespace`` field, which Codex cannot resolve. This processor sets the
    item's ``name`` to the bare verb and its ``namespace`` to ``mcp__boltrig`` so
    Codex's ``ToolName{name, namespace}`` match succeeds. Nothing else in the
    event is touched; events without a ``function_call`` marker pass through
    byte-for-byte.

    The stream is reassembled into whole SSE events (``\\n\\n``-delimited) so an
    item whose JSON straddles chunk boundaries is rewritten intact.
    """

    __slots__ = ("_allowed", "_buffer", "_native_gate")

    def __init__(
        self,
        allowed: frozenset[str],
        *,
        native_gate: NativeCollaborationWireGate | None = None,
    ) -> None:
        if type(allowed) is not frozenset:
            raise TypeError("allowed must be an exact frozenset")
        if native_gate is not None and type(native_gate) is not NativeCollaborationWireGate:
            raise TypeError("native_gate must be exact NativeCollaborationWireGate or None")
        if native_gate is not None and allowed & CODEX_NATIVE_COLLAB_TOOLS:
            raise ValueError("kernel and native collaboration tool names must not overlap")
        self._allowed = allowed
        self._native_gate = native_gate
        self._buffer = b""

    def feed(self, chunk: bytes) -> bytes:
        """Consume a raw response chunk; return the processed bytes to relay.

        Raises :class:`ToolCeilingViolation` on an out-of-ceiling call or an
        unparseable tool-call event - the caller stops relaying (fail-closed).
        """

        if type(chunk) is not bytes:
            raise TypeError("chunk must be exact bytes")
        self._buffer += chunk
        out = bytearray()
        while True:
            index, delimiter_len = self._next_event_end()
            if index < 0:
                break
            event = self._buffer[: index + delimiter_len]
            self._buffer = self._buffer[index + delimiter_len :]
            out += self._process_event(event)
        return bytes(out)

    def _next_event_end(self) -> tuple[int, int]:
        """The earliest event terminator in the buffer as ``(index, length)``.

        Splits on the FIRST of any accepted blank-line terminator (LF or CRLF), so
        a mixed or CRLF stream can never hide a completed event behind an unmatched
        ``\\n\\n`` search. ``(-1, 0)`` when no whole event is buffered yet.
        """
        best_index = -1
        best_len = 0
        for delimiter in _EVENT_DELIMITERS:
            found = self._buffer.find(delimiter)
            if found < 0:
                continue
            if best_index < 0 or found < best_index or (
                found == best_index and len(delimiter) > best_len
            ):
                best_index, best_len = found, len(delimiter)
        return best_index, best_len

    def finish(self) -> bytes:
        """Flush the trailing partial event at stream end.

        A trailing fragment that still carries a tool-call marker cannot be
        verified whole, so it is refused rather than relayed unchecked.
        """

        rest = self._buffer
        self._buffer = b""
        if _FUNCTION_CALL_MARKER in rest:
            raise ToolCeilingViolation("response stream ended mid tool-call event")
        return rest

    def _process_event(self, event: bytes) -> bytes:
        if _FUNCTION_CALL_MARKER not in event:
            return event
        try:
            text = event.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ToolCeilingViolation("response event was not UTF-8") from error
        changed = False
        lines = text.split("\n")
        for position, line in enumerate(lines):
            carriage = line.endswith("\r")
            core = line[:-1] if carriage else line
            if not core.startswith("data:"):
                continue
            payload = core[len("data:") :].lstrip()
            if not payload or payload == "[DONE]":
                continue
            try:
                document = json.loads(payload)
            except json.JSONDecodeError as error:
                raise ToolCeilingViolation("response data frame is not parseable JSON") from error
            complete = (
                isinstance(document, dict)
                and document.get("type") == "response.output_item.done"
            )
            if self._bridge_function_calls(document, complete=complete):
                rewritten = "data: " + json.dumps(
                    document, ensure_ascii=False, separators=(",", ":")
                )
                lines[position] = rewritten + ("\r" if carriage else "")
                changed = True
        if not changed:
            return event
        return "\n".join(lines).encode("utf-8")

    def _bridge_function_calls(self, node: object, *, complete: bool) -> bool:
        """Enforce + reattach the namespace on every ``function_call`` in ``node``.

        Returns whether ``node`` was mutated. Raises on an out-of-ceiling call.
        """

        changed = False
        if isinstance(node, dict):
            if node.get("type") == "function_call":
                changed = self._bridge_one_call(node, complete=complete) or changed
            for value in node.values():
                changed = self._bridge_function_calls(value, complete=complete) or changed
        elif isinstance(node, list):
            for item in node:
                changed = self._bridge_function_calls(item, complete=complete) or changed
        return changed

    def _bridge_one_call(self, call: dict[str, object], *, complete: bool) -> bool:
        name = call.get("name")
        if not isinstance(name, str) or not name:
            # A nameless placeholder frame is not an executable call; leave it be.
            return False
        resolved = self._resolved_tool(name, call.get("namespace"))
        if resolved is None:
            raise ToolCeilingViolation("upstream returned a tool call outside the ceiling")
        bare, namespace = resolved
        changed = call.get("name") != bare or call.get("namespace") != namespace
        call["name"] = bare
        call["namespace"] = namespace
        if complete and namespace == CODEX_NATIVE_COLLAB_NAMESPACE_NAME:
            assert self._native_gate is not None
            self._native_gate.validate_complete_call(call)
        return changed

    def _resolved_tool(
        self, name: str, declared_namespace: object
    ) -> tuple[str, str] | None:
        """The bare name + exact namespace a returned call maps to, or None.

        Accepts the bare name (the flattened form the model is offered) or, defensively,
        an exact namespace-qualified form. A response that declares another
        namespace is never silently rewritten into an admitted one.
        """

        candidates = [(CODEX_MCP_NAMESPACE_NAME, self._allowed)]
        if self._native_gate is not None:
            candidates.append(
                (CODEX_NATIVE_COLLAB_NAMESPACE_NAME, CODEX_NATIVE_COLLAB_TOOLS)
            )
        if declared_namespace is not None:
            if not isinstance(declared_namespace, str):
                return None
            for namespace, allowed in candidates:
                if declared_namespace == namespace and name in allowed:
                    return name, namespace
            return None
        bare_matches = [
            (name, namespace)
            for namespace, allowed in candidates
            if name in allowed
        ]
        if len(bare_matches) == 1:
            return bare_matches[0]
        for namespace, allowed in candidates:
            for separator in _NAMESPACE_SEPARATORS:
                prefix = f"{namespace}{separator}"
                if name.startswith(prefix) and name[len(prefix) :] in allowed:
                    return name[len(prefix) :], namespace
        return None


def _tool_name(tool: object) -> str | None:
    """The wire name of a Responses-API tool entry, or None if it has no name.

    A function tool carries ``name``; a built-in tool is identified by ``type``.
    An entry we cannot name can never match the ceiling, so it is dropped.
    """

    if not isinstance(tool, dict):
        return None
    name = tool.get("name")
    if isinstance(name, str) and name:
        return name
    kind = tool.get("type")
    return kind if isinstance(kind, str) and kind else None


__all__ = [
    "MAX_MODEL_CALL_BODY_BYTES",
    "CODEX_NATIVE_COLLAB_NAMESPACE_NAME",
    "CODEX_NATIVE_COLLAB_TOOLS",
    "CodexResponseStreamProcessor",
    "ModelCeilingViolation",
    "NativeCollaborationWireGate",
    "ReasoningEffortCeilingViolation",
    "ToolCeilingViolation",
    "enforce_model_ceiling",
    "enforce_reasoning_effort_ceiling",
    "enforce_tool_ceiling",
]
