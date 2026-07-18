from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from boltrig.fleet.domain.skill_attestation import (
    SkillAttestationError,
    SkillAttestationPlan,
)
from boltrig.fleet.infrastructure.skill_artifacts import (
    SelectedSkillSource,
    digest_directory,
    materialize_selected_skills,
)
from boltrig.fleet.infrastructure.skill_discovery import (
    attest_skills_list,
    force_reload_params,
    parse_skills_list,
)


def _layout(tmp_path: Path) -> tuple[SkillAttestationPlan, Path]:
    catalogue = tmp_path / "catalogue"
    source = catalogue / "legal-review"
    source.mkdir(parents=True)
    manifest = b"---\nname: legal-review\ndescription: Review evidence\n---\nBody\n"
    (source / "SKILL.md").write_bytes(manifest)
    digest = digest_directory(source)
    selected = SelectedSkillSource(
        name="legal-review",
        source_path=str(source),
        expected_directory_digest=digest.digest,
        expected_manifest_digest=f"sha256:{hashlib.sha256(manifest).hexdigest()}",
    )
    cell = tmp_path / "cell"
    codex_home = cell / "codex"
    workspace = cell / "workspace"
    codex_home.mkdir(parents=True)
    workspace.mkdir()
    materialized = materialize_selected_skills(
        (selected,),
        catalogue_root=catalogue,
        cell_root=cell,
        codex_home=codex_home,
    )
    return SkillAttestationPlan(str(workspace), (materialized[0].expected(),)), source


def _metadata(plan: SkillAttestationPlan, *, enabled: bool = True) -> dict[str, object]:
    expected = plan.selected[0]
    return {
        "description": "Review evidence",
        "enabled": enabled,
        "name": expected.name,
        "path": expected.manifest_path,
        "scope": expected.scope.value,
    }


def _payload(
    plan: SkillAttestationPlan,
    *skills: dict[str, object],
    errors: list[object] | None = None,
) -> dict[str, object]:
    return {
        "data": [
            {
                "cwd": plan.workspace_path,
                "errors": errors or [],
                "skills": list(skills),
            }
        ]
    }


def test_force_reload_request_is_exact_and_cwd_scoped(tmp_path: Path) -> None:
    plan, _source = _layout(tmp_path)

    assert force_reload_params(plan) == {
        "cwds": [plan.workspace_path],
        "forceReload": True,
    }


def test_enabled_selection_is_rehashed_and_attested(tmp_path: Path) -> None:
    plan, _source = _layout(tmp_path)
    bundled = {
        "description": "Bundled helper",
        "enabled": False,
        "name": "skill-creator",
        "path": "/opt/codex/system/skill-creator/SKILL.md",
        "scope": "system",
    }

    receipt = attest_skills_list(_payload(plan, _metadata(plan), bundled), plan)

    assert receipt.selected_names == ("legal-review",)
    assert receipt.observed_count == 2


@pytest.mark.invariant("SEC-156")
def test_unselected_bundled_skill_must_be_disabled(tmp_path: Path) -> None:
    plan, _source = _layout(tmp_path)
    bundled = {
        "description": "Bundled helper",
        "enabled": True,
        "name": "skill-creator",
        "path": "/opt/codex/system/skill-creator/SKILL.md",
        "scope": "system",
    }

    with pytest.raises(SkillAttestationError, match="unselected"):
        attest_skills_list(_payload(plan, _metadata(plan), bundled), plan)


def test_unexpected_enabled_path_is_rejected_before_filesystem_access(tmp_path: Path) -> None:
    plan, _source = _layout(tmp_path)
    metadata = _metadata(plan)
    metadata["path"] = "/does/not/exist/SKILL.md"

    with pytest.raises(SkillAttestationError, match="unselected"):
        attest_skills_list(_payload(plan, metadata), plan)


def test_discovery_errors_fail_without_exposing_their_payload(tmp_path: Path) -> None:
    plan, _source = _layout(tmp_path)
    secret = "credential-secret-that-must-not-leak"

    with pytest.raises(SkillAttestationError) as caught:
        attest_skills_list(
            _payload(plan, _metadata(plan), errors=[{"message": secret, "path": secret}]),
            plan,
        )

    assert secret not in str(caught.value)


@pytest.mark.invariant("SEC-156")
def test_digest_drift_after_materialization_fails_closed(tmp_path: Path) -> None:
    plan, _source = _layout(tmp_path)
    manifest = Path(plan.selected[0].manifest_path)
    manifest.parent.chmod(0o700)
    manifest.chmod(0o600)
    manifest.write_text("---\nname: legal-review\n---\nChanged\n", encoding="utf-8")
    manifest.chmod(0o400)
    manifest.parent.chmod(0o500)

    with pytest.raises(SkillAttestationError):
        attest_skills_list(_payload(plan, _metadata(plan)), plan)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": []},
        {"data": [{"cwd": "relative", "errors": [], "skills": []}]},
        {"data": [{"cwd": "/safe", "errors": "bad", "skills": []}]},
        {"data": [{"cwd": "/safe", "errors": [], "skills": "bad"}]},
    ],
)
def test_malformed_response_shapes_fail_closed(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    plan, _source = _layout(tmp_path)

    with pytest.raises(SkillAttestationError, match="malformed"):
        parse_skills_list(payload, plan)


def test_duplicate_discovery_entries_fail_attestation(tmp_path: Path) -> None:
    plan, _source = _layout(tmp_path)
    enabled = _metadata(plan)
    duplicate = _metadata(plan, enabled=False)

    with pytest.raises(SkillAttestationError):
        attest_skills_list(_payload(plan, enabled, duplicate), plan)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("enabled", 1),
        ("scope", "unknown"),
        ("name", "../escape"),
        ("path", "/skill/../escape/SKILL.md"),
    ],
)
def test_metadata_types_and_paths_are_strict(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    plan, _source = _layout(tmp_path)
    metadata = _metadata(plan)
    metadata[field] = value

    with pytest.raises(SkillAttestationError):
        parse_skills_list(_payload(plan, metadata), plan)
