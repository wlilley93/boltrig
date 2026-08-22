"""Append a successful invocation to the durable run-effect ledger.

Called by ``Dispatcher.invoke`` on the success path only - a failed call
changed nothing worth undoing. Its own module because ``dispatch.py`` sits at
a frozen structural-debt ceiling, and because the recording POLICY (what is
worth a ledger row) is a judgement worth reading in one place:

  * ``meta["gated"]`` - the approval gate's own consequence verdict - is the
    primary filter, so the undo ledger and the HITL gate agree about what
    counts as consequential. A verb ``effect_inverses`` knows is recorded
    even ungated: a reversible convenience is still worth offering back.
  * A revert run records NOTHING (``context.extra["effect_revert"]``): the
    inverse of an inverse is the original effect, and re-recording it would
    let one undo bounce forever.
  * Recording failure NEVER fails the call - the invocation already
    succeeded; a bookkeeping error becomes a log line, not a user error.
    Fail-open here is deliberate and bounded: the ledger under-reporting an
    effect yields a missing undo affordance, never a wrong action.
"""

from __future__ import annotations

import logging
from typing import Any

from boltrig.models import InvocationContext, RunEffect

from .effect_inverses import inverse_for

logger = logging.getLogger(__name__)

#: Matches the audit row's params bound; the ledger label is for humans (K-20).
_SUMMARY_BOUND = 200


async def record_run_effect(
    store: Any,
    verb: str,
    params: dict[str, Any],
    output: dict[str, Any] | None,
    context: InvocationContext,
    meta: dict[str, Any],
    *,
    summarise: Any,
) -> None:
    if not context.run_id or (context.extra or {}).get("effect_revert"):
        return
    inverse = inverse_for(verb, params, output)
    if not meta.get("gated") and inverse is None:
        return
    inverse_verb, inverse_params = inverse if inverse else (None, {})
    try:
        await store.record_run_effect(
            RunEffect(
                tenant_id=context.tenant_id,
                run_id=context.run_id,
                seq=0,  # the store assigns the real seq atomically
                verb_id=verb,
                status="recorded" if inverse_verb else "not_undoable",
                inverse_verb=inverse_verb,
                inverse_params=inverse_params,
                summary=str(summarise(params))[:_SUMMARY_BOUND],
            )
        )
    except Exception:
        logger.warning("run effect not recorded for %s", verb, exc_info=True)
