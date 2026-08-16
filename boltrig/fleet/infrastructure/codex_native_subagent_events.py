"""Content-free projection of pinned Codex native-subagent item metadata."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Callable, Protocol

from boltrig.fleet.domain import JSONValue
from boltrig.models.model_id_policy import exact_model_id

from .codex_runtime_event_state import CodexRuntimeProtocolError

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_COLLAB_TOOLS = frozenset(
    {"spawnAgent", "sendInput", "resumeAgent", "wait", "closeAgent"}
)
_COLLAB_STATUSES = frozenset({"inProgress", "completed", "failed"})
_COLLAB_AGENT_STATUSES = frozenset(
    {
        "pendingInit",
        "running",
        "interrupted",
        "completed",
        "errored",
        "shutdown",
        "notFound",
    }
)
_SUBAGENT_ACTIVITY_KINDS = frozenset({"started", "interacted", "interrupted"})
_REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh"})


class NativeThreadKnowledge(Protocol):
    def require_known(self, thread_id: str) -> None: ...


def validate_native_event_policy(model_id: str, reasoning_effort: str) -> None:
    try:
        exact_model_id(model_id)
    except ValueError:
        raise ValueError("event translator model policy is invalid")
    if reasoning_effort not in _REASONING_EFFORTS:
        raise ValueError("event translator reasoning policy is invalid")


def native_thread_ref(assignment_id: str, root_id: str, thread_id: str) -> str:
    if thread_id == root_id:
        return "root"
    return hashlib.sha256(
        f"{assignment_id}:{thread_id}".encode("utf-8")
    ).hexdigest()[:24]


def native_item_payload(
    method: str,
    item_type: str,
    item: Mapping[str, JSONValue],
    *,
    assignment_id: str,
    root_id: str,
    max_total: int,
    model_id: str,
    reasoning_effort: str,
    thread_knowledge: NativeThreadKnowledge,
) -> dict[str, JSONValue]:
    lifecycle = "started" if method == "item/started" else "completed"
    def ref(thread_id: str) -> str:
        return native_thread_ref(assignment_id, root_id, thread_id)
    if item_type == "subAgentActivity":
        thread_id = _identifier("native activity thread id", item.get("agentThreadId"))
        activity = _choice(
            "native activity kind", item.get("kind"), _SUBAGENT_ACTIVITY_KINDS
        )
        if type(item.get("agentPath")) is not str:
            raise CodexRuntimeProtocolError("native activity path is invalid")
        return {
            "activity": activity,
            "lifecycle": lifecycle,
            "native_thread_ref": ref(thread_id),
        }

    tool = _choice("collab tool", item.get("tool"), _COLLAB_TOOLS)
    status = _choice("collab status", item.get("status"), _COLLAB_STATUSES)
    if (
        (method == "item/started" and status != "inProgress")
        or (method == "item/completed" and status == "inProgress")
    ):
        raise CodexRuntimeProtocolError("collab status does not match item lifecycle")
    sender = _identifier("collab sender thread id", item.get("senderThreadId"))
    if sender != root_id:
        thread_knowledge.require_known(sender)
    receiver_ids = _receiver_ids(item.get("receiverThreadIds"), max_total)
    _require_requested_policy(item, model_id, reasoning_effort)
    projected_states = _project_agent_states(item.get("agentsStates"), max_total, ref)
    return {
        "action": tool,
        "agent_states": projected_states,
        "lifecycle": lifecycle,
        "native_receiver_refs": [ref(thread_id) for thread_id in receiver_ids],
        "native_sender_ref": ref(sender),
        "status": status,
    }


def _receiver_ids(value: object, max_total: int) -> list[str]:
    if not isinstance(value, list) or len(value) > max_total:
        raise CodexRuntimeProtocolError("collab receiver set is invalid")
    receiver_ids = [
        _identifier("collab receiver thread id", receiver) for receiver in value
    ]
    if len(receiver_ids) != len(set(receiver_ids)):
        raise CodexRuntimeProtocolError("collab receiver set is duplicated")
    return receiver_ids


def _require_requested_policy(
    item: Mapping[str, JSONValue],
    model_id: str,
    reasoning_effort: str,
) -> None:
    requested_model = item.get("model")
    if requested_model is not None and (
        type(requested_model) is not str or requested_model != model_id
    ):
        raise CodexRuntimeProtocolError("collab request exceeded the model ceiling")
    requested_effort = item.get("reasoningEffort")
    if requested_effort is not None and (
        type(requested_effort) is not str or requested_effort != reasoning_effort
    ):
        raise CodexRuntimeProtocolError("collab request exceeded the reasoning ceiling")
    prompt = item.get("prompt")
    if prompt is not None and type(prompt) is not str:
        raise CodexRuntimeProtocolError("collab prompt field is invalid")


def _project_agent_states(
    value: object,
    max_total: int,
    ref: Callable[[str], str],
) -> dict[str, JSONValue]:
    if not isinstance(value, dict) or len(value) > max_total:
        raise CodexRuntimeProtocolError("collab agent states are invalid")
    projected: dict[str, JSONValue] = {}
    for raw_thread_id, raw_state in value.items():
        thread_id = _identifier("collab state thread id", raw_thread_id)
        if not isinstance(raw_state, dict):
            raise CodexRuntimeProtocolError("collab agent state is invalid")
        state = _choice(
            "collab agent status", raw_state.get("status"), _COLLAB_AGENT_STATUSES
        )
        message = raw_state.get("message")
        if message is not None and type(message) is not str:
            raise CodexRuntimeProtocolError("collab agent state message is invalid")
        projected[ref(thread_id)] = state
    return projected


def _identifier(label: str, value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise CodexRuntimeProtocolError(f"{label} is invalid")
    return value


def _choice(label: str, value: object, allowed: frozenset[str]) -> str:
    if type(value) is not str or value not in allowed:
        raise CodexRuntimeProtocolError(f"{label} is invalid")
    return value


__all__ = [
    "native_item_payload",
    "native_thread_ref",
    "validate_native_event_policy",
]
