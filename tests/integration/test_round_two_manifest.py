"""Manifest sidecar/v2 config sections still load (S9, SEC-24)."""

from pathlib import Path

import pytest
import yaml

from boltrig.config import BudgetConfig, export_runtime_environment, load_manifest

_MANIFEST = "manifest.example.yaml"
_ACTIVE_MANIFEST = "manifest.yaml"


# Runtimes decision 0012 retired. A capability on one of these is not a soft
# failure: the runtime gate returns UnavailableRuntime, so EVERY run degrades with
# "runtime_unavailable" while the stack reports healthy on every surface. That is
# how the boltrig.io deployment came to be unable to answer at all.
_RETIRED_RUNTIMES = {"pi", "hermes", "openai", "claude-api", "opencode", "rivet", "rivet_agentos"}


def test_manifest_still_loads_with_round_two_sections():
    # the R1 loader must tolerate the new runtimes/mcp/chat sections
    m = load_manifest(_MANIFEST)
    assert m.tenant_id
    assert m.ephemeral_runtimes


@pytest.mark.parametrize("manifest_path", [_MANIFEST, _ACTIVE_MANIFEST])
def test_no_default_lane_targets_a_retired_runtime(manifest_path):
    """The shipped template is what every new tenant is seeded from.

    `worker-cheap` is the capability every spawn rule routes to, and the tier
    hierarchy is what a chat turn runs on - a retired runtime on any of them makes
    the tenant's agent dead on arrival. rivet/opencode capabilities are retained
    UNWIRED so a non-Codex leaf stays re-wirable ([2026] VJS-PC 20 cond.1), so this
    checks the lanes that are actually DEFAULTED to, not every declared capability.

    ``manifest.yaml`` is the ACTIVE manifest of whatever checkout this runs in and
    is gitignored - a deployment artifact, not a repo file - so that leg is a local
    pre-flight and is skipped where there is none. It ran green locally and failed
    only in CI, which is the same shape as every other defect this week: a check
    that passes because of something present on one machine.

    Skipped loudly rather than quietly dropped, because the TEMPLATE leg is the one
    that guards new tenants and always runs; nobody should read a green CI as
    evidence that some box's live manifest was checked.
    """
    if not Path(manifest_path).exists():
        pytest.skip(f"{manifest_path} absent (gitignored active manifest); template leg still runs")
    m = load_manifest(manifest_path)
    defaulted = [m.hierarchy.tier1, *m.hierarchy.tier2] if m.hierarchy.tier1 else list(m.hierarchy.tier2)
    defaulted += [rt for rt in m.ephemeral_runtimes if rt.name.startswith("worker-")]
    assert defaulted, "a manifest with no default lane would spawn nothing"
    for cap in defaulted:
        assert cap.runtime not in _RETIRED_RUNTIMES, (
            f"{manifest_path}: default lane '{cap.name}' targets retired runtime "
            f"'{cap.runtime}' - every run would degrade with runtime_unavailable"
        )


def test_manifest_interpolated_false_is_false():
    m = load_manifest(_MANIFEST, env={"AIR_GAPPED": "false"})
    assert m.network.air_gapped is False


def test_manifest_budget_window_vocabulary_is_closed():
    with pytest.raises(ValueError, match="budget window must be"):
        BudgetConfig(window="weekly")


@pytest.mark.security
@pytest.mark.invariant("SEC-24")
def test_pi_is_retired_and_stays_restrictive_if_ever_re_wired():
    """pi is retired from the roster (decision 0012), but the routing seam stays
    live with it re-wirable (VJS-PC 20 cond.1) - so SEC-24 still binds the day
    anyone flips it back on."""
    with open(_MANIFEST, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    pi = doc["runtimes"]["pi"]
    assert pi.get("enabled") is False, "pi is retired; a roster entry must not be enabled"
    sandbox = pi.get("sandbox")
    if sandbox is not None:
        assert sandbox["native_tools"] is False  # no Pi filesystem/bash/network tools
        assert set(sandbox["network_allow"]) <= {"kernel_mcp", "model_endpoint"}


def test_manifest_preserves_boltrig_v2_stack_sections():
    m = load_manifest(_MANIFEST)
    assert m.section("stack") == {
        "cockpit": "boltrig_ui",
        "orchestration": "boltrig",
        "durability": "hatchet",
        "runtime_sandbox": "codex_supervisor",
        "coding_agent": "codex",
        "browser_automation": "browser_cli",
        "memory_primary": "pgvector",
        "knowledge_compiler": "cognee",
        "model_routing": "bifrost",
        "observability": "langfuse",
        "tool_protocol": "mcp_kernel",
    }
    assert m.section("mastra")["compile_to"] == "hatchet"
    assert m.section("mastra")["plan_contract"] == "boltrig.mastra.v1"
    assert m.section("rivet_agentos")["enabled"] is True
    assert m.section("rivet_agentos")["network_allow"] == ["kernel_mcp", "model_endpoint"]
    assert m.section("browser_cli")["enabled"] is True
    assert m.section("browser_cli")["runtime"] == "rivet_agentos"
    assert m.section("browser_cli")["cloud_policy"] == "disabled"
    assert m.section("langfuse")["secret_key_ref"] == "LANGFUSE_SECRET_KEY"

    memory = m.section("memory")
    assert memory["authority"] == "kernel_ledger"
    assert memory["primary_projection"] is None
    assert [p["id"] for p in memory["projections"]] == ["mem0", "cognee"]
    assert [p["enabled"] for p in memory["projections"]] == [False, False]
    assert memory["fanout"]["mode"] == "ledger_then_projection"
    assert memory["fanout"]["execution"] == "inline"

    knowledge = m.section("knowledge")
    assert knowledge["enabled"] is True
    assert knowledge["vault"]["kind"] == "filesystem"
    assert [provider["id"] for provider in knowledge["providers"]] == [
        "cognee",
        "supermemory",
        "mem0",
    ]
    assert [provider["enabled"] for provider in knowledge["providers"]] == [
        True,
        False,
        False,
    ]


@pytest.mark.invariant("FR-HOST-13")
def test_manifest_exports_browser_cloud_policy_without_secret_material():
    m = load_manifest(_MANIFEST)
    env: dict[str, str] = {}

    export_runtime_environment(m, env)

    assert env["BOLTRIG_BROWSER_CLOUD_POLICY"] == "disabled"
    assert "BOLTRIG_BROWSER_CLOUD_API_KEY" not in env
    assert "BOLTRIG_BROWSER_CLOUD_PROFILE_ID" not in env


@pytest.mark.invariant("FR-HOST-13")
def test_manifest_export_does_not_override_browser_cloud_policy():
    m = load_manifest(_MANIFEST)
    env = {"BOLTRIG_BROWSER_CLOUD_POLICY": "stack"}

    export_runtime_environment(m, env)

    assert env["BOLTRIG_BROWSER_CLOUD_POLICY"] == "stack"


@pytest.mark.parametrize("path", [_MANIFEST])
def test_checked_in_manifests_preserve_v2_entrypoints(path):
    m = load_manifest(path)
    adapters = {adapter.id for adapter in m.adapters}
    runtimes = {runtime.name: runtime for runtime in m.ephemeral_runtimes}

    assert m.section("stack")["cockpit"] == "boltrig_ui"
    assert m.section("stack")["coding_agent"] == "codex"
    assert m.section("stack")["browser_automation"] == "browser_cli"
    assert {"herdr", "browser-cli"} <= adapters
    assert "rivet-worker" in runtimes
    assert runtimes["rivet-worker"].runtime == "rivet_agentos"
    assert "opencode-worker" in runtimes
    assert runtimes["opencode-worker"].runtime == "opencode"


def test_local_active_manifest_preserves_v2_entrypoints_when_present():
    if not Path(_ACTIVE_MANIFEST).exists():
        pytest.skip("local active manifest is ignored and absent")
    test_checked_in_manifests_preserve_v2_entrypoints(_ACTIVE_MANIFEST)
