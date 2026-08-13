"""Persistent wire policy for one admitted Codex native-agent tree."""

from __future__ import annotations

import json
import threading

from boltrig.models.model_id_policy import exact_model_id

from .model_proxy_ceiling_errors import ToolCeilingViolation

CODEX_NATIVE_COLLAB_NAMESPACE_NAME = "multi_agent_v1"
CODEX_NATIVE_COLLAB_TOOLS = frozenset(
    {"spawn_agent", "send_input", "resume_agent", "wait_agent", "close_agent"}
)


class NativeCollaborationWireGate:
    """Bound lifetime spawns and refuse non-admitted child overrides."""

    __slots__ = (
        "_allowed_model",
        "_allowed_reasoning_effort",
        "_lock",
        "_max_total",
        "_spawn_calls",
    )

    def __init__(
        self,
        *,
        max_total: int,
        allowed_model: str,
        allowed_reasoning_effort: str,
    ) -> None:
        if type(max_total) is not int or not 1 <= max_total <= 64:
            raise ValueError("native collaboration max_total must be between 1 and 64")
        try:
            exact_model_id(allowed_model)
        except ValueError:
            raise ValueError("native collaboration model must be bounded and non-empty")
        if (
            type(allowed_reasoning_effort) is not str
            or not allowed_reasoning_effort
            or len(allowed_reasoning_effort) > 32
        ):
            raise ValueError(
                "native collaboration reasoning effort must be bounded and non-empty"
            )
        self._max_total = max_total
        self._allowed_model = allowed_model
        self._allowed_reasoning_effort = allowed_reasoning_effort
        self._spawn_calls: dict[str, str] = {}
        self._lock = threading.Lock()

    @property
    def spawn_count(self) -> int:
        with self._lock:
            return len(self._spawn_calls)

    @property
    def allowed_model(self) -> str:
        return self._allowed_model

    @property
    def allowed_reasoning_effort(self) -> str:
        return self._allowed_reasoning_effort

    def validate_complete_call(self, call: dict[str, object]) -> None:
        name = call.get("name")
        if name not in CODEX_NATIVE_COLLAB_TOOLS:
            raise ToolCeilingViolation("native collaboration tool is outside stable V1")
        call_id = call.get("call_id")
        arguments = call.get("arguments")
        if (
            not isinstance(call_id, str)
            or not call_id
            or len(call_id) > 256
            or not isinstance(arguments, str)
            or len(arguments.encode("utf-8")) > 1024 * 1024
        ):
            raise ToolCeilingViolation("native collaboration call is not exactly bounded")
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as error:
            raise ToolCeilingViolation(
                "native collaboration arguments are not parseable JSON"
            ) from error
        if not isinstance(parsed, dict):
            raise ToolCeilingViolation("native collaboration arguments are not an object")
        if name != "spawn_agent":
            return
        self._validate_spawn_overrides(parsed)
        signature = json.dumps(
            parsed, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        with self._lock:
            previous = self._spawn_calls.get(call_id)
            if previous is not None:
                if previous != signature:
                    raise ToolCeilingViolation(
                        "native spawn call id was reused with different arguments"
                    )
                return
            if len(self._spawn_calls) >= self._max_total:
                raise ToolCeilingViolation(
                    "native collaboration total spawn budget exhausted"
                )
            self._spawn_calls[call_id] = signature

    def _validate_spawn_overrides(self, parsed: dict[str, object]) -> None:
        if parsed.get("model") not in (None, "", self._allowed_model):
            raise ToolCeilingViolation("native child model override exceeds the ceiling")
        if parsed.get("reasoning_effort") not in (
            None,
            "",
            self._allowed_reasoning_effort,
        ):
            raise ToolCeilingViolation(
                "native child reasoning effort override exceeds the ceiling"
            )
        if parsed.get("service_tier") not in (None, ""):
            raise ToolCeilingViolation("native child service tier is not admitted")
