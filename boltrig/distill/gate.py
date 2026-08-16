"""Promotion gates for sleep distillation (decision 0023, DIS-5..7).

The live register gate is MECHANICAL - no LLM judge anywhere. A judge would make the
ratchet a matter of opinion, and the opinion would come from the model being
judged (0023, "Refused").

* register - mean held-out token log-likelihood of the tenant's ACCEPTED
             assistant turns, candidate vs incumbent, on the split pinned by
             the corpus digest. Objective, cheap, judge-free.

The verdict functions are pure so the invariant tests bind arithmetic, not
plumbing; the adapter owns store/audit/sidecar I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

# A register candidate must beat the incumbent by a sliver more than float
# noise: equality is a hold (the incumbent keeps its seat on a tie).
_REGISTER_EPSILON = 1e-9

# Entropy guard (DIS-9): a candidate whose sampled generations carry less than
# this fraction of the incumbent's distinct-n diversity is held regardless of
# likelihood. Likelihood measures fitting the accepted turns; nothing else in
# the register gate notices that the fit was bought by collapsing onto a
# template - the silent-collapse failure mode (Karpathy/Dwarkesh 2025-10).
_DIVERSITY_FLOOR = 0.8


@dataclass(frozen=True)
class GateVerdict:
    promote: bool
    reason: str
    incumbent_score: float
    candidate_score: float
    regressed_cases: tuple[str, ...] = ()
    incumbent_diversity: float | None = None
    candidate_diversity: float | None = None


def register_verdict(
    incumbent_loglik: float,
    candidate_loglik: float,
    *,
    incumbent_diversity: float | None = None,
    candidate_diversity: float | None = None,
) -> GateVerdict:
    """Promote iff the candidate finds the held-out accepted turns strictly
    more likely than the incumbent does, AND its sampled generations keep at
    least the diversity floor relative to the incumbent (DIS-9). A tie keeps
    the incumbent; a likelihood win bought by collapse is a hold."""
    if (
        incumbent_diversity is not None
        and candidate_diversity is not None
        and candidate_diversity < _DIVERSITY_FLOOR * incumbent_diversity
    ):
        return GateVerdict(
            False, "entropy_collapse", incumbent_loglik, candidate_loglik,
            incumbent_diversity=incumbent_diversity,
            candidate_diversity=candidate_diversity,
        )
    if candidate_loglik > incumbent_loglik + _REGISTER_EPSILON:
        return GateVerdict(
            True, "promote", incumbent_loglik, candidate_loglik,
            incumbent_diversity=incumbent_diversity,
            candidate_diversity=candidate_diversity,
        )
    return GateVerdict(
        False, "held_out_likelihood_not_improved", incumbent_loglik, candidate_loglik,
        incumbent_diversity=incumbent_diversity,
        candidate_diversity=candidate_diversity,
    )
