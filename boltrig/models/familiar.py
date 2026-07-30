"""Versioned cosmetic identity derived from an authoritative agent profile."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

FAMILIAR_GENOTYPE_SOURCE = "agent_capability.name.v1"

_BODIES = ("cassini", "kepler", "pioneer", "voyager")
_PALETTES = (
    ("#dbeafe", "#3b82f6", "#172554"),
    ("#ede9fe", "#8b5cf6", "#2e1065"),
    ("#cffafe", "#06b6d4", "#164e63"),
    ("#dcfce7", "#22c55e", "#14532d"),
    ("#ffedd5", "#f97316", "#7c2d12"),
    ("#fce7f3", "#ec4899", "#831843"),
)
_MARKINGS = ("arc", "constellation", "halo", "orbit")
_ACCESSORIES = ("antenna", "orbit-ring", "signal-pin")


@dataclass(frozen=True)
class FamiliarGenotype:
    """Identity-only birth configuration; never authority or runtime mood."""

    seed: int
    body: str
    palette: tuple[str, str, str]
    markings: tuple[str, ...]
    accessories: tuple[str, ...]
    source: str = field(default=FAMILIAR_GENOTYPE_SOURCE, init=False)
    voice_id: None = field(default=None, init=False)

    def as_view(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "seed": self.seed,
            "body": self.body,
            "palette": list(self.palette),
            "markings": list(self.markings),
            "accessories": list(self.accessories),
            "voice_id": self.voice_id,
        }


def derive_familiar_genotype(capability_name: str) -> FamiliarGenotype:
    """Derive a stable display identity from the canonical capability name.

    Runtime, skills, grants, model, cost, and execution state are deliberately
    excluded: none can change identity or be inferred as authority from it.
    """
    digest = hashlib.sha256(capability_name.encode("utf-8")).digest()
    accessory = (
        ()
        if digest[3] % (len(_ACCESSORIES) + 1) == len(_ACCESSORIES)
        else (_ACCESSORIES[digest[3] % len(_ACCESSORIES)],)
    )
    return FamiliarGenotype(
        seed=int.from_bytes(digest[:4], "big"),
        body=_BODIES[digest[0] % len(_BODIES)],
        palette=_PALETTES[digest[1] % len(_PALETTES)],
        markings=(_MARKINGS[digest[2] % len(_MARKINGS)],),
        accessories=accessory,
    )


__all__ = [
    "FAMILIAR_GENOTYPE_SOURCE",
    "FamiliarGenotype",
    "derive_familiar_genotype",
]
