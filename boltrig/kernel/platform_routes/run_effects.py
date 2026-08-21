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

import uuid
from typing import Any

from fastapi import HTTPException

from boltrig.models import InvocationContext, RunEffect

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
    return InvocationContext(
        tenant_id=p.tenant_id,
        run_id=uuid.uuid4().hex,
        actor="effect-revert",
        on_behalf_of=p.subject,
        workspace_id=p.active_workspace_id,
        grants=p.grants,
        extra={"effect_revert": run_id},
    )


async def _revert_one(k: Any, context: InvocationContext, effect: RunEffect) -> str:
    assert effect.inverse_verb is not None
    noun = effect.inverse_verb.split(".", 1)[0]
    try:
        await k.invoke(noun, effect.inverse_verb, dict(effect.inverse_params), context)
    except Exception:
        return "revert_failed"
    return "reverted"


async def revert_run_effects(k: Any, p: Any, run_id: str) -> list[dict[str, Any]]:
    """The whole revert loop, importable so tests drive the SHIPPED loop.

    Newest-first over the run's ledger: settled rows are reported as they
    stand, ``recorded`` rows are claimed by CAS (to ``revert_failed``, the
    honest state if we die mid-inverse) and promoted to ``reverted`` only
    after their inverse returns.
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
        outcome = await _revert_one(k, context, effect)
        if outcome == "reverted":
            await k.store.settle_run_effect(
                p.tenant_id, run_id, effect.seq,
                expected="revert_failed", status="reverted",
            )
        results.append({**_view(effect), "outcome": outcome})
    return results


def register(app: Any, P: Any, K: Any) -> None:
    @app.get("/v1/runs/{run_id}/effects")  # type: ignore[untyped-decorator]
    async def list_effects(run_id: str, k: Any = K, p: Any = P) -> dict[str, Any]:
        effects = await _visible_effects(k, p, run_id)
        return {"run_id": run_id, "effects": [_view(e) for e in effects]}

    @app.post("/v1/runs/{run_id}/revert")  # type: ignore[untyped-decorator]
    async def revert_run(run_id: str, k: Any = K, p: Any = P) -> dict[str, Any]:
        return {"run_id": run_id, "results": await revert_run_effects(k, p, run_id)}
