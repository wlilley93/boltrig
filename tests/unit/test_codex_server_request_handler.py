"""codex server-request handler ([2026] VJS-COUNTY 12).

codex's per-tool-call item/tool/requestUserInput is answered by ADMITTING the call
to the kernel (approve, using codex's own approve-option label); the kernel /v1/mcp
door is the sole governing gate. The handler makes no gating decision of its own,
fails closed on an unresolvable label, and refuses any other server request with a
typed error - never crashing.
"""

from __future__ import annotations

import json

import pytest

from boltrig.fleet.domain import CanonicalJSON
from boltrig.fleet.infrastructure import codex_protocol as wire
from boltrig.fleet.infrastructure.codex_server_request_handler import (
    REQUEST_USER_INPUT_METHOD,
    answer_server_request,
)


def _request(method: str, params: dict) -> wire.RequestMessage:
    return wire.RequestMessage(0, method, CanonicalJSON.from_mapping(params))


def _approval(options: list, *, qid: str = "mcp_tool_call_approval_call_1") -> wire.RequestMessage:
    return _request(
        REQUEST_USER_INPUT_METHOD,
        {
            "threadId": "t1", "turnId": "u1", "itemId": "call_1",
            "questions": [{
                "id": qid, "header": "Approve app tool call?",
                "question": 'Allow the boltrig MCP server to run tool "opbox.matter.list"?',
                "isOther": False, "isSecret": False, "options": options,
            }],
            "autoResolutionMs": None,
        },
    )


_OFFERED = [
    {"label": "Approve", "description": "run the tool"},
    {"label": "Decline", "description": "do not run"},
    {"label": "Abort", "description": "cancel the turn"},
]


@pytest.mark.invariant("CODEX-APPROVAL-4")
async def test_a_tool_approval_is_admitted_with_codex_own_label() -> None:
    response = await answer_server_request(_approval(_OFFERED))
    assert response.request_id == 0 and response.error is None
    result = response.result.to_value()
    # Exactly the schema codex expects, echoing the offered label (not hardcoded).
    assert result == {"answers": {"mcp_tool_call_approval_call_1": {"answers": ["Approve"]}}}
    # And it encodes to a valid response frame.
    line = wire.encode_response(response)
    assert '"id":0' in line and '"result"' in line


@pytest.mark.invariant("CODEX-APPROVAL-4")
async def test_the_answer_label_is_read_from_offered_options_not_hardcoded() -> None:
    # codex offers "Accept" (not "Approve") -> we must echo "Accept".
    offered = [{"label": "Accept", "description": "ok"}, {"label": "Reject", "description": "no"}]
    response = await answer_server_request(_approval(offered))
    assert response.result.to_value()["answers"]["mcp_tool_call_approval_call_1"]["answers"] == ["Accept"]


@pytest.mark.invariant("CODEX-APPROVAL-2")
async def test_the_handler_makes_no_gating_decision_so_it_cannot_drift() -> None:
    """[2026] VJS-COUNTY 12 D2+D4: the handler ADMITS every prompted call to the kernel
    identically - it never inspects the verb's consequence or duplicates the
    dispatch.py:406 gate - so it can never drift from the kernel, which stays the
    sole governing locus. A LOW read and a HIGH delete get the same admit answer;
    the kernel's own selective gate does the real work."""
    low = _approval(_OFFERED, qid="approve_low")
    # A HIGH-consequence verb in the question text must not change the answer:
    high = _request(
        REQUEST_USER_INPUT_METHOD,
        {
            "threadId": "t", "turnId": "u", "itemId": "call_h",
            "questions": [{
                "id": "approve_high", "header": "Approve app tool call?",
                "question": 'Allow the boltrig MCP server to run tool "jira.delete"?',
                "isOther": False, "isSecret": False, "options": _OFFERED,
            }],
            "autoResolutionMs": None,
        },
    )
    low_ans = (await answer_server_request(low)).result.to_value()["answers"]["approve_low"]
    high_ans = (await answer_server_request(high)).result.to_value()["answers"]["approve_high"]
    assert low_ans == high_ans == {"answers": ["Approve"]}


# [2026] VJS-COUNTY 12 D5: the approve label must be PRESENT and UNAMBIGUOUS in
# codex's offered options, or the handler answers the error arm and fails closed -
# guessing a label is how a HIGH call gets admitted on a wrong answer.
@pytest.mark.invariant("CODEX-APPROVAL-4")
async def test_no_approve_option_fails_closed_with_an_error() -> None:
    offered = [{"label": "Decline", "description": "no"}, {"label": "Abort", "description": "no"}]
    response = await answer_server_request(_approval(offered))
    assert response.error is not None and response.result is None


@pytest.mark.invariant("CODEX-APPROVAL-4")
async def test_an_ambiguous_approve_option_fails_closed() -> None:
    # Two DIFFERENT approve-ish labels -> ambiguous -> refuse rather than guess.
    offered = [{"label": "Approve", "description": "a"}, {"label": "Allow", "description": "b"}]
    response = await answer_server_request(_approval(offered))
    assert response.error is not None and response.result is None


async def test_null_or_empty_options_fails_closed() -> None:
    assert (await answer_server_request(_approval(None))).error is not None
    assert (await answer_server_request(_approval([]))).error is not None


async def test_a_non_approval_server_request_is_refused_typed() -> None:
    response = await answer_server_request(_request("account/chatgptAuthTokens/refresh", {"x": 1}))
    assert response.error is not None and response.result is None
    assert response.error.code == -32601


async def test_a_duplicate_approve_label_is_not_ambiguous() -> None:
    # The same approve label offered twice is still a single unambiguous choice.
    offered = [{"label": "Approve", "description": "a"}, {"label": "Approve", "description": "b"}]
    response = await answer_server_request(_approval(offered))
    assert response.error is None
    assert response.result.to_value()["answers"]["mcp_tool_call_approval_call_1"]["answers"] == ["Approve"]


@pytest.mark.invariant("SEC-150")
async def test_the_error_arm_carries_no_request_params() -> None:
    # A refusal must not echo any of codex's params back on the wire.
    req = _approval([{"label": "Decline", "description": "SECRETDESC"}])
    response = await answer_server_request(req)
    line = wire.encode_response(response)
    assert "SECRETDESC" not in line
    assert json.loads(line.replace("data: ", ""))["error"]["code"] == -32602
