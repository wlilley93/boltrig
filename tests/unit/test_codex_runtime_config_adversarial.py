from __future__ import annotations

import copy
import hashlib
import pickle
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

import boltrig.fleet.infrastructure.codex_runtime_config as config_module
import boltrig.fleet.infrastructure.codex_runtime_config_toml as config_toml_module
from boltrig.fleet.infrastructure.codex_runtime_config import (
    CodexReasoningEffort,
    CodexRuntimeConfigError,
    CodexRuntimeConfigRequest,
    ComposedCodexRuntimeConfig,
    compose_codex_runtime_config,
)
from boltrig.fleet.infrastructure.codex_runtime_config_toml import (
    canonical_skill_entries_digest,
)
from boltrig.fleet.infrastructure.skill_config import REVIEWED_SYSTEM_SKILLS_0_144_3

_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64
_DIGEST_C = "sha256:" + "c" * 64
_CELL = Path("/srv/boltrig/cells/cell-001")
_CODEX_HOME = _CELL / "codex"


def _skill_fragment() -> bytes:
    entries = [
        (_CODEX_HOME / "skills" / ".system" / name / "SKILL.md", False)
        for name in REVIEWED_SYSTEM_SKILLS_0_144_3
    ]
    entries.append((_CODEX_HOME / "skills" / "legal-review" / "SKILL.md", True))
    lines: list[str] = []
    for path, enabled in entries:
        lines.extend(
            (
                "[[skills.config]]",
                f'path = "{path.as_posix()}"',
                f"enabled = {'true' if enabled else 'false'}",
                "",
            )
        )
    return "\n".join(lines).encode("ascii")


def _request() -> CodexRuntimeConfigRequest:
    return CodexRuntimeConfigRequest(
        cell_id="cell-001",
        cell_root=_CELL,
        codex_home=_CODEX_HOME,
        helper_path=_CELL / "bin" / "codex-model-auth",
        helper_sha256=_DIGEST_A,
        model_id="gpt-5.4",
        model_policy_digest=_DIGEST_B,
        reasoning_effort=CodexReasoningEffort.HIGH,
        proxy_port=43190,
        skill_config_fragment=_skill_fragment(),
        skill_inventory_digest=_DIGEST_C,
    )


def _config_receipt(
    composed: ComposedCodexRuntimeConfig,
    config_toml: str,
    *,
    skill_entries_digest: str | None = None,
):
    encoded = config_toml.encode("ascii")
    changes: dict[str, object] = {
        "config_digest": "sha256:" + hashlib.sha256(encoded).hexdigest(),
        "config_bytes": len(encoded),
    }
    if skill_entries_digest is not None:
        changes["skill_entries_digest"] = skill_entries_digest
    return replace(composed.receipt, **changes)


def _skill_digest(config_toml: str) -> str:
    document = tomllib.loads(config_toml)
    entries = tuple(
        (item["path"], item["enabled"])
        for item in document["skills"]["config"]
    )
    return canonical_skill_entries_digest(entries)


@pytest.mark.invariant("SEC-159")
def test_compose_revalidates_a_request_mutated_after_construction() -> None:
    request = _request()
    object.__setattr__(request, "helper_path", Path("/tmp/attacker-helper"))

    with pytest.raises(CodexRuntimeConfigError, match="exact cell"):
        compose_codex_runtime_config(request)


@pytest.mark.invariant("SEC-159")
def test_compose_uses_a_private_snapshot_after_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    original_validate = config_module._validate_request

    def mutate_caller_after_validation(value: CodexRuntimeConfigRequest) -> None:
        original_validate(value)
        object.__setattr__(request, "helper_path", Path("/tmp/attacker-helper"))

    monkeypatch.setattr(
        config_module, "_validate_request", mutate_caller_after_validation
    )

    composed = compose_codex_runtime_config(request)

    assert composed.receipt.helper_path == (
        _CELL / "bin" / "codex-model-auth"
    ).as_posix()
    assert "/tmp/attacker-helper" not in composed.config_toml


def test_request_is_slot_isolated_redacted_and_not_pickle_serializable() -> None:
    request = _request()

    assert not hasattr(request, "__dict__")
    assert repr(request) == "CodexRuntimeConfigRequest(redacted=True)"
    for operation in (pickle.dumps, copy.copy, copy.deepcopy):
        with pytest.raises(TypeError, match="must not be pickled or copied"):
            operation(request)


@pytest.mark.invariant("SEC-159")
def test_self_consistent_receipt_cannot_move_helper_outside_cell() -> None:
    composed = compose_codex_runtime_config(_request())
    external = "/tmp/attacker-helper"
    widened = composed.config_toml.replace(composed.receipt.helper_path, external)
    receipt = _config_receipt(composed, widened)
    object.__setattr__(receipt, "helper_path", external)

    with pytest.raises(CodexRuntimeConfigError, match="exact cell"):
        ComposedCodexRuntimeConfig(widened, receipt)


@pytest.mark.invariant("SEC-159")
@pytest.mark.parametrize("mutation", ["system", "outside_root"])
def test_self_consistent_receipt_cannot_widen_skill_policy(mutation: str) -> None:
    composed = compose_codex_runtime_config(_request())
    if mutation == "system":
        system_path = (_CODEX_HOME / "skills" / ".system" / "imagegen" / "SKILL.md").as_posix()
        system_entry = f'path = "{system_path}"\nenabled = false'
        widened = composed.config_toml.replace(
            system_entry, f'path = "{system_path}"\nenabled = true', 1
        )
    else:
        selected = (_CODEX_HOME / "skills" / "legal-review" / "SKILL.md").as_posix()
        widened = composed.config_toml.replace(selected, "/tmp/attacker/SKILL.md", 1)
    receipt = _config_receipt(
        composed,
        widened,
        skill_entries_digest=_skill_digest(widened),
    )

    with pytest.raises(CodexRuntimeConfigError, match="skill policy"):
        ComposedCodexRuntimeConfig(widened, receipt)


def test_app_server_arguments_require_exact_strings_without_repr_leakage() -> None:
    sentinel = "LEAKED-UPSTREAM-SECRET"

    class ForgedArgument:
        def __eq__(self, _other: object) -> bool:
            return True

        def __repr__(self) -> str:
            return sentinel

    composed = compose_codex_runtime_config(_request())
    forged = tuple(ForgedArgument() for _ in composed.receipt.app_server_arguments)
    with pytest.raises(CodexRuntimeConfigError, match="contract") as captured:
        replace(composed.receipt, app_server_arguments=forged)  # type: ignore[arg-type]
    assert sentinel not in str(captured.value)

    object.__setattr__(composed.receipt, "app_server_arguments", forged)
    assert sentinel not in repr(composed.receipt)
    assert sentinel not in repr(composed)
    with pytest.raises(CodexRuntimeConfigError, match="contract"):
        ComposedCodexRuntimeConfig(composed.config_toml, composed.receipt)


def test_raw_fragment_digest_is_absent_and_renderer_has_one_internal_user() -> None:
    receipt = compose_codex_runtime_config(_request()).receipt
    assert not hasattr(receipt, "skill_fragment_digest")
    assert not hasattr(config_toml_module, "render_codex_runtime_config")
    assert "render_codex_runtime_config" not in config_toml_module.__all__

    root = Path(__file__).parents[2]
    renderer = "_render_codex_runtime_config"
    users = {
        path.relative_to(root).as_posix()
        for path in (root / "boltrig").rglob("*.py")
        if path.name != "codex_runtime_config_toml.py" and renderer in path.read_text()
    }
    assert users == {"boltrig/fleet/infrastructure/codex_runtime_config.py"}
