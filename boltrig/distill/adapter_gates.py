"""The two gate legs the ``distill.gate`` verb runs (decision 0023, DIS-6).

Split from the adapter so each stays a focused surface: the adapter owns
sidecar I/O and audit receipts; these functions own how a candidate is scored.

* ``register_gate`` asks the sidecar for held-out mean log-likelihood under
  each model (no fleet-runtime logprob support exists, deliberately - the
  sidecar route keeps the legacy runtime lane untouched).
* ``craft_gate`` replays the tenant's active eval cases through the
  composition-owned EvalRunner, routing each run at the named model via the
  model-profile context seam (``fleet/model_profiles.py``). That seam
  deliberately bypasses the store ``is_active`` check - correct here, because
  the candidate is inactive BY DESIGN until promoted (DIS-5); production
  serving still resolves through the store, which enforces retirement.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Awaitable, Callable

from boltrig.adapters.base import AdapterError, ErrorClass
from boltrig.distill.gate import CaseScore, GateVerdict, craft_verdict, register_verdict
from boltrig.models import InvocationContext

# The adapter's sidecar carrier: (method, url, payload) -> parsed body or error.
SidecarCall = Callable[[str, str, Any], Awaitable[dict[str, Any] | AdapterError]]


async def register_gate(
    call: SidecarCall, digest: str, incumbent: str, candidate: str
) -> GateVerdict | AdapterError:
    scores: dict[str, float] = {}
    for name in (incumbent, candidate):
        ll = await call("POST", "/loglik", {"corpus_digest": digest, "model": name})
        if isinstance(ll, AdapterError):
            return ll
        try:
            scores[name] = float(ll["mean_loglik"])
        except (KeyError, TypeError, ValueError):
            return AdapterError(
                ErrorClass.INVALID, "sidecar returned no mean_loglik",
                retryable=False,
            )
    return register_verdict(scores[incumbent], scores[candidate])


async def craft_gate(
    eval_runner: Any,
    store: Any,
    serve_url: str | None,
    context: InvocationContext,
    incumbent: str,
    candidate: str,
) -> GateVerdict | AdapterError:
    if eval_runner is None:
        return AdapterError(
            ErrorClass.UNAVAILABLE,
            "craft gate needs the composition eval runner (not bound)",
            retryable=False,
        )
    if not serve_url:
        # The TRAINER sidecar serves no chat completions; routing eval traffic
        # at it would fail on every case. A craft gate needs a chat-serving
        # endpoint for the candidate (mlx_lm.server) named by distill.serve_url
        # - absent that, refuse typed rather than fail confusingly downstream.
        return AdapterError(
            ErrorClass.UNAVAILABLE,
            "craft gate needs distill.serve_url (a chat-serving endpoint for "
            "candidates); the trainer sidecar serves no /v1/chat/completions",
            retryable=False,
        )
    cases = [
        case for case in await store.list_eval_cases(context.tenant_id)
        if case.is_active
    ]
    if not cases:
        return AdapterError(
            ErrorClass.INVALID,
            "craft gate refused: tenant has no active eval cases, so a "
            "candidate cannot be distinguished from a regression",
            retryable=False,
        )
    results: dict[str, list[CaseScore]] = {incumbent: [], candidate: []}
    for model in (incumbent, candidate):
        for case in cases:
            ctx = replace(
                context,
                extra={
                    **dict(case.input or {}),
                    "model_profile": "distill-gate",
                    "model_profiles": {
                        "distill-gate": {
                            "provider": "openai",
                            "model": model,
                            "base_url": serve_url,
                        }
                    },
                },
            )
            run = await eval_runner.run_case(case, grants=context.grants, context=ctx)
            results[model].append(CaseScore(case.id, run.passed, run.score))
    return craft_verdict(results[incumbent], results[candidate])
