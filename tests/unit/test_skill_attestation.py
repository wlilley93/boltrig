from __future__ import annotations

from dataclasses import replace

import pytest

from boltrig.fleet.domain.skill_attestation import (
    ExpectedSkill,
    ObservedSkill,
    SkillAttestationError,
    SkillAttestationPlan,
    SkillAttestationState,
    SkillDiscoveryReport,
    SkillScope,
    absolute_posix_path,
    attest_skill_discovery,
    sha256_digest,
)

_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64
_DIGEST_C = "sha256:" + "c" * 64


def _expected(name: str = "legal-review", suffix: str = "a") -> ExpectedSkill:
    digest = "sha256:" + suffix * 64
    return ExpectedSkill(
        name=name,
        manifest_path=f"/cells/phase/codex/skills/{name}/SKILL.md",
        scope=SkillScope.USER,
        directory_digest=digest,
        manifest_digest=_DIGEST_B,
    )


def _observed(expected: ExpectedSkill, *, enabled: bool = True) -> ObservedSkill:
    return ObservedSkill(
        name=expected.name,
        manifest_path=expected.manifest_path,
        scope=expected.scope,
        enabled=enabled,
        directory_digest=expected.directory_digest if enabled else None,
        manifest_digest=expected.manifest_digest if enabled else None,
    )


def _report(*skills: ObservedSkill, cwd: str = "/cells/phase/workspace") -> SkillDiscoveryReport:
    return SkillDiscoveryReport(cwd=cwd, skills=skills)


@pytest.mark.parametrize(
    "value",
    ["relative/path", "/path/../escape", "/double//slash", "/trailing/", ""],
)
def test_paths_must_be_absolute_normalized_posix(value: str) -> None:
    with pytest.raises(ValueError):
        absolute_posix_path(value)


@pytest.mark.parametrize("value", ["sha256:" + "a" * 63 + " ", "sha256:" + "A" * 64])
def test_digest_rejects_whitespace_and_non_lowercase_hex(value: str) -> None:
    with pytest.raises(ValueError):
        sha256_digest(value)


def test_plan_rejects_duplicate_names_and_paths() -> None:
    first = _expected()
    with pytest.raises(ValueError, match="unique"):
        SkillAttestationPlan("/cells/phase/workspace", (first, first))
    same_path = replace(_expected("finance-review", "c"), manifest_path=first.manifest_path)
    with pytest.raises(ValueError, match="unique"):
        SkillAttestationPlan("/cells/phase/workspace", (first, same_path))


@pytest.mark.invariant("SEC-156")
def test_exact_enabled_allowlist_attests_with_disabled_system_skill_visible() -> None:
    expected = _expected()
    disabled_system = ObservedSkill(
        name="skill-creator",
        manifest_path="/opt/codex/system/skill-creator/SKILL.md",
        scope=SkillScope.SYSTEM,
        enabled=False,
    )
    plan = SkillAttestationPlan("/cells/phase/workspace", (expected,))

    receipt = attest_skill_discovery(plan, _report(_observed(expected), disabled_system))

    assert receipt.digest.startswith("sha256:")
    assert receipt.selected_names == ("legal-review",)
    assert receipt.observed_count == 2


@pytest.mark.parametrize(
    "report",
    [
        _report(),
        _report(
            ObservedSkill(
                name="unexpected",
                manifest_path="/opt/unexpected/SKILL.md",
                scope=SkillScope.SYSTEM,
                enabled=True,
                directory_digest=_DIGEST_A,
                manifest_digest=_DIGEST_B,
            )
        ),
        SkillDiscoveryReport("/cells/phase/workspace", (), error_count=1),
        _report(cwd="/cells/other/workspace"),
    ],
)
def test_missing_unexpected_error_or_wrong_cwd_fails_closed(report: SkillDiscoveryReport) -> None:
    with pytest.raises(SkillAttestationError):
        attest_skill_discovery(
            SkillAttestationPlan("/cells/phase/workspace", (_expected(),)),
            report,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        {"scope": SkillScope.REPO},
        {"manifest_path": "/cells/phase/codex/skills/other/SKILL.md"},
        {"directory_digest": _DIGEST_C},
        {"manifest_digest": _DIGEST_C},
    ],
)
def test_scope_path_or_digest_drift_fails(mutation: dict[str, object]) -> None:
    expected = _expected()
    observed = replace(_observed(expected), **mutation)
    plan = SkillAttestationPlan("/cells/phase/workspace", (expected,))

    with pytest.raises(SkillAttestationError):
        attest_skill_discovery(plan, _report(observed))


def test_duplicate_discovery_name_or_path_fails_even_when_disabled() -> None:
    expected = _expected()
    duplicate = replace(_observed(expected), enabled=False, directory_digest=None, manifest_digest=None)
    plan = SkillAttestationPlan("/cells/phase/workspace", (expected,))

    with pytest.raises(SkillAttestationError):
        attest_skill_discovery(plan, _report(_observed(expected), duplicate))


def test_receipt_digest_is_selection_order_independent() -> None:
    legal = _expected()
    finance = _expected("finance-review", "c")
    first = SkillAttestationPlan("/cells/phase/workspace", (legal, finance))
    second = SkillAttestationPlan("/cells/phase/workspace", (finance, legal))
    report = _report(_observed(finance), _observed(legal))

    assert attest_skill_discovery(first, report).digest == attest_skill_discovery(second, report).digest


@pytest.mark.invariant("SEC-156")
def test_skills_changed_invalidates_until_a_new_attestation_is_accepted() -> None:
    expected = _expected()
    plan = SkillAttestationPlan("/cells/phase/workspace", (expected,))
    receipt = attest_skill_discovery(plan, _report(_observed(expected)))
    state = SkillAttestationState().accept(receipt, plan)
    assert state.current() == receipt

    changed = state.invalidate()
    with pytest.raises(SkillAttestationError, match="not currently attested"):
        changed.current()

    with pytest.raises(SkillAttestationError, match="stale"):
        changed.accept(receipt, plan)

    refreshed_plan = SkillAttestationPlan(
        plan.workspace_path,
        plan.selected,
        generation=changed.generation,
    )
    refreshed = attest_skill_discovery(refreshed_plan, _report(_observed(expected)))
    assert changed.accept(refreshed, refreshed_plan).current() == refreshed


def test_state_rejects_a_stale_attestation_generation() -> None:
    expected = _expected()
    receipt = attest_skill_discovery(
        SkillAttestationPlan("/cells/phase/workspace", (expected,)),
        _report(_observed(expected)),
    )

    with pytest.raises(ValueError, match="stale"):
        SkillAttestationState(generation=2, attested_generation=1, attestation=receipt)
