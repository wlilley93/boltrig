"""The undo surface for a run: what it changed, and reversing what reverses.

GET lists the ledger so a client can render each step with its honest
undoability. POST walks the run's ``recorded`` effects newest-first and
executes each inverse THROUGH ``kernel.invoke`` - the same chokepoint that
performed the original call - so every compensation is granted, gated,
rate-limited and audited like any other action, and a high-consequence
inverse pends for a human exactly as its forward twin would have.

Two loops one cannot fall into by construction:

  * the revert context carries ``extra["effect_revert"]``, which the
    recorder treats as "record nothing" - undoing an undo cannot re-enter
    the ledger;
  * each row is settled by compare-and-swap (``settle_run_effect``) BEFORE
    its inverse runs, so two concurrent revert requests cannot execute the
    same inverse twice - the loser simply finds nothing left to settle.

Visibility is ``visible_work_item_by_run``: the caller must already be able
to see the run they are unwinding, workspace-fenced like every other run
read. ``not_undoable`` rows are reported, never attempted.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from boltrig.models import InvocationContext, RunEffect
from boltrig.models.errors import PendingHuman

from ..run_access import visible_work_item_by_run


def _view(effect: RunEffect) -> dict[str, Any]:
    return {
        "seq": effect.seq,
        "verb": effect.verb_id,
        "status": effect.status,
        "undoable": effect.status == "recorded",
        "summary": effect.summary,
        "created_at": effect.created_at.isoformat(),
    }


async def _visible_effects(k: Any, p: Any, run_id: str) -> list[RunEffect]:
    if await visible_work_item_by_run(k.store, p, run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    return await k.store.list_run_effects(p.tenant_id, run_id)


def _revert_context(p: Any, run_id: str) -> InvocationContext:
    # DETERMINISTIC revert run id: the approval fingerprint binds the
    # initiator's run_id (SEC-14), so a fresh uuid here would make the second
    # attempt a DIFFERENT action and the approved request could never release
    # it. One revert identity per run also groups its audit rows.
    return InvocationContext(
        tenant_id=p.tenant_id,
        run_id=f"revert:{run_id}",
        actor="effect-revert",
        on_behalf_of=p.subject,
        workspace_id=p.active_workspace_id,
        grants=p.grants,
        extra={"effect_revert": run_id},
    )


async def _revert_one(
    k: Any,
    context: InvocationContext,
    effect: RunEffect,
    approval_id: str | None,
) -> tuple[str, str | None]:
    """(outcome, hitl_request_id). A PENDING APPROVAL IS NOT A FAILURE: a
    high-consequence inverse pends for a human exactly like its forward twin,
    and coercing that into ``revert_failed`` would strand the row terminal
    with the effect still standing. The caller returns the row to
    ``recorded`` and reports the request id, so the client can answer it and
    revert again carrying ``approvals[seq]``."""
    assert effect.inverse_verb is not None
    noun = effect.inverse_verb.split(".", 1)[0]
    try:
        await k.invoke(
            noun,
            effect.inverse_verb,
            dict(effect.inverse_params),
            context,
            approval_id=approval_id,
        )
    except PendingHuman as pending:
        return "approval_pending", pending.hitl_request_id
    except Exception:
        return "revert_failed", None
    return "reverted", None


async def revert_run_effects(
    k: Any,
    p: Any,
    run_id: str,
    approvals: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """The whole revert loop, importable so tests drive the SHIPPED loop.

    Newest-first over the run's ledger: settled rows are reported as they
    stand, ``recorded`` rows are claimed by CAS (to ``revert_failed``, the
    honest state if we die mid-inverse) and promoted to ``reverted`` only
    after their inverse returns. A pending human approval settles the row
    BACK to ``recorded`` and reports ``approval_pending`` with the request
    id; the next revert carries ``approvals={seq: approval_id}`` and the
    SAME approved request releases the SAME inverse.
    """
    effects = await _visible_effects(k, p, run_id)
    context = _revert_context(p, run_id)
    results: list[dict[str, Any]] = []
    for effect in sorted(effects, key=lambda e: e.seq, reverse=True):
        if effect.status != "recorded":
            results.append({**_view(effect), "outcome": effect.status})
            continue
        claimed = await k.store.settle_run_effect(
            p.tenant_id, run_id, effect.seq,
            expected="recorded", status="revert_failed",
        )
        if not claimed:
            results.append({**_view(effect), "outcome": "already_settled"})
            continue
        outcome, hitl_id = await _revert_one(
            k, context, effect, (approvals or {}).get(str(effect.seq))
        )
        if outcome == "reverted":
            await k.store.settle_run_effect(
                p.tenant_id, run_id, effect.seq,
                expected="revert_failed", status="reverted",
            )
        elif outcome == "approval_pending":
            await k.store.settle_run_effect(
                p.tenant_id, run_id, effect.seq,
                expected="revert_failed", status="recorded",
            )
        row = {**_view(effect), "outcome": outcome}
        if hitl_id:
            row["approval_id"] = hitl_id
        results.append(row)
    return results


def register(app: Any, P: Any, K: Any) -> None:
    @app.get("/v1/runs/{run_id}/effects")  # type: ignore[untyped-decorator]
    async def list_effects(run_id: str, k: Any = K, p: Any = P) -> dict[str, Any]:
        effects = await _visible_effects(k, p, run_id)
        return {"run_id": run_id, "effects": [_view(e) for e in effects]}

    @app.post("/v1/runs/{run_id}/revert")  # type: ignore[untyped-decorator]
    async def revert_run(
        run_id: str, body: dict | None = None, k: Any = K, p: Any = P
    ) -> dict[str, Any]:
        approvals = (body or {}).get("approvals") or {}
        approvals = {
            str(seq): str(approval)
            for seq, approval in approvals.items()
            if isinstance(approval, str) and approval
        }
        return {
            "run_id": run_id,
            "results": await revert_run_effects(k, p, run_id, approvals),
        }
