"""Secret-minimizing normalization of stable Codex 0.144.3 notifications."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping

from boltrig.fleet.domain import (
    CanonicalJSON,
    JSONValue,
    PhaseAssignmentRef,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeThreadRef,
    RuntimeTurnRef,
)

from . import codex_protocol as wire
from .codex_cell_policy import CODEX_CLI_VERSION
from .codex_runtime_config_toml import CODEX_MCP_SERVER_NAME
from .codex_runtime_event_state import (
    CodexRuntimeProtocolError,
    NativeObservationState,
)

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_TURN_STATUSES = frozenset({"completed", "failed", "inProgress", "interrupted"})
_ITEM_TYPES = frozenset(
    {
        "agentMessage",
        "collabAgentToolCall",
        "commandExecution",
        "contextCompaction",
        "dynamicToolCall",
        "enteredReviewMode",
        "exitedReviewMode",
        "fileChange",
        "hookPrompt",
        "imageGeneration",
        "imageView",
        "mcpToolCall",
        "plan",
        "reasoning",
        "sleep",
        "subAgentActivity",
        "userMessage",
        "webSearch",
    }
)
_NATIVE_ITEM_TYPES = frozenset({"collabAgentToolCall", "subAgentActivity"})
_LIFECYCLE_METHODS = frozenset(
    {
        "error",
        "item/completed",
        "item/started",
        "thread/closed",
        "thread/started",
        "turn/completed",
        "turn/started",
        "warning",
    }
)
MAX_RUNTIME_EVENTS = 1_000_000
MAX_ITEMS_PER_PHASE = 4096
_INVALIDATION_METHODS = frozenset(
    {
        "app/list/updated",
        "configWarning",
        "externalAgentConfig/import/completed",
        "externalAgentConfig/import/progress",
        "fs/changed",
        "hook/completed",
        "hook/started",
        "mcpServer/oauthLogin/completed",
        "mcpServer/startupStatus/updated",
        "model/rerouted",
        "skills/changed",
        "thread/settings/updated",
    }
)


def is_runtime_invalidation(method: str) -> bool:
    """Return whether a notification invalidates quarantined phase evidence."""

    return method in _INVALIDATION_METHODS


def is_kernel_tools_mcp_startup_update(notification: wire.NotificationMessage) -> bool:
    """Whether an invalidation-class notification is the ONE the kernel-tools
    lane expects: the admitted ``boltrig`` MCP server reaching a live state.

    The preflight attested the inventory (exactly this server, bearer auth, no
    resources, tools within the admitted ceiling), so its startup updates carry
    no new evidence. Anything else stays fatal: another server's update, a
    failure/cancellation of ours (the tool path died - the turn must degrade),
    or any other invalidation method. The server name itself is argv-pinned, so
    a rewritten per-cell config cannot borrow it (VJS-CC-VJS 6 H5).
    """

    if notification.method != "mcpServer/startupStatus/updated":
        return False
    params = notification.params.to_mapping()
    return (
        params.get("name") == CODEX_MCP_SERVER_NAME
        and params.get("status") in {"starting", "ready"}
    )


class CodexEventTranslator:
    """Normalize observations; native limits are detection tripwires, not controls."""

    def __init__(
        self,
        *,
        assignment: PhaseAssignmentRef,
        thread: RuntimeThreadRef,
        cwd: str,
        max_native_concurrent: int,
        max_native_total: int,
        max_native_depth: int,
    ) -> None:
        if thread.assignment != assignment:
            raise ValueError("event translator bindings disagree")
        if any(
            type(value) is not int
            for value in (max_native_concurrent, max_native_total, max_native_depth)
        ):
            raise TypeError("native subagent limits must be exact integers")
        if (
            min(max_native_concurrent, max_native_total, max_native_depth) < 0
            or max_native_concurrent > max_native_total
            or (max_native_total == 0) != (max_native_depth == 0)
        ):
            raise ValueError("native subagent limits are inconsistent")
        self._assignment = assignment
        self._assignment_digest = hashlib.sha256(
            assignment.assignment_id.encode("utf-8")
        ).hexdigest()[:24]
        self._thread = thread
        self._cwd = cwd
        self._max_native_concurrent = max_native_concurrent
        self._max_native_total = max_native_total
        self._max_native_depth = max_native_depth
        self._current_turn: RuntimeTurnRef | None = None
        self._root_started = False
        self._turn_started = False
        self._item_types: dict[str, str] = {}
        self._active_items: set[str] = set()
        # The latest phase-thread agentMessage text, captured for the read-back
        # seam only. It is NEVER placed in an emitted RuntimeEvent (events() stays a
        # content-free ledger, a test-pinned contract); read_turn_output reads it
        # here because thread/read is not served in the App Server's exec mode.
        self._latest_agent_message_text = ""
        self._native = NativeObservationState(
            max_concurrent=max_native_concurrent,
            max_total=max_native_total,
            max_depth=max_native_depth,
            max_items=MAX_ITEMS_PER_PHASE,
        )
        self._sequence = 0

    @property
    def current_turn(self) -> RuntimeTurnRef | None:
        return self._current_turn

    @property
    def latest_agent_message_text(self) -> str:
        """The most recent phase-thread agentMessage text (read-back seam only)."""

        return self._latest_agent_message_text

    @property
    def root_started(self) -> bool:
        return self._root_started

    def bind_turn(self, turn: RuntimeTurnRef) -> None:
        if turn.thread != self._thread:
            raise CodexRuntimeProtocolError("turn belongs to another phase thread")
        if self._current_turn is not None:
            raise CodexRuntimeProtocolError("phase thread already has an active turn")
        if not self._root_started:
            raise CodexRuntimeProtocolError("phase thread has not emitted its root start")
        _identifier("turn id", turn.turn_id)
        self._current_turn = turn
        self._turn_started = False
        self._item_types.clear()
        self._active_items.clear()

    def translate(self, notification: wire.NotificationMessage) -> RuntimeEvent:
        if self._sequence >= MAX_RUNTIME_EVENTS:
            raise CodexRuntimeProtocolError("runtime event limit is exhausted")
        self._sequence += 1
        if is_runtime_invalidation(notification.method):
            raise CodexRuntimeProtocolError("Codex pre-thread attestation was invalidated")
        if not self._root_started and notification.method != "thread/started":
            raise CodexRuntimeProtocolError("notification preceded the phase root start")
        if notification.method not in _LIFECYCLE_METHODS:
            return self._event(
                RuntimeEventKind.UNKNOWN,
                payload={"method_digest": _method_digest(notification.method)},
            )
        params = notification.params.to_mapping()
        if notification.method == "thread/started":
            return self._thread_started(params)
        if notification.method == "thread/closed":
            return self._thread_closed(params)
        if notification.method in {"turn/started", "turn/completed"}:
            return self._turn_event(notification.method, params)
        if notification.method in {"item/started", "item/completed"}:
            return self._item_event(notification.method, params)
        if notification.method == "error":
            return self._error(params)
        return self._warning(params)

    def _thread_started(self, params: Mapping[str, JSONValue]) -> RuntimeEvent:
        thread = _mapping(params, "thread")
        thread_id = _identifier("thread id", thread.get("id"))
        if (
            thread.get("cliVersion") != CODEX_CLI_VERSION
            or thread.get("cwd") != self._cwd
            or thread.get("ephemeral") is not True
        ):
            raise CodexRuntimeProtocolError("thread notification policy does not match")
        parent = thread.get("parentThreadId")
        if thread_id == self._thread.thread_id:
            if parent is not None or self._root_started:
                raise CodexRuntimeProtocolError("phase thread claimed a native parent")
            self._root_started = True
            return self._event(RuntimeEventKind.THREAD_STARTED)
        if not self._root_started:
            raise CodexRuntimeProtocolError("native thread preceded the phase root start")
        parent_id = _identifier("native parent thread id", parent)
        depth = self._native.start(self._thread.thread_id, thread_id, parent_id)
        return self._event(
            RuntimeEventKind.UNKNOWN,
            payload={"native_depth": depth, "observation": "native_thread_started"},
        )

    def _thread_closed(self, params: Mapping[str, JSONValue]) -> RuntimeEvent:
        thread_id = _identifier("thread id", params.get("threadId"))
        if thread_id == self._thread.thread_id:
            raise CodexRuntimeProtocolError("phase thread closed outside Boltrig lifecycle")
        self._native.close(thread_id)
        return self._event(
            RuntimeEventKind.UNKNOWN,
            payload={"observation": "native_thread_closed"},
        )

    def _turn_event(self, method: str, params: Mapping[str, JSONValue]) -> RuntimeEvent:
        thread_id = _identifier("thread id", params.get("threadId"))
        turn = _mapping(params, "turn")
        turn_id = _identifier("turn id", turn.get("id"))
        status = _choice("turn status", turn.get("status"), _TURN_STATUSES)
        if not isinstance(turn.get("items"), list):
            raise CodexRuntimeProtocolError("turn items must be a list")
        if thread_id != self._thread.thread_id:
            self._native.transition_turn(method, thread_id, turn_id, status)
            return self._event(
                RuntimeEventKind.UNKNOWN,
                payload={"observation": "native_turn_lifecycle", "status": status},
            )
        expected = self._require_current_turn(turn_id)
        if method == "turn/started":
            if status != "inProgress" or self._turn_started:
                raise CodexRuntimeProtocolError("started turn is not in progress")
            self._turn_started = True
            return self._event(RuntimeEventKind.TURN_STARTED, turn=expected)
        if status == "inProgress" or not self._turn_started or self._active_items:
            raise CodexRuntimeProtocolError("completed turn is still in progress")
        event = self._event(
            RuntimeEventKind.TURN_COMPLETED,
            turn=expected,
            payload={"status": status},
        )
        self._current_turn = None
        self._turn_started = False
        return event

    def _item_event(self, method: str, params: Mapping[str, JSONValue]) -> RuntimeEvent:
        thread_id = _identifier("thread id", params.get("threadId"))
        turn_id = _identifier("turn id", params.get("turnId"))
        item = _mapping(params, "item")
        item_id = _identifier("item id", item.get("id"))
        item_type = _choice("item type", item.get("type"), _ITEM_TYPES)
        timestamp_key = "startedAtMs" if method == "item/started" else "completedAtMs"
        timestamp = params.get(timestamp_key)
        if type(timestamp) is not int or timestamp < 0:
            raise CodexRuntimeProtocolError("item timestamp is invalid")
        if thread_id != self._thread.thread_id:
            self._native.transition_item(
                method,
                thread_id,
                turn_id,
                item_id,
                item_type,
                root_item_count=len(self._item_types),
            )
            return self._event(
                RuntimeEventKind.UNKNOWN,
                payload={"item_type": item_type, "observation": "native_item_lifecycle"},
            )
        turn = self._require_current_turn(turn_id)
        if not self._turn_started:
            raise CodexRuntimeProtocolError("item preceded its turn start")
        self._transition_item(method, item_id, item_type)
        if method == "item/completed" and item_type == "agentMessage":
            text = item.get("text")
            if type(text) is str:
                self._latest_agent_message_text = text
        if item_type in _NATIVE_ITEM_TYPES:
            raise CodexRuntimeProtocolError("native agent activity is not admitted")
        kind = (
            RuntimeEventKind.ITEM_STARTED
            if method == "item/started"
            else RuntimeEventKind.ITEM_COMPLETED
        )
        return self._event(
            kind,
            turn=turn,
            item_id=item_id,
            payload={
                "item_type": item_type,
                "native_observation": item_type in _NATIVE_ITEM_TYPES,
            },
        )

    def _error(self, params: Mapping[str, JSONValue]) -> RuntimeEvent:
        thread_id = _identifier("thread id", params.get("threadId"))
        turn_id = _identifier("turn id", params.get("turnId"))
        error = _mapping(params, "error")
        will_retry = params.get("willRetry")
        if type(error.get("message")) is not str or type(will_retry) is not bool:
            raise CodexRuntimeProtocolError("error notification shape is invalid")
        if thread_id != self._thread.thread_id:
            self._native.require_turn(thread_id, turn_id)
            return self._event(
                RuntimeEventKind.UNKNOWN,
                payload={"observation": "native_error", "will_retry": will_retry},
            )
        turn = self._require_current_turn(turn_id)
        if not self._turn_started:
            raise CodexRuntimeProtocolError("error preceded its turn start")
        return self._event(
            RuntimeEventKind.ERROR,
            turn=turn,
            payload={"will_retry": will_retry},
        )

    def _warning(self, params: Mapping[str, JSONValue]) -> RuntimeEvent:
        if type(params.get("message")) is not str:
            raise CodexRuntimeProtocolError("warning notification shape is invalid")
        thread_id = params.get("threadId")
        if thread_id is None:
            return self._event(RuntimeEventKind.WARNING)
        exact_thread = _identifier("thread id", thread_id)
        if exact_thread != self._thread.thread_id:
            self._native.require_active(exact_thread)
            return self._event(
                RuntimeEventKind.UNKNOWN,
                payload={"observation": "native_warning"},
            )
        return self._event(RuntimeEventKind.WARNING)

    def _require_current_turn(self, turn_id: str) -> RuntimeTurnRef:
        if self._current_turn is None or self._current_turn.turn_id != turn_id:
            raise CodexRuntimeProtocolError("notification turn does not match the active turn")
        return self._current_turn

    def _transition_item(self, method: str, item_id: str, item_type: str) -> None:
        if method == "item/started":
            if item_id in self._item_types or len(self._item_types) >= MAX_ITEMS_PER_PHASE:
                raise CodexRuntimeProtocolError("item start is duplicate or exceeds its bound")
            self._item_types[item_id] = item_type
            self._active_items.add(item_id)
            return
        if self._item_types.get(item_id) != item_type or item_id not in self._active_items:
            raise CodexRuntimeProtocolError("item completion has no matching active start")
        self._active_items.remove(item_id)

    def _event(
        self,
        kind: RuntimeEventKind,
        *,
        turn: RuntimeTurnRef | None = None,
        item_id: str | None = None,
        payload: dict[str, JSONValue] | None = None,
    ) -> RuntimeEvent:
        safe_payload = {} if payload is None else payload
        return RuntimeEvent(
            event_id=f"codex:{self._assignment_digest}:{self._sequence}",
            assignment=self._assignment,
            kind=kind,
            thread=self._thread,
            turn=turn,
            item_id=item_id,
            source_sequence=self._sequence,
            payload=CanonicalJSON.from_mapping(safe_payload),
        )


def _identifier(label: str, value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise CodexRuntimeProtocolError(f"{label} is invalid")
    return value


def _mapping(value: Mapping[str, JSONValue], key: str) -> dict[str, JSONValue]:
    item = value.get(key)
    if not isinstance(item, dict) or not all(type(name) is str for name in item):
        raise CodexRuntimeProtocolError(f"{key} notification field is invalid")
    return item


def _choice(label: str, value: object, allowed: frozenset[str]) -> str:
    if type(value) is not str or value not in allowed:
        raise CodexRuntimeProtocolError(f"{label} is invalid")
    return value


def _method_digest(method: str) -> str:
    try:
        encoded = method.encode("utf-8")
    except UnicodeError:
        raise CodexRuntimeProtocolError("notification method is invalid") from None
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "CodexEventTranslator",
    "CodexRuntimeProtocolError",
    "is_kernel_tools_mcp_startup_update",
    "is_runtime_invalidation",
]
