"""Bounded ordering state for observed Codex-native lifecycle notifications."""

from __future__ import annotations


class CodexRuntimeProtocolError(RuntimeError):
    """A stable notification violated checked ordering or quarantined policy."""


class NativeObservationState:
    """Detect native lifecycle drift; this cannot constrain App Server execution."""

    def __init__(
        self,
        *,
        max_concurrent: int,
        max_total: int,
        max_depth: int,
        max_items: int,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._max_total = max_total
        self._max_depth = max_depth
        self._max_items = max_items
        self._depths: dict[str, int] = {}
        self._parents: dict[str, str] = {}
        self._active: set[str] = set()
        self._turns: dict[str, str] = {}
        self._item_types: dict[tuple[str, str, str], str] = {}
        self._active_items: set[tuple[str, str, str]] = set()

    def start(self, root_id: str, thread_id: str, parent_id: str) -> int:
        if parent_id == root_id:
            depth = 1
        else:
            self.require_active(parent_id)
            depth = self._depths[parent_id] + 1
        if (
            self._max_total == 0
            or depth > self._max_depth
            or thread_id in self._depths
            or len(self._depths) >= self._max_total
            or len(self._active) >= self._max_concurrent
        ):
            raise CodexRuntimeProtocolError("native thread exceeded an observation tripwire")
        self._depths[thread_id] = depth
        self._parents[thread_id] = parent_id
        self._active.add(thread_id)
        return depth

    def close(self, thread_id: str) -> None:
        self.require_active(thread_id)
        if thread_id in self._turns or any(
            parent == thread_id and child in self._active
            for child, parent in self._parents.items()
        ):
            raise CodexRuntimeProtocolError("native thread closed with active work")
        self._active.remove(thread_id)

    def require_active(self, thread_id: str) -> None:
        if thread_id not in self._active:
            raise CodexRuntimeProtocolError("notification thread is outside the active phase tree")

    def transition_turn(
        self,
        method: str,
        thread_id: str,
        turn_id: str,
        status: str,
    ) -> None:
        self.require_active(thread_id)
        if method == "turn/started":
            if status != "inProgress" or thread_id in self._turns:
                raise CodexRuntimeProtocolError("native turn start is invalid")
            self._turns[thread_id] = turn_id
            return
        if status == "inProgress" or self._turns.get(thread_id) != turn_id:
            raise CodexRuntimeProtocolError("native turn completion is invalid")
        if any(key[:2] == (thread_id, turn_id) for key in self._active_items):
            raise CodexRuntimeProtocolError("native turn completed with active items")
        del self._turns[thread_id]

    def transition_item(
        self,
        method: str,
        thread_id: str,
        turn_id: str,
        item_id: str,
        item_type: str,
        *,
        root_item_count: int,
    ) -> None:
        self.require_active(thread_id)
        if self._turns.get(thread_id) != turn_id:
            raise CodexRuntimeProtocolError("native item turn is not active")
        key = (thread_id, turn_id, item_id)
        if method == "item/started":
            if key in self._item_types or (
                root_item_count + len(self._item_types) >= self._max_items
            ):
                raise CodexRuntimeProtocolError("native item start is invalid")
            self._item_types[key] = item_type
            self._active_items.add(key)
            return
        if self._item_types.get(key) != item_type or key not in self._active_items:
            raise CodexRuntimeProtocolError("native item completion is invalid")
        self._active_items.remove(key)

    def require_turn(self, thread_id: str, turn_id: str) -> None:
        self.require_active(thread_id)
        if self._turns.get(thread_id) != turn_id:
            raise CodexRuntimeProtocolError("native notification turn is not active")
