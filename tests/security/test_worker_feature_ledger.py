"""Completeness ratchet for Worker-relevant non-HTTP feature sources."""

from __future__ import annotations

import ast
import re
from dataclasses import fields
from pathlib import Path

import pytest

from boltrig.config.manifest import (
    AdapterConfig,
    BudgetConfig,
    ChatConfig,
    CredentialRef,
    EphemeralRuntime,
    FleetManifest,
    HierarchyConfig,
    HierarchyTier,
    HitlConfig,
    IdentityConfig,
    ModelsConfig,
    NamedAgentConfig,
    NamedAgentsConfig,
    NetworkConfig,
    PrivacyConfig,
)
from boltrig.config.spawn_rules import SpawnRule
from boltrig.models import ModelEndpoint, RoleMapping
from tests.worker_feature_ledger import (
    ALL_NON_HTTP_FEATURES,
    BACKGROUND_FEATURES,
    CLI_COMMAND_FEATURES,
    GOVERNED_WORKER_CONTROL_FEATURES,
    LIFECYCLE_DIMENSIONS,
    LIFECYCLE_OWNERS,
    MANIFEST_EXTRA_FEATURES,
    MANIFEST_FEATURES,
    NESTED_MANIFEST_FIELDS,
    NATIVE_COMMANDS,
    NATIVE_PLUGIN_FEATURES,
)

ROOT = Path(__file__).resolve().parents[2]
NESTED_MANIFEST_TYPES = (
    CredentialRef,
    IdentityConfig,
    ModelsConfig,
    NamedAgentConfig,
    NamedAgentsConfig,
    BudgetConfig,
    HierarchyTier,
    HierarchyConfig,
    EphemeralRuntime,
    AdapterConfig,
    HitlConfig,
    NetworkConfig,
    PrivacyConfig,
    ChatConfig,
    RoleMapping,
    ModelEndpoint,
    SpawnRule,
)


def _manifest_extra_sections() -> set[str]:
    tree = ast.parse((ROOT / "boltrig/config/manifest.py").read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.keyword) or node.arg != "extra":
            continue
        if not isinstance(node.value, ast.DictComp):
            continue
        generators = node.value.generators
        if len(generators) != 1 or not isinstance(generators[0].iter, ast.Tuple):
            continue
        values = {
            item.value
            for item in generators[0].iter.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
        if values:
            return values
    raise AssertionError("FleetManifest extra-section allowlist was not found")


def _tauri_commands() -> set[str]:
    source = (ROOT / "apps/worker/src-tauri/src/lib.rs").read_text()
    return set(
        re.findall(
            r"#\[tauri::command\]\s*(?:async\s+)?fn\s+([a-zA-Z0-9_]+)",
            source,
        )
    )


def _tauri_handlers() -> set[str]:
    source = (ROOT / "apps/worker/src-tauri/src/lib.rs").read_text()
    match = re.search(
        r"invoke_handler\(tauri::generate_handler!\[(.*?)\]\)",
        source,
        flags=re.DOTALL,
    )
    assert match is not None
    return set(re.findall(r"\b([a-z][a-z0-9_]*)\b", match.group(1)))


def _tauri_plugins() -> set[str]:
    source = (ROOT / "apps/worker/src-tauri/src/lib.rs").read_text()
    return set(
        re.findall(r"\.plugin\(\s*tauri_plugin_([a-z_]+)::", source)
    )


def _cli_commands() -> set[str]:
    tree = ast.parse((ROOT / "boltrig/api/cli.py").read_text())
    commands: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and function.attr == "add_parser"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            commands.add(node.args[0].value)
    return commands


def _worker_named_tasks() -> set[str]:
    tree = ast.parse((ROOT / "boltrig/api/worker.py").read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if (
                keyword.arg == "name"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                names.add(keyword.value.value)
    return names


def _governed_worker_control_sources() -> set[str]:
    root = ROOT / "apps/worker/src/components"
    sources: set[str] = set()
    for path in root.rglob("*.tsx"):
        source = path.read_text()
        if (
            "pending_human" in source
            or "hitl_request_id" in source
            or "useExactApprovalFinalizer" in source
            or (
                path.name == "ChatView.tsx"
                and "respondHitl" in source
            )
        ):
            sources.add(path.relative_to(root).as_posix())
    return sources


@pytest.mark.security
@pytest.mark.invariant("WRK-06")
def test_every_manifest_feature_source_has_a_worker_lifecycle_classification():
    assert set(FleetManifest.__dataclass_fields__) == set(MANIFEST_FEATURES)
    assert _manifest_extra_sections() == set(MANIFEST_EXTRA_FEATURES)
    nested_fields = {
        f"{record.__name__}.{item.name}"
        for record in NESTED_MANIFEST_TYPES
        for item in fields(record)
    }
    assert nested_fields == set(NESTED_MANIFEST_FIELDS)


@pytest.mark.security
@pytest.mark.invariant("WRK-06")
def test_every_native_command_is_classified_and_registered():
    assert _tauri_commands() == _tauri_handlers() == set(NATIVE_COMMANDS)
    assert _tauri_plugins() == set(NATIVE_PLUGIN_FEATURES)
    assert _cli_commands() == set(CLI_COMMAND_FEATURES)
    assert _governed_worker_control_sources() == set(
        GOVERNED_WORKER_CONTROL_FEATURES
    )


@pytest.mark.security
@pytest.mark.invariant("WRK-06")
def test_every_named_fleet_background_task_is_classified():
    assert _worker_named_tasks() <= set(BACKGROUND_FEATURES)
    worker = (ROOT / "boltrig/api/worker.py").read_text()
    assert "pump.run_forever" in worker
    assert "delegation-pump" in BACKGROUND_FEATURES


@pytest.mark.security
@pytest.mark.invariant("WRK-06")
def test_non_http_feature_rows_are_closed_and_missing_states_explain_the_gap():
    assert len(ALL_NON_HTTP_FEATURES) >= 50
    for feature_id, coverage in ALL_NON_HTTP_FEATURES.items():
        assert coverage.source
        assert coverage.note
        states = [getattr(coverage, field) for field in LIFECYCLE_DIMENSIONS]
        assert set(states) <= LIFECYCLE_OWNERS, feature_id
        if "missing" in states:
            assert len(coverage.note) >= 40, feature_id
