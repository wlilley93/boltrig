"""Promotion gates for sleep distillation (decision 0023, DIS-5..7).

Both gates are MECHANICAL - no LLM judge anywhere. A judge would make the
ratchet a matter of opinion, and the opinion would come from the model being
judged (0023, "Refused").

* craft    - the existing eval harness's scores, candidate vs incumbent, with
             a subset clause: a mean that rises while a previously-passing
             case silently breaks is a hold, not a promotion (DIS-6).
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


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    passed: bool
    score: float


@dataclass(frozen=True)
class GateVerdict:
    promote: bool
    reason: str
    incumbent_score: float
    candidate_score: float
    regressed_cases: tuple[str, ...] = ()


def _mean(scores: list[CaseScore]) -> float:
    return sum(s.score for s in scores) / len(scores) if scores else 0.0


def craft_verdict(
    incumbent: list[CaseScore], candidate: list[CaseScore]
) -> GateVerdict:
    """Promote iff mean(candidate) >= mean(incumbent) AND every case passing
    on the incumbent still passes on the candidate (DIS-6)."""
    if not candidate:
        return GateVerdict(False, "no_candidate_evidence", _mean(incumbent), 0.0)
    incumbent_mean = _mean(incumbent)
    candidate_mean = _mean(candidate)
    candidate_passed = {s.case_id for s in candidate if s.passed}
    regressed = tuple(
        sorted(
            s.case_id for s in incumbent if s.passed and s.case_id not in candidate_passed
        )
    )
    if regressed:
        return GateVerdict(
            False, "case_regression", incumbent_mean, candidate_mean, regressed
        )
    if candidate_mean < incumbent_mean:
        return GateVerdict(False, "mean_below_incumbent", incumbent_mean, candidate_mean)
    return GateVerdict(True, "promote", incumbent_mean, candidate_mean)


def register_verdict(
    incumbent_loglik: float, candidate_loglik: float
) -> GateVerdict:
    """Promote iff the candidate finds the held-out accepted turns strictly
    more likely than the incumbent does. A tie keeps the incumbent."""
    if candidate_loglik > incumbent_loglik + _REGISTER_EPSILON:
        return GateVerdict(True, "promote", incumbent_loglik, candidate_loglik)
    return GateVerdict(
        False, "held_out_likelihood_not_improved", incumbent_loglik, candidate_loglik
    )
