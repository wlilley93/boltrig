"""Fail-closed effective authority for one governed execution phase."""

from __future__ import annotations

from dataclasses import dataclass

from boltrig.models import GrantSet, VerbId


@dataclass(frozen=True)
class EffectiveAuthority:
    """The five independent ceilings every domain tool call must satisfy.

    Keeping the ceilings separate avoids lossy wildcard materialisation. A verb
    is permitted only when every current ceiling permits it. Callers must resolve
    this value again at execution and resume boundaries; selected skills can
    narrow the result but can never create authority.
    """

    parent_grant: GrantSet
    profile_ceiling: GrantSet
    selected_skill_requirements: GrantSet
    workspace_policy: GrantSet
    approval_state: GrantSet

    def permits(self, verb_id: VerbId) -> bool:
        """Return true only when all five authority inputs currently permit the verb."""
        return all(ceiling.permits(verb_id) for ceiling in self.ceilings())

    def ceilings(self) -> tuple[GrantSet, GrantSet, GrantSet, GrantSet, GrantSet]:
        """Expose the named formula as an ordered, immutable evaluation tuple."""
        return (
            self.parent_grant,
            self.profile_ceiling,
            self.selected_skill_requirements,
            self.workspace_policy,
            self.approval_state,
        )

    def denied_by(self, verb_id: VerbId) -> tuple[str, ...]:
        """Return bounded policy labels for audit without exposing policy contents."""
        labels = (
            "parent_grant",
            "profile_ceiling",
            "selected_skill_requirements",
            "workspace_policy",
            "approval_state",
        )
        return tuple(
            label
            for label, ceiling in zip(labels, self.ceilings(), strict=True)
            if not ceiling.permits(verb_id)
        )
