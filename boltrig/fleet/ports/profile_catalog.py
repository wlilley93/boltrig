"""Resolution port for immutable static profiles and skill manifests."""

from __future__ import annotations

from typing import Protocol

from boltrig.fleet.domain.profile_policy import StaticRoleProfile, VersionedSkillManifest
from boltrig.models import ProfileVersionPin, SkillVersionPin


class StaticProfileCatalog(Protocol):
    """Resolve exact pins; the application layer still verifies every returned value."""

    async def resolve_profile(self, pin: ProfileVersionPin) -> StaticRoleProfile: ...

    async def resolve_skills(
        self, pins: tuple[SkillVersionPin, ...]
    ) -> tuple[VersionedSkillManifest, ...]: ...


__all__ = ["StaticProfileCatalog"]
