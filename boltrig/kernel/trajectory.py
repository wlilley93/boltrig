"""The trajectory recorder: a fail-safe side-channel, off by default.

THE SAME SHAPE AS THE OTHER TWO SIDE-CHANNELS. `Dispatcher` already carries an
optional run-event relay and an optional SecurityEvent stream, both documented
as never affecting the dispatch decision and never breaking a call when they
fail (P9). A trajectory that could break a turn would be worse than no
trajectory, so it joins them rather than inventing a third discipline.

OFF UNLESS ASKED. This stream is verbatim -- whole prompts, whole tool payloads,
whole results -- which is the entire point and also the reason it cannot be on
by default. A tenant turns it on deliberately (``BOLTRIG_TRAJECTORY=1``, or a
per-call recorder), rows carry an expiry, and there is a purge. Compare
``kernel/audit.py``, which is always on precisely because it is scrubbed.

WHAT IT REFUSES TO WRITE. Two bounds, both of which cost information on purpose:

  * SIZE. A payload is capped and truncated with a marker rather than dropped,
    because a debugging record that silently discarded the big tool result is
    worse than one that says "6 MB, truncated at 64 KB".
  * CREDENTIALS. Values under obviously-secret keys are replaced before the row
    is built. The audit log's scrubber exists for the compliance chain; this is
    a much cruder guard on a stream that is otherwise deliberately verbatim,
    and it is NOT a substitute for not putting secrets in tool params.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from boltrig.models import InvocationContext, TrajectoryKind

log = logging.getLogger("boltrig.kernel.trajectory")

# READ FROM os.environ RATHER THAN boltrig.config.environment.is_truthy, which
# is the same three lines. Importing config here pulls config -> identity ->
# kernel.app -> kernel and the kernel cannot finish initialising itself.
# ``kernel/audit.py`` reads os.environ directly for the same reason.
_TRUE_VALUES = {"1", "true", "yes", "on", "y", "t"}


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE_VALUES

MAX_PAYLOAD_CHARS = 64_000
"""Per string value. Chosen against a real tool result rather than a round
number: a page of HTML fits, a downloaded file does not."""

_SECRET_HINTS = (
    "password", "secret", "token", "api_key", "apikey", "authorization",
    "credential", "private_key", "access_key", "bearer", "cookie", "session_id",
)

REDACTED = "[redacted]"
TRUNCATED = "[truncated {dropped} chars]"


def _looks_secret(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in _SECRET_HINTS)


def bound_payload(value: Any, *, depth: int = 0) -> Any:
    """``bound_payload`` caps and redacts, recursively.

    Total function: it never raises on odd input.

    Depth-limited because a tool result can be arbitrarily nested and a
    recorder that blows the stack has failed at its one job.
    """
    if depth > 12:
        return "[too deeply nested]"
    if isinstance(value, dict):
        return {
            key: (REDACTED if _looks_secret(str(key)) else bound_payload(item, depth=depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [bound_payload(item, depth=depth + 1) for item in value[:200]]
    if isinstance(value, str) and len(value) > MAX_PAYLOAD_CHARS:
        dropped = len(value) - MAX_PAYLOAD_CHARS
        return value[:MAX_PAYLOAD_CHARS] + TRUNCATED.format(dropped=dropped)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)[:MAX_PAYLOAD_CHARS]


class TrajectoryRecorder:
    """Writes trajectory rows, or does nothing at all.

    A disabled recorder is a live object whose ``record`` returns immediately,
    rather than a None the caller must check. Every call site would otherwise
    grow the same ``if self._trajectory is not None`` and one of them would
    eventually forget.
    """

    def __init__(self, store: Any, *, enabled: bool | None = None, ttl_days: int = 14) -> None:
        self._store = store
        self._ttl_days = ttl_days
        self._enabled = (
            _is_truthy(os.environ.get("BOLTRIG_TRAJECTORY")) if enabled is None else enabled
        )

    @property
    def enabled(self) -> bool:
        return self._enabled and self._store is not None

    async def record(
        self,
        context: InvocationContext,
        kind: TrajectoryKind,
        payload: dict[str, Any],
    ) -> None:
        """``record`` appends one row, and never raises into the caller.

        A run with no id is not recorded rather than being filed under a
        placeholder: a trajectory is per run, and rows that belong to "unknown"
        would interleave every unattributed call in the tenant into one
        unreadable stream.
        """
        if not self.enabled or not context.run_id:
            return
        try:
            await self._store.append_trajectory(
                context.tenant_id,
                context.run_id,
                kind,
                bound_payload(payload),
                actor=context.actor,
                parent_run_id=context.parent_run_id,
                depth=context.depth,
                ttl_days=self._ttl_days,
            )
        except Exception as error:  # noqa: BLE001 - observability must not break a turn
            log.warning("trajectory write failed (%s): %s", kind.value, error)


class NullTrajectoryRecorder(TrajectoryRecorder):
    """Explicitly records nothing, for callers with no store to hand."""

    def __init__(self) -> None:
        super().__init__(None, enabled=False)


class RecordingDispatcher:
    """Records each ``invoke`` on the trajectory, and changes nothing else.

    A DECORATOR RATHER THAN AN EDIT TO THE CHOKEPOINT. ``Dispatcher.invoke`` is
    the one function every external action funnels through, with a fixed audited
    order; recording inline grew it by eleven lines and the file by twenty-six,
    and the structure ratchet refused -- correctly. Wrapping records the same
    call and the same outcome while leaving the dispatch decision, its ordering
    and its audit byte-for-byte unchanged.

    Everything that is not ``invoke`` is delegated by ``__getattr__``, so the
    kernel, the fleet and the tests keep using the dispatcher they already know.

    THE CALL ID IS THIS WRAPPER'S OWN. Dispatch mints one internally to pair its
    run events; reaching in for it would couple the two, so the pair here is
    correlated by an id the wrapper controls.
    """

    _OWN = frozenset({"_inner", "_recorder"})

    def __init__(self, inner: Any, recorder: TrajectoryRecorder) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_recorder", recorder)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """WRITES GO THROUGH TOO, or the proxy is only half transparent.

        Delegating reads but not writes is the subtle half of this bug: the
        chokepoint-order and HITL tests swap collaborators in by assignment
        (``k.dispatcher._creds = rec``), which silently landed on the WRAPPER
        while the real dispatcher kept its original. The call then behaved
        correctly and the assertion about the double failed, which reads as a
        broken chokepoint rather than a broken test double.
        """
        if name in RecordingDispatcher._OWN:
            object.__setattr__(self, name, value)
        else:
            setattr(self._inner, name, value)

    def __delattr__(self, name: str) -> None:
        delattr(self._inner, name)

    async def invoke(
        self,
        noun: str,
        verb: str,
        params: dict[str, Any],
        context: InvocationContext,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self._recorder.enabled:
            # The overwhelmingly common path: one attribute lookup, then the
            # real dispatcher. Nothing about a disabled trajectory should cost
            # a turn anything measurable.
            return await self._inner.invoke(noun, verb, params, context, **kwargs)

        call_id = uuid.uuid4().hex
        # VERBATIM, where the run event beside it carries a redacted projection.
        # That difference is the whole feature: a summary cannot answer "why did
        # it say that". Bounding and secret-scrubbing happen in the recorder.
        await self._recorder.record(
            context,
            TrajectoryKind.TOOL_CALL,
            {"call_id": call_id, "noun": noun, "verb": verb, "params": params},
        )
        try:
            result = await self._inner.invoke(noun, verb, params, context, **kwargs)
        except Exception as error:
            # Recorded, then re-raised unchanged. A turn that failed is exactly
            # the turn somebody will want to read back, and swallowing the
            # exception to write a row would be the observability tail wagging
            # the dispatch dog.
            await self._recorder.record(
                context,
                TrajectoryKind.ERROR,
                {"call_id": call_id, "verb": verb, "error": type(error).__name__,
                 "detail": str(error)},
            )
            raise
        await self._recorder.record(
            context,
            TrajectoryKind.TOOL_RESULT,
            {"call_id": call_id, "verb": verb, "result": result},
        )
        return result
