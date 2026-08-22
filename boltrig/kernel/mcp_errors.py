"""The MCP wire envelopes: the JSON-RPC frames, and the result a model reads.

Extracted from ``mcp.py``'s ``_call_tool``, which had grown a branch per failure
mode. The envelopes here are byte-identical to the ones it returned, with one
addition: a schema rejection now names the keys involved.

WHY THAT ADDITION IS THE WHOLE POINT. On the Classical Visas tenant the model
called ``opbox.get_matter`` with ``{"number": ...}`` NINE consecutive times, each
answered with the single word ``schema_invalid``, and only then broke down and
emitted tool calls as prose. The verb it wanted, ``opbox.get_matter_by_number``,
was offered to it in the same request. Both observed degenerations on that tenant
followed 9+ identical unproductive calls; neither followed a healthy first
attempt. An error that cannot be acted on is not an error message, it is a loop.

TWO LIMITS, both deliberate.

1. NAMES, NEVER VALUES. For an MCP-imported verb the input schema is THIRD-PARTY
   data taken verbatim from the remote ``tools/list``, and ``const``/``enum`` put
   literals in it. So this reports which keys are required, declared and supplied,
   and never what they must contain. That is the same names-versus-values cut the
   schema-validation ledger order draws for the append-only store, applied to a
   second channel. See ``kernel/schema_diagnosis.py`` for the rule.

2. DISCLOSURE FOLLOWS AUTHORISATION. This gate is now belt AND braces, and
   both halves are worth keeping. ``dispatch.py`` used to validate params BEFORE
   checking grants, so a caller holding no grant still reached the schema
   rejection and this predicate was the only thing between them and the input
   shape of every verb in the tenant. As of the capability-routing follow-up the
   grant check runs first (the routed case made it acute: a routed call is
   validated against the SOURCE OPERATION's schema, and the digest in that
   rejection is the binding's own ``source_schema_digest``). The predicate stays
   because the ordering is a property of one call path and this is a property of
   the envelope - the kind of pair whose disagreement is how the hole opened in
   the first place. An ungranted caller keeps the bare reason.

``_boltrig`` is untouched in every branch: the machine-readable status and reason
are a contract, and only the human/model-facing text grows.
"""

from __future__ import annotations

from typing import Any

from boltrig.models import (
    ApprovalNotHoldable,
    BoltrigError,
    DegradedMode,
    PendingHuman,
    SchemaValidationError,
)

def ok(rid: Any, result: dict) -> dict:
    """A JSON-RPC success frame. It lives here rather than in ``mcp.py`` so a
    handler extracted out of that file can answer without importing it back."""
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def err(rid: Any, code: int, message: str) -> dict:
    """A JSON-RPC error frame."""
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


# A rejection is meant to be read and acted on in one turn, so it stays short
# enough to survive a context window that is already carrying the failed call.
MAX_NAMED_KEYS = 20


def _named(keys: list[str]) -> str:
    shown = sorted(keys)[:MAX_NAMED_KEYS]
    more = len(keys) - len(shown)
    return ", ".join(shown) + (f" (+{more} more)" if more > 0 else "")


def schema_rejection_text(
    verb: str, schema: dict[str, Any] | None, args: dict[str, Any]
) -> str:
    """What the model needs to fix the call, in key names only.

    Deliberately says ``required`` and ``accepts`` even when nothing is missing,
    because the observed failure was a model holding the RIGHT argument for the
    WRONG verb: ``{"number": ...}`` is a perfectly good argument, just not for
    this verb. Listing the accepted keys is what lets it notice that.
    """
    schema = schema or {}
    sent = [k for k in (args or {}) if isinstance(k, str)]
    properties = sorted((schema.get("properties") or {}))
    required = sorted(schema.get("required") or [])
    missing = [k for k in required if k not in sent]
    unexpected = [k for k in sent if properties and k not in properties]

    parts = [f"schema_invalid for {verb}."]
    if missing:
        parts.append(f"Missing required: {_named(missing)}.")
    if unexpected:
        parts.append(f"Not accepted here: {_named(unexpected)}.")
    parts.append(f"You sent: {_named(sent) or '(no keys)'}.")
    # The full accepted set, but only where it adds something the lines above did
    # not already say. Repeating one key three times is noise in a context window
    # that is already carrying the failed call.
    if properties and set(properties) != set(missing):
        parts.append(f"{verb} accepts: {_named(properties)}.")
        if required and set(required) != set(properties):
            parts.append(f"Required: {_named(required)}.")
    return " ".join(parts)


def result_for(
    exc: BoltrigError, *, verb: str, schema: dict[str, Any] | None,
    args: dict[str, Any], may_disclose_schema: bool,
) -> dict[str, Any]:
    """The MCP envelope for a failed ``tools/call``.

    Ordered most specific first, because every one of these is a ``BoltrigError``
    subclass and a single ``except`` clause now feeds this.
    """
    if isinstance(exc, PendingHuman):
        return {
            "content": [{"type": "text", "text": f"pending approval: {exc.hitl_request_id}"}],
            "isError": True,
            "_boltrig": {"status": "pending_human", "hitl_request_id": exc.hitl_request_id},
        }
    if isinstance(exc, ApprovalNotHoldable):
        # The cell asked for a high-consequence action on a run that could not
        # hold an approval, so NO request was created. Handing back a bare
        # reason would leave the cell waiting on an id that does not exist -
        # which is the shape of the defect this refusal exists to prevent - so
        # say what happened and what to do instead.
        return {
            "content": [{"type": "text", "text": (
                f"cannot request approval for {exc.verb} here: this run cannot "
                "hold one, so nothing was submitted. Ask the person you are "
                "working with to run it, or raise it where it can be held."
            )}],
            "isError": True,
            "_boltrig": {"status": "not_holdable", "reason": exc.reason, "verb": exc.verb},
        }
    if isinstance(exc, DegradedMode):
        return {
            "content": [{"type": "text", "text": "degraded"}],
            "isError": True,
            "_boltrig": {"status": "degraded", "output": exc.output},
        }
    status = "denied" if exc.status_code == 403 else "error"
    text = exc.reason
    if isinstance(exc, SchemaValidationError) and may_disclose_schema:
        text = schema_rejection_text(verb, schema, args)
    return {
        "content": [{"type": "text", "text": text}],
        "isError": True,
        "_boltrig": {"status": status, "reason": exc.reason},
    }
