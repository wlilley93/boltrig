"""Enforce a cell's tool ceiling on the model-call wire (the one chokepoint).

Codex 0.144.3 offers its built-in tools (``exec_command``, ``write_stdin``,
``update_plan``, ``request_user_input``, ``view_image``) on every turn, and
``config.toml`` cannot suppress them: the reviewed ``[tools]`` table accepts only
``web_search`` and ``experimental_request_user_input``. So a cell configured
``approval_policy = "never"`` would hand the model an unapproved shell inside the
kernel container, and any shell child - being a descendant of the App Server -
also satisfies the ancestry attestation on the bearer ingress.

Admission already asserts the quarantined Codex lane has NO effective tools
(``codex_runtime_admission``: "quarantined runtime cannot attest effective
tools"). That assertion was unenforced on the wire; this module makes it true.
The per-cell loopback proxy is the only point both sides must traverse, so the
ceiling is applied there rather than trusted to the runtime's own config.

The ceiling is a SET, not a flag: the kernel-tools lane
(``codex_kernel_tools_phase``) compiles the run's granted verbs into exact
Codex wire names (``mcp__boltrig__*``) at admission, and the same enforcement
then offers exactly those tools and no more - built-ins stay stripped either
way, and a boltrig verb outside the run's grants is stripped like any other.

Fail-closed: a body we cannot parse is a body whose tool set we cannot verify, so
it is rejected rather than forwarded.
"""

from __future__ import annotations

import json
import re

# The Responses API names a tool call by this item type; the SSE frames that carry
# one always contain it, so it is the cheapest exact marker to scan a stream for.
_FUNCTION_CALL_MARKER = b"function_call"
_NAME_FIELD = re.compile(rb'"name"\s*:\s*"([^"]*)"')
# A tail long enough that a marker or a name split across two chunks is still seen.
_STREAM_TAIL_BYTES = 512

# A model-call body we cannot parse is one whose tool set we cannot check. The
# cap is generous (a full read-only context is well under it) and exists so an
# unbounded body can never be forwarded unverified.
MAX_MODEL_CALL_BODY_BYTES = 32 * 1024 * 1024


class ToolCeilingViolation(ValueError):
    """A model-call body could not be verified against the cell's tool ceiling."""


def enforce_tool_ceiling(body: bytes, allowed: frozenset[str]) -> bytes:
    """Return ``body`` with every tool outside ``allowed`` removed.

    An empty body passes through (a GET carries no tool set). Any other body must
    be JSON we can parse, or it is refused. When the surviving tool list is empty
    the ``tools`` key is dropped entirely, along with ``tool_choice``, so the
    upstream sees a plain reasoning call rather than an empty-tools edge case.
    """

    if type(body) is not bytes:
        raise TypeError("body must be exact bytes")
    if type(allowed) is not frozenset:
        raise TypeError("allowed must be an exact frozenset")
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
    kept = [tool for tool in declared if _tool_name(tool) in allowed]
    if len(kept) == len(declared):
        return body
    if kept:
        payload["tools"] = kept
    else:
        payload.pop("tools", None)
        payload.pop("tool_choice", None)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class ToolCallStreamGuard:
    """Hold the ceiling on the RESPONSE stream, not only the request.

    ``enforce_tool_ceiling`` bounds what the model is OFFERED. It does not bound
    what comes back: a gateway that returns a ``function_call`` for a tool we
    stripped would still be executed by the App Server, which never needed to be
    offered the tool at all. [2026] VJS-CC-VJS 4's exclusivity limb asks whether
    the capability can be conferred by ANY path that misses the chokepoint, and an
    unsolicited tool call in the response is exactly such a path.

    The stream is scanned as it passes, with a sliding tail so a marker split
    across two chunks is still seen. On a violation the caller must stop relaying:
    a truncated response is the fail-closed outcome, because by then the status and
    headers have already gone to the cell and no error status is available.

    When the ceiling is empty (the read-only lane) the test is exact and needs no
    name parsing: ANY function call at all is a violation.
    """

    __slots__ = ("_allowed", "_tail")

    def __init__(self, allowed: frozenset[str]) -> None:
        if type(allowed) is not frozenset:
            raise TypeError("allowed must be an exact frozenset")
        self._allowed = allowed
        self._tail = b""

    def inspect(self, chunk: bytes) -> None:
        """Raise :class:`ToolCeilingViolation` if the chunk carries a barred call."""

        if type(chunk) is not bytes:
            raise TypeError("chunk must be exact bytes")
        window = self._tail + chunk
        if _FUNCTION_CALL_MARKER in window:
            if not self._allowed or not self._named_calls_are_allowed(window):
                raise ToolCeilingViolation("upstream returned a tool call outside the ceiling")
        # Keep enough tail that a marker or name split across chunks is still seen.
        self._tail = window[-_STREAM_TAIL_BYTES:]

    def _named_calls_are_allowed(self, window: bytes) -> bool:
        for match in _NAME_FIELD.finditer(window):
            try:
                name = match.group(1).decode("utf-8")
            except UnicodeDecodeError:
                return False
            if name not in self._allowed:
                return False
        return True


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
    "ToolCallStreamGuard",
    "ToolCeilingViolation",
    "enforce_tool_ceiling",
]
