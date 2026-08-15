"""The two gate legs the ``distill.gate`` verb runs (decision 0023, DIS-6).

Split from the adapter so each stays a focused surface: the adapter owns
sidecar I/O and audit receipts; these functions own how a candidate is scored.

* ``register_gate`` asks the sidecar for held-out mean log-likelihood under
  each model; the trusted Codex runtime deliberately exposes no logprob seam.
* ``craft_gate`` is closed until candidate evaluation can bind an inactive
  candidate through the same governed Codex/Bifrost admission path as normal
  model execution. The retired provider-runtime context override must never be
  revived as a second routing authority.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from boltrig.adapters.base import AdapterError, ErrorClass
from boltrig.distill.gate import GateVerdict, register_verdict

# The adapter's sidecar carrier: (method, url, payload) -> parsed body or error.
SidecarCall = Callable[[str, str, Any], Awaitable[dict[str, Any] | AdapterError]]


async def register_gate(
    call: SidecarCall, digest: str, incumbent: str, candidate: str
) -> GateVerdict | AdapterError:
    scores: dict[str, float] = {}
    diversity: dict[str, float] = {}
    for name in (incumbent, candidate):
        ll = await call("POST", "/loglik", {"corpus_digest": digest, "model": name})
        if isinstance(ll, AdapterError):
            return ll
        # The entropy guard is deliberately STRICT: a sidecar that cannot
        # measure diversity fails the gate rather than silently waiving DIS-9
        # (both halves ship together, so skew here is a deployment error).
        dv = await call("POST", "/diversity", {"corpus_digest": digest, "model": name})
        if isinstance(dv, AdapterError):
            return dv
        try:
            scores[name] = float(ll["mean_loglik"])
            diversity[name] = float(dv["distinct_2"])
        except (KeyError, TypeError, ValueError):
            return AdapterError(
                ErrorClass.INVALID,
                "sidecar returned no mean_loglik/distinct_2",
                retryable=False,
            )
    return register_verdict(
        scores[incumbent],
        scores[candidate],
        incumbent_diversity=diversity[incumbent],
        candidate_diversity=diversity[candidate],
    )


async def craft_gate() -> GateVerdict | AdapterError:
    return AdapterError(
        ErrorClass.UNAVAILABLE,
        "craft gate is unavailable until inactive candidates can be evaluated "
        "through governed Codex/Bifrost model admission",
        retryable=False,
    )
