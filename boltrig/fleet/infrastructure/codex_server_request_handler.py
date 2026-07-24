"""Answer codex's server-initiated requests, deriving the answer from the kernel
as the sole governing gate ([2026] VJS-COUNTY 12).

Codex's App Server can initiate a request to the client - notably
``item/tool/requestUserInput``, a per-tool-call APPROVAL prompt it raises for
EVERY MCP tool call. Our client used to reject all server requests, which crashed
the single-reader notification pump (``CodexRuntimeOperationError``) and degraded
the turn.

The ruling: codex's prompt is an INTERFACE control point, not a governing one. The
governing locus is the kernel ``/v1/mcp`` door, whose SEC-14 gate is SELECTIVE -
it human-vetoes only HIGH-consequence (or explicitly blocking-listed) verbs; every
other verb runs under grant-check + audit with no human veto, by deliberate
calibration (``dispatch.py`` ``gated = consequence == HIGH or verb in
blocking_verbs``). So the faithful, drift-proof answer is to ADMIT every prompted
call to the kernel by answering approve: a LOW verb then runs and returns its
result; a HIGH verb hits the kernel's own durable, param-bound HITL, which is the
real veto. This handler makes NO gating decision of its own - it never duplicates
the kernel predicate, so it can never drift from it (derive-don't-store). A human
veto for the LOW class is deliberately omitted; the doctrine-honoring way to add
one is to recalibrate the verb as data (``consequence: HIGH`` / ``blocking_verbs``),
never a codex-side gate.

Fail-closed on ambiguity: if the approve option cannot be identified unambiguously
from codex's offered options, the request is refused with a typed error rather
than a fabricated label - and never an auto-DENY, which would suppress the call
before the kernel gate ever runs. Any non-approval server request is refused with a
typed error too. Neither path ever crashes the pump.
"""

from __future__ import annotations

import logging

from boltrig.fleet.domain import CanonicalJSON

from . import codex_protocol as wire

logger = logging.getLogger(__name__)

# Codex's per-tool-call approval prompt (App Server protocol v2).
REQUEST_USER_INPUT_METHOD = "item/tool/requestUserInput"

# JSON-RPC error codes for a refused server request (method / params).
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602

# Case-insensitive option labels that unambiguously mean "approve / admit". Codex
# offers options like Accept / Decline / Cancel; admitting the call to the kernel
# (the sole governing locus) means picking the approve option and echoing its
# exact label back (the answer schema is label-based, not a decision enum).
_APPROVE_LABELS = frozenset(
    {"approve", "approved", "accept", "accepted", "allow", "yes", "confirm"}
)


class ApprovalLabelError(ValueError):
    """The approve option could not be identified unambiguously (fail closed)."""


async def answer_server_request(request: wire.RequestMessage) -> wire.ResponseMessage:
    """Derive codex's answer to a server-initiated request; never crash the pump.

    For ``item/tool/requestUserInput`` this admits the call to the kernel (answers
    approve with codex's own approve-option label). Any other method, or an
    unresolvable approve label, is refused with a typed error response.
    """

    if request.method != REQUEST_USER_INPUT_METHOD:
        return _error(request.request_id, _METHOD_NOT_FOUND, "unsupported codex server request")
    try:
        answers = _approve_all_questions(request.params.to_mapping())
    except ApprovalLabelError as exc:
        # Fail closed: refuse rather than guess a label; the kernel gate never
        # runs on a fabricated approval, and we never auto-deny before it either.
        logger.warning("codex approval refused (label unresolved): %s", exc)
        return _error(request.request_id, _INVALID_PARAMS, "approval label unresolved")
    return wire.ResponseMessage(
        request_id=request.request_id,
        result=CanonicalJSON.from_mapping({"answers": answers}),
    )


def _approve_all_questions(params: dict[str, object]) -> dict[str, object]:
    questions = params.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ApprovalLabelError("requestUserInput carried no questions")
    answers: dict[str, object] = {}
    for question in questions:
        if not isinstance(question, dict):
            raise ApprovalLabelError("malformed requestUserInput question")
        question_id = question.get("id")
        if not isinstance(question_id, str) or not question_id:
            raise ApprovalLabelError("requestUserInput question has no id")
        answers[question_id] = {"answers": [_approve_label(question.get("options"))]}
    return answers


def _approve_label(options: object) -> str:
    """The unique offered option label that means approve, else fail closed.

    Exactly one offered option must map to an approve label; zero (nothing to
    approve with) or many (ambiguous) is refused. Echoes the option's EXACT label
    (codex matches the answer against the label it offered).
    """

    if not isinstance(options, list) or not options:
        raise ApprovalLabelError("requestUserInput offered no options")
    matches: list[str] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        label = option.get("label")
        if isinstance(label, str) and label.strip().lower() in _APPROVE_LABELS:
            matches.append(label)
    if len({label.strip().lower() for label in matches}) != 1:
        raise ApprovalLabelError(
            f"approve option is not unambiguous ({len(matches)} candidate labels)"
        )
    return matches[0]


def _error(request_id: int, code: int, message: str) -> wire.ResponseMessage:
    return wire.ResponseMessage(
        request_id=request_id,
        error=wire.RemoteErrorData(code=code, message=message),
    )


__all__ = ["REQUEST_USER_INPUT_METHOD", "ApprovalLabelError", "answer_server_request"]
