"""Reading and exporting a run's trajectory (Decision TRJ-01).

GATED ON RUN VISIBILITY, NOT ON TENANCY. Every other route that serves
run-scoped content goes through ``visible_work_item_by_run``, which enforces the
caller's workspace as well as the tenant. The trajectory holds MORE than those
streams do -- the whole prompt, the whole tool payload -- so it uses the same
gate rather than a weaker one. Tenancy alone would let anyone in an
organisation read the verbatim contents of anyone else's run.

A run nobody can see is 404, not 403: telling a caller that a run exists but is
not theirs is itself a leak about other people's activity.

EXPORT IS JSONL, one event per line, in sequence. It is what a person hands to a
script, so it is deliberately not wrapped in an envelope object -- streaming a
million-line array of JSON is a worse shape for every consumer than a million
lines of JSON.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse

from boltrig.kernel.run_access import visible_work_item_by_run

_PAGE = 500
"""Rows per read. Bounded because a trajectory has no natural size and an
unbounded read is how one debugging session takes the API down."""


def register_trajectory_routes(app, principal_dep, get_kernel) -> None:
    P = Depends(principal_dep)
    K = Depends(get_kernel)

    async def _require_visible(k, p, run_id: str) -> None:
        if await visible_work_item_by_run(k.store, p, run_id) is None:
            # 404 rather than 403 on purpose -- see the module docstring.
            raise HTTPException(status_code=404, detail="run not found")

    @app.get("/v1/trajectory")
    async def list_runs(limit: int = 50, k=K, p=P) -> dict:
        """Runs that have a trajectory, most recent first.

        No visibility filter is applied to the LIST because a run id is not
        content; the rows behind each id are gated individually below.
        """
        runs = await k.trajectory_store.list_trajectory_runs(p.tenant_id, limit=min(limit, 200))
        return {"runs": runs, "enabled": k.trajectory.enabled}

    @app.get("/v1/trajectory/{run_id}")
    async def read_run(run_id: str, after_seq: int = 0, k=K, p=P) -> dict:
        """One page of a run's trajectory, in sequence.

        ``after_seq`` is a resume cursor rather than an offset, so a client
        polling a live run never re-reads or skips a row when the run grows
        between requests.
        """
        await _require_visible(k, p, run_id)
        rows = await k.trajectory_store.read_trajectory(
            p.tenant_id, run_id, after_seq=after_seq, limit=_PAGE
        )
        return {
            "run_id": run_id,
            "events": [row.to_jsonl_row() for row in rows],
            "next_seq": rows[-1].seq if rows else after_seq,
            "complete": len(rows) < _PAGE,
        }

    @app.get("/v1/trajectory/{run_id}/export")
    async def export_run(run_id: str, k=K, p=P) -> StreamingResponse:
        """The whole run as JSONL, streamed a page at a time.

        Streamed rather than assembled: a long run is larger than anything worth
        holding in memory to serialise, and the caller can begin reading the
        first turn while the last is still being fetched.
        """
        await _require_visible(k, p, run_id)

        async def lines() -> AsyncIterator[bytes]:
            cursor = 0
            while True:
                rows = await k.trajectory_store.read_trajectory(
                    p.tenant_id, run_id, after_seq=cursor, limit=_PAGE
                )
                if not rows:
                    return
                for row in rows:
                    yield (json.dumps(row.to_jsonl_row()) + "\n").encode()
                cursor = rows[-1].seq

        return StreamingResponse(
            lines(),
            media_type="application/x-ndjson",
            headers={"content-disposition": f'attachment; filename="{run_id}.jsonl"'},
        )

    @app.delete("/v1/trajectory/{run_id}")
    async def purge_run(run_id: str, k=K, p=P) -> dict:
        """Delete a run's verbatim record.

        Deliberately available to whoever can read it: this stream exists to be
        disposable, and someone who realises they pasted something into a
        recorded run should be able to remove it without an administrator. The
        AUDIT row for that same run is untouched and is not deletable here --
        the compliance record is not what this route serves.
        """
        await _require_visible(k, p, run_id)
        return {"run_id": run_id, "deleted": await k.trajectory_store.purge_trajectory(p.tenant_id, run_id)}
