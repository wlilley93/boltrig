"""Typed-memory bundle configuration (decision 0029).

``MemoryConfig`` plane toggles and per-plane character budgets. Kept separate
from the assembly code so the ablation matrix (flipping one plane off must not
touch retrieval code) is a configuration concern, and so the manifest defaults
and per-call overrides share one merge point. Budgets are characters (approx 4
chars/token): no tokenizer dependency ships, and tests stay offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class RecallMode:
    TYPED = "typed"
    LEGACY = "legacy"
    NONE = "none"


@dataclass(frozen=True)
class RecallBudget:
    semantic_chars: int = 4_800
    episodic_chars: int = 6_000
    procedural_chars: int = 10_000
    source_chars: int = 12_000

    semantic_items: int = 8
    episodic_items: int = 4
    procedures: int = 3
    source_chunks: int = 8


@dataclass(frozen=True)
class MemoryConfig:
    """Per-call plane toggles (the ablation matrix, spec section 18)."""

    recall_mode: str = RecallMode.TYPED
    semantic: bool = True
    episodic: bool = True
    procedural: bool = True
    source_knowledge: bool = True
    budget: RecallBudget = field(default_factory=RecallBudget)

    @property
    def label(self) -> str:
        if self.recall_mode == RecallMode.NONE:
            return "no-memory"
        if self.recall_mode == RecallMode.LEGACY:
            return "legacy-recall"
        disabled = [
            name
            for name, enabled in (
                ("semantic", self.semantic),
                ("episodic", self.episodic),
                ("procedural", self.procedural),
                ("source", self.source_knowledge),
            )
            if not enabled
        ]
        return "all-on" if not disabled else "no-" + "-".join(disabled)


def config_from_overrides(overrides: dict | None, *, defaults: dict | None = None) -> MemoryConfig:
    """Merge manifest defaults with per-call overrides (both untyped dicts)."""

    merged = {**(defaults or {}), **(overrides or {})}
    budget = RecallBudget(**{k: v for k, v in (merged.get("budget") or {}).items()})
    mode = str(merged.get("recall_mode", RecallMode.TYPED))
    if mode not in {RecallMode.TYPED, RecallMode.LEGACY, RecallMode.NONE}:
        mode = RecallMode.TYPED
    return MemoryConfig(
        recall_mode=mode,
        semantic=bool(merged.get("semantic", True)),
        episodic=bool(merged.get("episodic", True)),
        procedural=bool(merged.get("procedural", True)),
        source_knowledge=bool(merged.get("source_knowledge", True)),
        budget=budget,
    )


__all__ = [
    "MemoryConfig",
    "RecallBudget",
    "RecallMode",
    "config_from_overrides",
]
