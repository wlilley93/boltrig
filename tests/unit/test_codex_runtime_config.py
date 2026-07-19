from __future__ import annotations

import hashlib
import tomllib
from dataclasses import fields, replace
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure.codex_runtime_config import (
    CODEX_RUNTIME_APP_SERVER_ARGUMENTS,
    CODEX_RUNTIME_CLI_VERSION,
    CODEX_RUNTIME_CONFIG_PRODUCTION_READY,
    CODEX_RUNTIME_INITIALIZE_EXPERIMENTAL_API,
    CODEX_RUNTIME_PROVIDER_CONTRACT_DIGEST,
    CodexReasoningEffort,
    CodexRuntimeConfigError,
    CodexRuntimeConfigRequest,
    CodexRuntimeSurface,
    CodexRuntimeSurfaceAttestation,
    ComposedCodexRuntimeConfig,
    compose_codex_runtime_config,
)
from boltrig.fleet.infrastructure.skill_config import REVIEWED_SYSTEM_SKILLS_0_144_3

_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64
_DIGEST_C = "sha256:" + "c" * 64


def _skill_fragment(codex_home: Path, selected: tuple[str, ...] = ()) -> bytes:
    entries = [
        (codex_home / "skills" / ".system" / name / "SKILL.md", False)
        for name in REVIEWED_SYSTEM_SKILLS_0_144_3
    ]
    entries.extend((codex_home / "skills" / name / "SKILL.md", True) for name in selected)
    lines = ["# validated skill fragment"]
    for path, enabled in entries:
        lines.extend(
            (
                "",
                "[[skills.config]]",
                f'path = "{path.as_posix()}"',
                f"enabled = {'true' if enabled else 'false'}",
            )
        )
    return ("\n".join(lines) + "\n").encode("ascii")


def _request(
    *,
    selected: tuple[str, ...] = ("legal-review",),
    attestations: tuple[CodexRuntimeSurfaceAttestation, ...] = (),
) -> CodexRuntimeConfigRequest:
    cell = Path("/srv/boltrig/cells/cell-001")
    codex_home = cell / "codex"
    return CodexRuntimeConfigRequest(
        cell_id="cell-001",
        cell_root=cell,
        codex_home=codex_home,
        helper_path=Path("/opt/boltrig/codex/model_auth_helper"),
        helper_sha256=_DIGEST_A,
        socket_path=Path("/var/lib/boltrig/codex-cells/mp-0123456789abcdef.sock"),
        model_id="gpt-5.4",
        model_policy_digest=_DIGEST_B,
        reasoning_effort=CodexReasoningEffort.HIGH,
        proxy_port=43190,
        skill_config_fragment=_skill_fragment(codex_home, selected),
        skill_inventory_digest=_DIGEST_C,
        surface_attestations=attestations,
    )


def _document(config: ComposedCodexRuntimeConfig) -> dict[str, object]:
    return tomllib.loads(config.config_toml)


def _replace_config(composed: ComposedCodexRuntimeConfig, old: str, new: str) -> ComposedCodexRuntimeConfig:
    return _rebind_config(composed, composed.config_toml.replace(old, new))


def _rebind_config(composed: ComposedCodexRuntimeConfig, config_toml: str) -> ComposedCodexRuntimeConfig:
    encoded = config_toml.encode("ascii")
    receipt = replace(
        composed.receipt,
        config_digest="sha256:" + hashlib.sha256(encoded).hexdigest(),
        config_bytes=len(encoded),
    )
    return ComposedCodexRuntimeConfig(config_toml, receipt)


@pytest.mark.invariant("SEC-159")
def test_composes_exact_secretless_read_only_config_and_receipt() -> None:
    composed = compose_codex_runtime_config(_request())
    document = _document(composed)

    assert document["model"] == "gpt-5.4"
    assert document["model_provider"] == "boltrig_model_proxy"
    assert document["model_reasoning_effort"] == "high"
    assert document["approval_policy"] == "never"
    assert document["sandbox_mode"] == "read-only"
    assert document["web_search"] == "disabled"
    assert document["project_doc_max_bytes"] == 0
    assert document["project_root_markers"] == []
    assert document["mcp_servers"] == {}
    assert document["history"] == {"persistence": "none"}
    assert document["analytics"] == {"enabled": False}
    assert document["feedback"] == {"enabled": False}
    receipt = composed.receipt
    assert receipt.matches(composed.config_toml)
    assert receipt.config_digest == "sha256:" + hashlib.sha256(
        composed.config_toml.encode("ascii")
    ).hexdigest()
    assert receipt.helper_sha256 == _DIGEST_A
    assert receipt.model_policy_digest == _DIGEST_B
    assert receipt.skill_inventory_digest == _DIGEST_C
    assert receipt.skill_entries_digest.startswith("sha256:")
    assert receipt.reasoning_effort is CodexReasoningEffort.HIGH
    assert receipt.proxy_port == 43190


def test_custom_provider_contract_uses_only_verified_command_auth_fields() -> None:
    document = _document(compose_codex_runtime_config(_request()))
    provider = document["model_providers"]["boltrig_model_proxy"]  # type: ignore[index]

    assert set(provider) == {
        "name",
        "base_url",
        "wire_api",
        "request_max_retries",
        "stream_max_retries",
        "stream_idle_timeout_ms",
        "supports_websockets",
        "auth",
    }
    assert provider["base_url"] == "http://127.0.0.1:43190/v1"
    assert provider["wire_api"] == "responses"
    assert provider["supports_websockets"] is False
    assert provider["request_max_retries"] == 0
    assert provider["stream_max_retries"] == 0
    assert provider["auth"] == {
        "command": "/opt/boltrig/codex/model_auth_helper",
        "args": [
            "--cell-id",
            "cell-001",
            "--socket",
            "/var/lib/boltrig/codex-cells/mp-0123456789abcdef.sock",
        ],
        "timeout_ms": 1000,
        "refresh_interval_ms": 30000,
    }
    assert CODEX_RUNTIME_PROVIDER_CONTRACT_DIGEST == (
        "sha256:5d7154040272973b0c227152bf820ac29db6a63b4c06955dbc8a8fa7dd594ae0"
    )


def test_config_and_receipt_contain_no_upstream_or_provider_secret_channel() -> None:
    composed = compose_codex_runtime_config(_request())
    forbidden = (
        "CODEX_ACCESS_TOKEN",
        "CODEX_API_KEY",
        "OPENAI_API_KEY",
        "env_key",
        "env_http_headers",
        "experimental_bearer_token",
        "requires_openai_auth",
    )

    assert all(item not in composed.config_toml for item in forbidden)
    assert all(item not in repr(composed) for item in forbidden)
    assert composed.receipt.helper_path.endswith("/model_auth_helper")


def test_stable_stdio_strict_config_contract_is_explicit_and_not_ready() -> None:
    receipt = compose_codex_runtime_config(_request()).receipt

    assert CODEX_RUNTIME_CLI_VERSION == "0.144.3"
    assert receipt.codex_cli_version == "0.144.3"
    assert CODEX_RUNTIME_APP_SERVER_ARGUMENTS == (
        "app-server",
        "--listen",
        "stdio://",
        "--strict-config",
    )
    assert receipt.app_server_arguments == CODEX_RUNTIME_APP_SERVER_ARGUMENTS
    assert receipt.initialize_experimental_api is False
    assert CODEX_RUNTIME_INITIALIZE_EXPERIMENTAL_API is False
    assert receipt.production_ready is False
    assert CODEX_RUNTIME_CONFIG_PRODUCTION_READY is False


def test_dynamic_surfaces_are_disabled_without_exact_attestations() -> None:
    document = _document(compose_codex_runtime_config(_request()))
    features = document["features"]

    assert features["multi_agent"] is False  # type: ignore[index]
    assert features["apps"] is False  # type: ignore[index]
    assert features["hooks"] is False  # type: ignore[index]
    assert features["plugins"] is False  # type: ignore[index]
    assert features["remote_plugin"] is False  # type: ignore[index]
    assert features["plugin_sharing"] is False  # type: ignore[index]
    assert document["apps"] == {"_default": {"enabled": False}}
    assert document["agents"] == {"max_threads": 1, "max_depth": 1}


@pytest.mark.invariant("SEC-159")
def test_caller_constructible_surface_digests_never_grant_dynamic_surfaces() -> None:
    for surface in CodexRuntimeSurface:
        attestation = CodexRuntimeSurfaceAttestation(surface, _DIGEST_A)
        with pytest.raises(CodexRuntimeConfigError, match="governed verifier"):
            _request(attestations=(attestation,))


def test_ambient_and_unknown_override_fields_fail_closed_without_echoing_values() -> None:
    with pytest.raises(CodexRuntimeConfigError, match="ambient") as captured:
        compose_codex_runtime_config(
            _request(), ambient_overrides={"experimental_bearer_token": "secret-value"}
        )

    assert "secret-value" not in str(captured.value)
    request = _request()
    values = {field.name: getattr(request, field.name) for field in fields(request)}
    assert not hasattr(request, "__dict__")
    with pytest.raises(TypeError, match="unexpected"):
        CodexRuntimeConfigRequest(**values, unexpected=True)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            {"helper_path": Path("/srv/boltrig/cells/cell-001/bin/helper")},
            "outside the mutable cell root",
        ),
        ({"codex_home": Path("/srv/boltrig/codex")}, "exact child"),
        ({"proxy_port": 0}, "between 1 and 65535"),
        ({"model_id": "gpt 5"}, "model id"),
        ({"helper_sha256": "sha256:nope"}, "helper digest"),
    ],
)
def test_cell_provider_inputs_are_exact_and_local(change: dict[str, object], message: str) -> None:
    with pytest.raises((CodexRuntimeConfigError, TypeError), match=message):
        replace(_request(), **change)


def test_skill_fragment_cannot_add_top_level_config_or_enable_system_skills() -> None:
    request = _request()
    injected = request.skill_config_fragment + b'\nmodel_provider = "attacker"\n'
    with pytest.raises(CodexRuntimeConfigError, match="malformed|unknown"):
        compose_codex_runtime_config(replace(request, skill_config_fragment=injected))

    enabled_system = request.skill_config_fragment.replace(
        b"enabled = false", b"enabled = true", 1
    )
    with pytest.raises(CodexRuntimeConfigError, match="system skills"):
        compose_codex_runtime_config(replace(request, skill_config_fragment=enabled_system))


def test_selected_skills_are_exact_sorted_children_of_isolated_root() -> None:
    composed = compose_codex_runtime_config(_request(selected=("legal-review", "writing")))
    entries = _document(composed)["skills"]["config"]  # type: ignore[index]

    assert [Path(item["path"]).parent.name for item in entries[-2:]] == [  # type: ignore[index]
        "legal-review",
        "writing",
    ]
    request = _request(selected=("writing", "legal-review"))
    with pytest.raises(CodexRuntimeConfigError, match="sorted"):
        compose_codex_runtime_config(request)


def test_receipt_detects_config_tampering() -> None:
    composed = compose_codex_runtime_config(_request())

    assert not composed.receipt.matches(composed.config_toml + "# drift\n")
    with pytest.raises(CodexRuntimeConfigError, match="receipt"):
        ComposedCodexRuntimeConfig(composed.config_toml + "# drift\n", composed.receipt)
    with pytest.raises(CodexRuntimeConfigError, match="contract"):
        replace(composed.receipt, production_ready=True)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('model = "gpt-5.4"', 'model = "gpt-5.3"'),
        ('model_reasoning_effort = "high"', 'model_reasoning_effort = "low"'),
        ('approval_policy = "never"', 'approval_policy = "on-request"'),
        ('sandbox_mode = "read-only"', 'sandbox_mode = "workspace-write"'),
        ('multi_agent = false', 'multi_agent = true'),
        (
            'command = "/opt/boltrig/codex/model_auth_helper"',
            'command = "/tmp/attacker-helper"',
        ),
        ('"--cell-id", "cell-001"', '"--cell-id", "cell-999"'),
        (
            '"--socket", "/var/lib/boltrig/codex-cells/mp-0123456789abcdef.sock"',
            '"--socket", "/tmp/attacker.sock"',
        ),
        ('base_url = "http://127.0.0.1:43190/v1"', 'base_url = "http://127.0.0.1:9/v1"'),
    ],
)
def test_digest_recalculation_cannot_hide_config_receipt_semantic_drift(old: str, new: str) -> None:
    with pytest.raises(CodexRuntimeConfigError, match="metadata"):
        _replace_config(compose_codex_runtime_config(_request()), old, new)


def test_recomputed_digest_cannot_append_known_widening_root_config() -> None:
    composed = compose_codex_runtime_config(_request())
    widened = composed.config_toml.replace(
        'model = "gpt-5.4"',
        'developer_instructions = "attacker"\nmodel = "gpt-5.4"',
        1,
    )
    with pytest.raises(CodexRuntimeConfigError, match="metadata|skill policy"):
        _rebind_config(composed, widened)


def test_recomputed_digest_cannot_enable_a_reviewed_system_skill() -> None:
    composed = compose_codex_runtime_config(_request())
    widened = composed.config_toml.replace("enabled = false", "enabled = true", 1)
    with pytest.raises(CodexRuntimeConfigError, match="metadata|skill policy"):
        _rebind_config(composed, widened)


def test_recomputed_digest_cannot_add_an_unreceipted_selected_skill() -> None:
    composed = compose_codex_runtime_config(_request())
    marker = "\n[model_providers.boltrig_model_proxy]"
    extra = (
        "\n[[skills.config]]\n"
        'path = "/srv/boltrig/cells/cell-001/codex/skills/attacker/SKILL.md"\n'
        "enabled = true\n"
    )
    widened = composed.config_toml.replace(marker, extra + marker, 1)
    with pytest.raises(CodexRuntimeConfigError, match="metadata|skill policy"):
        _rebind_config(composed, widened)


@pytest.mark.parametrize("container", ["skills", "model_providers"])
def test_malformed_parsed_config_container_fails_closed(container: str) -> None:
    composed = compose_codex_runtime_config(_request())
    if container == "skills":
        start = composed.config_toml.index("\n[[skills.config]]")
        end = composed.config_toml.index("\n[model_providers.boltrig_model_proxy]")
    else:
        start = composed.config_toml.index("\n[model_providers.boltrig_model_proxy]")
        end = len(composed.config_toml)
    without_entries = composed.config_toml[:start] + composed.config_toml[end:]
    malformed = without_entries.replace(
        "\n[agents]", f'\n{container} = "oops"\n\n[agents]', 1
    )
    with pytest.raises(CodexRuntimeConfigError, match="metadata"):
        _rebind_config(composed, malformed)


@pytest.mark.parametrize(
    "change",
    [
        {"cell_id": "cell-999"},
        {"model_id": "gpt-5.3"},
        {"reasoning_effort": CodexReasoningEffort.LOW},
        {"helper_path": "/opt/boltrig/codex/other_helper"},
        {"proxy_port": 43191},
    ],
)
def test_receipt_metadata_must_match_its_exact_parsed_config(change: dict[str, object]) -> None:
    composed = compose_codex_runtime_config(_request())
    receipt = replace(composed.receipt, **change)
    with pytest.raises(CodexRuntimeConfigError, match="metadata"):
        ComposedCodexRuntimeConfig(composed.config_toml, receipt)


def test_external_evidence_digests_remain_untrusted_composition_metadata() -> None:
    """A config receipt is deliberately not a signature over external evidence."""

    composed = compose_codex_runtime_config(_request())
    changed = replace(
        composed.receipt,
        helper_sha256=_DIGEST_B,
        model_policy_digest=_DIGEST_C,
        skill_inventory_digest=_DIGEST_A,
    )

    assert ComposedCodexRuntimeConfig(composed.config_toml, changed).receipt == changed
    assert changed.production_ready is False


@pytest.mark.parametrize("field", ["cell_root", "codex_home", "helper_path"])
def test_stateful_path_subclasses_are_rejected_before_any_method_is_read(field: str) -> None:
    class StatefulPath(type(Path("/"))):
        reads = 0

        def as_posix(self) -> str:
            type(self).reads += 1
            if type(self).reads == 1:
                return super().as_posix()
            return "/tmp/attacker-path"

    request = _request()
    stateful = StatefulPath(str(getattr(request, field)))
    with pytest.raises(CodexRuntimeConfigError, match="exact pathlib POSIX path"):
        replace(request, **{field: stateful})
    assert StatefulPath.reads == 0


def test_duplicate_or_untyped_surface_attestations_fail_closed() -> None:
    duplicate = (
        CodexRuntimeSurfaceAttestation(CodexRuntimeSurface.APPS, _DIGEST_A),
        CodexRuntimeSurfaceAttestation(CodexRuntimeSurface.APPS, _DIGEST_B),
    )
    with pytest.raises(CodexRuntimeConfigError, match="unique"):
        replace(_request(), surface_attestations=duplicate)
    with pytest.raises(TypeError, match="exact CodexRuntimeSurface"):
        CodexRuntimeSurfaceAttestation("apps", _DIGEST_A)  # type: ignore[arg-type]
