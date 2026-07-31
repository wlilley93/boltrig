"""The inline fanout's bounded retry + outcome-row machinery (task #40).

Split from ``projections.py`` for the structural gate, and the seam is real
rather than convenient: this module owns HOW MANY TIMES a backend call runs and
WHAT THE ROW SAYS about it; ``projections.py`` owns what the operations ARE.

``fanout.retry_failed`` was advertised and read by nothing until 2026-07-31, so
a failed inline projection was never reattempted whatever it said. Now: true
gives a failed backend call exactly ONE bounded reattempt - inline execution
runs on the caller's request path, so a retry LOOP would turn a down backend
into a hung verb; the QUEUED path owns real budgets (max_operation_attempts).
False fails fast, and the row records max_operation_attempts=1 so a reader can
tell "we tried twice and it is down" from "fast-fail was chosen" without
consulting the manifest that was live at the time.
"""

from __future__ import annotations


class InlineRetryMixin:
    """Requires ``self._retry_failed``; provides the attempt loop + row builder."""

    def _outcome(
        self,
        *,
        tenant_id: str,
        projection_id: str,
        operation: str,
        status: str,
        fact_id: str | None,
        target: str | None,
        attempts: int,
        row_id: str,
        projection_ref: str | None = None,
        error: str | None = None,
    ):
        """One final status row, carrying the attempt budget that applied.

        max_operation_attempts on the row is what lets a reader tell "we tried
        twice and it is down" from "fast-fail was chosen" without consulting the
        manifest that was live at the time.
        """
        from boltrig.memory.projections import _row  # local: avoids the cycle

        return _row(
            tenant_id=tenant_id,
            projection_id=projection_id,
            operation=operation,
            status=status,
            fact_id=fact_id,
            target=target,
            projection_ref=projection_ref,
            error=error,
            operation_attempts=attempts,
            max_operation_attempts=2 if self._retry_failed else 1,
            row_id=row_id,
        )

    async def _attempt(self, operation):
        """Run one backend call with the bounded inline retry.

        Returns (result, error, attempts). One reattempt, not a loop: inline
        execution runs on the caller's request path, so unbounded retry would
        turn a down backend into a hung verb. The QUEUED path owns real retry
        budgets (max_operation_attempts); this is the inline path's honest
        minimum for `retry_failed: true`.
        """
        attempts = 0
        last_exc: Exception | None = None
        budget = 2 if self._retry_failed else 1
        while attempts < budget:
            attempts += 1
            try:
                return await operation(), None, attempts
            except Exception as exc:
                last_exc = exc
        return None, last_exc, attempts
