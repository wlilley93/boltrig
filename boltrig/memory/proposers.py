"""Per-plane parameter mapping for ``memory.propose`` (decision 0029).

The write gate takes explicit typed arguments (it is the deterministic policy
layer); untyped request params are an ADAPTER concern. These small proposers
are the only place a ``memory.propose`` params dict is unpacked into the
gate's keyword contract, one class per plane.
"""

from __future__ import annotations

from .typology import EPISODIC, PROCEDURAL, SEMANTIC


def _confidence(params: dict) -> float:
    return min(max(float(params.get("confidence", 0.0) or 0.0), 0.0), 1.0)


def _opt_bool(value) -> bool | None:
    return None if value is None else bool(value)


class SemanticProposer:
    plane = SEMANTIC

    def __init__(self, gate) -> None:
        self._gate = gate

    async def run(self, tenant: str, owner_scope: str, text: str, params: dict):
        return await self._gate.propose_semantic(
            tenant,
            subject_type=str(params.get("subject_type") or ""),
            subject_id=str(params.get("subject_id") or ""),
            predicate=str(params.get("predicate") or ""),
            value=params.get("value"),
            statement=text,
            owner_scope=owner_scope,
            confidence=_confidence(params),
            source_authority=params.get("source_authority"),
            source_kind=str(params.get("source_kind") or "verb_result"),
            source_ref=params.get("source_ref"),
            is_durable=_opt_bool(params.get("is_durable")),
        )


class EpisodicProposer:
    plane = EPISODIC

    def __init__(self, gate) -> None:
        self._gate = gate

    async def run(self, tenant: str, owner_scope: str, text: str, params: dict):
        return await self._gate.propose_episodic(
            tenant,
            title=str(params.get("title") or "episode"),
            retrieval_text=text,
            outcome=str(params.get("outcome") or ""),
            is_terminal=bool(params.get("is_terminal", False)),
            owner_scope=owner_scope,
            situation=str(params.get("situation") or ""),
            attempted=[str(a) for a in params.get("attempted") or []],
            failed_attempts=[str(a) for a in params.get("failed_attempts") or []],
            root_cause=params.get("root_cause"),
            resolution=params.get("resolution"),
            task_family=str(params.get("task_family") or "general"),
            tools_used=[str(t) for t in params.get("tools_used") or []],
            environment=dict(params.get("environment") or {}),
            outcome_evidence=[str(e) for e in params.get("outcome_evidence") or []],
            confidence=_confidence(params),
            source_kind=str(params.get("source_kind") or "verb_result"),
            source_ref=params.get("source_ref"),
        )


class ProceduralProposer:
    plane = PROCEDURAL

    def __init__(self, gate) -> None:
        self._gate = gate

    async def run(self, tenant: str, owner_scope: str, text: str, params: dict):
        return await self._gate.propose_procedural(
            tenant,
            procedure_key=str(params.get("procedure_key") or ""),
            title=str(params.get("title") or ""),
            body_markdown=str(params.get("body_markdown") or ""),
            owner_scope=owner_scope,
            summary=str(params.get("summary") or ""),
            applies_to_roles=[str(r) for r in params.get("applies_to_roles") or []],
            applies_to_workflows=[str(w) for w in params.get("applies_to_workflows") or []],
            invariants=[str(i) for i in params.get("invariants") or []],
            prohibited_actions=[str(p) for p in params.get("prohibited_actions") or []],
            confidence=_confidence(params),
            source_kind=str(params.get("source_kind") or "feedback"),
            source_ref=params.get("source_ref"),
        )


def proposer_for(gate, plane: str):
    proposers = {
        SEMANTIC: SemanticProposer,
        EPISODIC: EpisodicProposer,
        PROCEDURAL: ProceduralProposer,
    }
    return proposers[plane](gate)


__all__ = [
    "EpisodicProposer",
    "ProceduralProposer",
    "SemanticProposer",
    "proposer_for",
]
