"""Bounded scope-aware cancellation observation for model-proxy handoffs."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import TypeAlias

from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyAssignmentScope,
    ModelProxyCellScope,
    ModelProxyPhaseScope,
    ModelProxyRootScope,
)

MAX_TRACKED_MODEL_PROXY_CANCELLATIONS = 2_048
MAX_MODEL_PROXY_CANCELLATION_HISTORY = 4_096

ModelProxyCancellationScope: TypeAlias = (
    ModelProxyRootScope | ModelProxyPhaseScope | ModelProxyAssignmentScope | ModelProxyCellScope
)
CancelToken: TypeAlias = int | None


class ModelProxyCancellationTracker:
    """Detect only cancellations overlapping a cell, with bounded fail-closed overflow."""

    __slots__ = (
        "_change",
        "_history",
        "_inflight",
        "_next_token",
        "_overflow",
        "_sequence",
    )

    def __init__(self) -> None:
        self._change = asyncio.Event()
        self._history: deque[tuple[int, ModelProxyCancellationScope]] = deque(
            maxlen=MAX_MODEL_PROXY_CANCELLATION_HISTORY
        )
        self._inflight: dict[int, ModelProxyCancellationScope] = {}
        self._next_token = 0
        self._overflow = 0
        self._sequence = 0

    @property
    def sequence(self) -> int:
        return self._sequence

    def begin(self, scope: ModelProxyCancellationScope) -> CancelToken:
        _require_scope(scope)
        self._next_token += 1
        token: CancelToken = self._next_token
        if len(self._inflight) < MAX_TRACKED_MODEL_PROXY_CANCELLATIONS:
            self._inflight[self._next_token] = scope
        else:
            self._overflow += 1
            token = None
        self._record(scope)
        return token

    def finish(self, scope: ModelProxyCancellationScope, token: CancelToken) -> None:
        _require_scope(scope)
        if token is None:
            if self._overflow <= 0:
                raise RuntimeError("model-proxy cancellation overflow underflow")
            self._overflow -= 1
        elif self._inflight.pop(token, None) != scope:
            raise RuntimeError("model-proxy cancellation token mismatch")
        self._record(scope)

    async def must_retry(self, observed: int, cell: ModelProxyCellScope) -> bool:
        if type(observed) is not int or observed < 0:
            raise ValueError("observed cancellation sequence must be non-negative")
        if type(cell) is not ModelProxyCellScope:
            raise TypeError("cell must be an exact ModelProxyCellScope")
        change = self._change
        if self._overflow or any(_covers(scope, cell) for scope in self._inflight.values()):
            await change.wait()
            return True
        if not self._history or observed == self._sequence:
            return False
        if observed < self._history[0][0] - 1:
            return True
        return any(
            sequence > observed and _covers(scope, cell) for sequence, scope in self._history
        )

    def _record(self, scope: ModelProxyCancellationScope) -> None:
        self._sequence += 1
        self._history.append((self._sequence, scope))
        previous = self._change
        self._change = asyncio.Event()
        previous.set()


def _require_scope(scope: object) -> None:
    if type(scope) not in (
        ModelProxyRootScope,
        ModelProxyPhaseScope,
        ModelProxyAssignmentScope,
        ModelProxyCellScope,
    ):
        raise TypeError("scope must be an exact model-proxy cancellation scope")


def _covers(scope: ModelProxyCancellationScope, cell: ModelProxyCellScope) -> bool:
    if type(scope) is ModelProxyRootScope:
        return cell.assignment.phase.root == scope
    if type(scope) is ModelProxyPhaseScope:
        return cell.assignment.phase == scope
    if type(scope) is ModelProxyAssignmentScope:
        return cell.assignment == scope
    return cell == scope


__all__ = ["CancelToken", "ModelProxyCancellationScope", "ModelProxyCancellationTracker"]
