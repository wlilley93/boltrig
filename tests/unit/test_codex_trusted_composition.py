"""Tests for the trusted read-only Codex composition root ([2026] VJS-CC-VJS 2).

``build_trusted_codex_config`` is the api-layer factory that assembles the heavy
``TrustedProxyCodexPhaseCellProvider`` (which imports the fleet infrastructure
layer) and injects it down into ``RuntimeResolver``. These pin the off-by-default
no-op (missing flag / binary / stack root => ``None``, constructs nothing) and the
on path (all three set => a real provider in the expected dict shape). No live
Codex turn runs here; the factory only CONSTRUCTS.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from boltrig.api.codex_trusted import build_trusted_codex_config
from boltrig.config.settings import Settings
from boltrig.fleet.infrastructure.codex_trusted_proxy_provider import (

    TrustedProxyCodexPhaseCellProvider,
)

# Every leg here needs a Linux kernel facility macOS does not have: yama
# ptrace_scope, abstract AF_UNIX names, SO_PEERCRED, or bubblewrap. Marked so a
# non-Linux box reports them as unverified instead of failing; on Linux the
# marker is inert and they always run.
pytestmark = pytest.mark.linux_only

# Any real file that is absolute; the supervisor only records the path at
# construction (binary existence/pinning is verified later, at cell start).
_REAL_BINARY = "/bin/sh"

# Composition now PROVES the read-only sandbox engages before it builds anything on
# it, so the stand-in binary has to answer the probe. These two scripts are the two
# hosts that matter: one whose sandbox refuses writes and permits reads, and one that
# runs the command with no sandbox at all, which is what a kernel without Landlock
# gives you while `sandbox_mode = "read-only"` stays true in the config.
_ENGAGED_SANDBOX = """#!/bin/sh
while [ "$1" != "--" ]; do shift || exit 64; done
shift
case "$*" in
  *">"*) echo "sh: cannot create: Read-only file system" >&2; exit 2 ;;
esac
exec "$@"
"""

_UNENGAGED_SANDBOX = """#!/bin/sh
while [ "$1" != "--" ]; do shift || exit 64; done
shift
exec "$@"
"""


def _fake_codex(tmp_path: Path, name: str, script: str) -> str:
    path = tmp_path / name
    path.write_text(script, encoding="ascii")
    path.chmod(0o755)
    return str(path)


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


@pytest.mark.invariant("CODEX-COMPOSITION-1")
def test_returns_none_when_codex_trusted_off(tmp_path: Path) -> None:
    settings = _settings(
        codex_trusted=False,
        codex_binary=_REAL_BINARY,
        codex_stack_root=str(tmp_path),
    )
    result = build_trusted_codex_config(
        settings, model_id="glm-4.6", gateway_base_url="http://gateway"
    )
    assert result is None


def test_returns_none_when_binary_missing(tmp_path: Path) -> None:
    settings = _settings(
        codex_trusted=True,
        codex_binary=None,
        codex_stack_root=str(tmp_path),
    )
    assert (
        build_trusted_codex_config(settings, model_id="glm-4.6", gateway_base_url="http://gateway")
        is None
    )


def test_returns_none_when_stack_root_missing() -> None:
    settings = _settings(
        codex_trusted=True,
        codex_binary=_REAL_BINARY,
        codex_stack_root=None,
    )
    assert (
        build_trusted_codex_config(settings, model_id="glm-4.6", gateway_base_url="http://gateway")
        is None
    )


@pytest.mark.invariant("SEC-WRK-30")
def test_builds_provider_when_all_three_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The image bakes the shared helper at /opt/boltrig/codex/model_auth_helper,
    # which does not exist on a dev host; /bin/sh has the same proved shape
    # (root-owned, unwritable chain) so the boundary assertion is real, not stubbed.
    monkeypatch.setenv("BOLTRIG_CODEX_AUTH_HELPER", os.path.realpath("/bin/sh"))
    stack_root = tmp_path / "stack"
    stack_root.mkdir()
    settings = _settings(
        codex_trusted=True,
        codex_binary=_fake_codex(tmp_path, "codex-engaged", _ENGAGED_SANDBOX),
        codex_stack_root=str(stack_root),
        model_gateway_key="k",
    )
    result = build_trusted_codex_config(
        settings, model_id="glm-4.6", gateway_base_url="http://gateway"
    )
    assert result is not None
    assert result["trusted"] is True
    assert result["stack_root"] == stack_root
    assert result["model_id"] == "glm-4.6"
    assert isinstance(result["provider"], TrustedProxyCodexPhaseCellProvider)
    assert isinstance(result["receipt_identity"], str)
    assert result["receipt_identity"].startswith("cp_")
    assert str(tmp_path) not in result["receipt_identity"]
    assert "http://gateway" not in result["receipt_identity"]
    assert settings.model_gateway_key not in result["receipt_identity"]
    # Close the httpx client the provider opened so the test leaves nothing running.
    import asyncio

    asyncio.run(result["provider"]._client.aclose())


@pytest.mark.invariant("SEC-WRK-30")
def test_a_host_whose_sandbox_does_not_engage_composes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wiring, proved. Without this the proof above could be deleted silently.

    The test above passes on a fake whose sandbox refuses writes, which is also what
    it would do if the composition root never called the proof at all. This one
    supplies the opposite host - a Codex that runs the command with no sandbox, the
    shape a kernel without Landlock produces - and requires composition to REFUSE.
    """

    from boltrig.fleet.infrastructure.codex_sandbox_engagement import (
        CodexSandboxEngagementError,
    )

    monkeypatch.setenv("BOLTRIG_CODEX_AUTH_HELPER", os.path.realpath("/bin/sh"))
    stack_root = tmp_path / "stack"
    stack_root.mkdir()
    settings = _settings(
        codex_trusted=True,
        codex_binary=_fake_codex(tmp_path, "codex-unengaged", _UNENGAGED_SANDBOX),
        codex_stack_root=str(stack_root),
        model_gateway_key="k",
    )

    with pytest.raises(CodexSandboxEngagementError) as caught:
        build_trusted_codex_config(
            settings, model_id="glm-4.6", gateway_base_url="http://gateway"
        )
    assert "THE SANDBOX DID NOT ENGAGE" in str(caught.value)


@pytest.mark.invariant("CODEX-COMPOSITION-1")
def test_make_app_spawner_threads_codex_and_sensitive_policy_to_resolver() -> None:
    """The /v1/spawn seam must carry the trusted provider ([2026] VJS-CC-VJS 8).

    The gap this guards: ``build_trusted_codex_config`` was injected ONLY into the
    chat spawner, so a ``/v1/spawn`` that pinned a ``runtime: codex`` capability
    resolved the codex runtime yet had no provider and degraded to a script - no
    single call both routed to Codex and answered. ``make_app_spawner`` must thread
    the config into the ``Spawner`` it builds. RuntimeResolver stores only the
    kernel, so a sentinel kernel is enough (mirroring test_runtime_resolver_codex).
    """
    from boltrig.fleet.spawn import Spawner, make_app_spawner

    sentinel = {"trusted": True, "provider": object()}
    app_spawner = make_app_spawner(
        object(),
        codex_config=sentinel,
        sensitive_endpoint_id="local-sensitive",
    )
    # The Spawner is captured in the returned closure; it must carry the config.
    spawner = next(
        cell.cell_contents
        for cell in app_spawner.__closure__ or ()
        if isinstance(cell.cell_contents, Spawner)
    )
    assert spawner._runtime_resolver._codex is sentinel
    assert spawner._runtime_resolver._sensitive_endpoint_id == "local-sensitive"


def test_make_app_spawner_defaults_to_no_codex_config() -> None:
    """Off by default: no config threaded => the codex runtime degrades as before."""
    from boltrig.fleet.spawn import Spawner, make_app_spawner

    app_spawner = make_app_spawner(object())
    spawner = next(
        cell.cell_contents
        for cell in app_spawner.__closure__ or ()
        if isinstance(cell.cell_contents, Spawner)
    )
    assert spawner._runtime_resolver._codex is None
    assert spawner._runtime_resolver._sensitive_endpoint_id is None


@pytest.mark.invariant("CODEX-COMPOSITION-1")
def test_make_agent_invoker_threads_runtime_policy_to_resolver() -> None:
    """Agent-bound verbs share the trusted provider and sensitive route."""
    from boltrig.fleet.spawn import Spawner, make_agent_invoker

    sentinel = {"trusted": True, "provider": object()}
    invoker = make_agent_invoker(
        object(),
        codex_config=sentinel,
        sensitive_endpoint_id="local-sensitive",
    )
    spawner = next(
        cell.cell_contents
        for cell in invoker.__closure__ or ()
        if isinstance(cell.cell_contents, Spawner)
    )
    assert spawner._runtime_resolver._codex is sentinel
    assert spawner._runtime_resolver._sensitive_endpoint_id == "local-sensitive"


@pytest.mark.asyncio
@pytest.mark.invariant("CODEX-COMPOSITION-1")
@pytest.mark.invariant("SEC-WRK-30")
async def test_api_composition_shares_one_codex_config_with_every_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ASGI kernel, Chat, platform and direct spawn share one configuration."""
    from boltrig.api import bootstrap
    from boltrig.api import platform_bootstrap
    from boltrig.kernel import app as kernel_app

    codex_config = {"trusted": True, "provider": object()}
    sensitive_endpoint_id = "local-sensitive"
    spawn_rules = (object(),)
    manifest = SimpleNamespace(
        tenant_id="api-tenant",
        models=SimpleNamespace(sensitive_endpoint=sensitive_endpoint_id),
        spawn_rules=spawn_rules,
    )
    kernel = SimpleNamespace(
        store=SimpleNamespace(list_config_revisions=AsyncMock(return_value=[]))
    )
    addons_snapshot = (object(),)
    chat_factory = object()
    resume_held_write = object()
    platform_factory = object()
    principal_resolver = object()
    build_shared = Mock(return_value=codex_config)
    build_kernel = AsyncMock(return_value=kernel)
    build_chat = Mock(return_value=(chat_factory, resume_held_write))
    build_platform = Mock(return_value=platform_factory)
    make_spawner = Mock(return_value=object())
    load_manifest = Mock(return_value=manifest)
    select_principal_resolver = Mock(return_value=principal_resolver)
    publish_birth_profile = AsyncMock(return_value=True)

    monkeypatch.setattr(bootstrap, "_build_shared_codex_config", build_shared)
    monkeypatch.setattr(bootstrap, "_find_manifest", lambda: "manifest.yaml")
    monkeypatch.setattr(bootstrap, "load_manifest", load_manifest)
    monkeypatch.setattr(bootstrap, "build_kernel_async", build_kernel)
    monkeypatch.setattr(bootstrap, "_build_chat_wiring", build_chat)
    monkeypatch.setattr(bootstrap, "make_app_spawner", make_spawner)
    monkeypatch.setattr(
        bootstrap,
        "select_principal_resolver",
        select_principal_resolver,
    )
    monkeypatch.setattr(
        platform_bootstrap,
        "make_platform_factory",
        build_platform,
    )
    monkeypatch.setattr(
        bootstrap,
        "_publish_birth_profile_startup",
        publish_birth_profile,
    )
    monkeypatch.setattr(kernel_app, "create_app", lambda **kwargs: kwargs)

    wiring = bootstrap.build_app(addons_snapshot=addons_snapshot)
    built_kernel = await wiring["kernel_factory"]()
    wiring["spawner_factory"](kernel)

    assert built_kernel is kernel
    build_shared.assert_called_once_with()
    load_manifest.assert_called_once_with("manifest.yaml")
    select_principal_resolver.assert_called_once_with(manifest)
    model_catalogue = build_kernel.call_args.kwargs["model_catalogue"]
    build_kernel.assert_awaited_once_with(
        codex_config=codex_config,
        model_catalogue=model_catalogue,
        sensitive_endpoint_id=sensitive_endpoint_id,
        manifest_snapshot=manifest,
        manifest_path="manifest.yaml",
    )
    assert build_kernel.call_args.kwargs["codex_config"] is codex_config
    build_chat.assert_called_once_with(
        codex_config,
        spawn_rules,
        sensitive_endpoint_id,
        model_catalogue,
    )
    assert build_chat.call_args.args[0] is codex_config
    assert build_platform.call_args.kwargs["codex_config"] is codex_config
    assert build_platform.call_args.kwargs["model_catalogue"] is model_catalogue
    assert build_platform.call_args.kwargs["sensitive_endpoint_id"] == sensitive_endpoint_id
    make_spawner.assert_called_once_with(
        kernel,
        codex_config=codex_config,
        model_catalogue=model_catalogue,
        sensitive_endpoint_id=sensitive_endpoint_id,
        spawn_rules=spawn_rules,
    )
    assert make_spawner.call_args.kwargs["codex_config"] is codex_config
    publish_birth_profile.assert_awaited_once_with(
        kernel,
        process_kind="api",
        manifest=manifest,
        addons_snapshot=addons_snapshot,
        codex_config=codex_config,
        sensitive_endpoint_id=sensitive_endpoint_id,
    )


@pytest.mark.asyncio
@pytest.mark.invariant("CODEX-COMPOSITION-1")
async def test_kernel_uses_the_composition_manifest_snapshot_without_rereading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kernel and fleet routing cannot split across two manifest file reads."""
    from boltrig.api import bootstrap

    codex_config = {"trusted": True, "provider": object()}
    sensitive_endpoint_id = "local-sensitive"
    manifest = SimpleNamespace(
        tenant_id="snapshot-tenant",
        models=SimpleNamespace(sensitive_endpoint=sensitive_endpoint_id),
        hitl=SimpleNamespace(approval_timeout_seconds=30),
        # None, not omitted. This double stands in for a REAL FleetManifest at the
        # composition root, and a field the double lacks is an AttributeError there
        # rather than a default - which is how the merge found it. None is also the
        # right value on the merits: no posture declared is the fail-closed answer.
        development_posture=None,
        blocking_verbs=Mock(return_value={"sensitive.write"}),
    )
    kernel = SimpleNamespace(set_agent_invoker=Mock())
    seed_manifest = AsyncMock(return_value=None)
    invoker = object()

    monkeypatch.setattr(bootstrap, "refuse_default_audit_key_in_prod", Mock())
    monkeypatch.setattr(bootstrap, "build_store", AsyncMock(return_value=object()))
    monkeypatch.setattr(bootstrap, "build_counter", Mock(return_value=object()))
    monkeypatch.setattr(bootstrap, "build_event_relay", Mock(return_value=object()))
    monkeypatch.setattr(bootstrap, "Kernel", Mock(return_value=kernel))
    monkeypatch.setattr(bootstrap, "_desktop_hands_enabled", Mock(return_value=False))
    monkeypatch.setattr(bootstrap, "_seed_from_manifest", seed_manifest)
    monkeypatch.setattr(
        bootstrap,
        "load_manifest",
        Mock(side_effect=AssertionError("manifest was reread")),
    )
    make_agent_invoker = Mock(return_value=invoker)
    monkeypatch.setattr(bootstrap, "make_agent_invoker", make_agent_invoker)

    result = await bootstrap.build_kernel_async(
        codex_config=codex_config,
        sensitive_endpoint_id=sensitive_endpoint_id,
        manifest_snapshot=manifest,
        manifest_path="manifest.yaml",
    )

    assert result is kernel
    seed_manifest.assert_awaited_once_with(kernel, manifest, model_catalogue=None)
    make_agent_invoker.assert_called_once_with(
        kernel,
        codex_config=codex_config,
        model_catalogue=None,
        sensitive_endpoint_id=sensitive_endpoint_id,
    )
    kernel.set_agent_invoker.assert_called_once_with(invoker)


@pytest.mark.asyncio
@pytest.mark.invariant("CODEX-COMPOSITION-1")
@pytest.mark.invariant("SEC-WRK-30")
async def test_standalone_worker_shares_one_codex_provider_with_its_spawner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The standalone fleet worker must not strand Codex-configured profiles."""
    from boltrig.api import worker

    codex_config = {"trusted": True, "provider": object()}
    kernel = SimpleNamespace(
        store=object(),
        anchorer=object(),
        aclose=AsyncMock(),
    )
    executor = SimpleNamespace(durable=False)
    spawner = object()
    pump = SimpleNamespace(heads={}, run_forever=AsyncMock())
    manifest = SimpleNamespace(
        tenant_id="worker-tenant",
        models=SimpleNamespace(sensitive_endpoint="local-sensitive"),
        spawn_rules=(object(),),
    )
    build_shared = Mock(return_value=codex_config)
    build_kernel = AsyncMock(return_value=kernel)
    build_spawner = Mock(return_value=spawner)
    build_org = Mock(return_value=pump)
    effective_manifest = AsyncMock(return_value=manifest)
    record_observation = AsyncMock(return_value=None)
    publish_birth_profile = AsyncMock(return_value=True)

    monkeypatch.setattr(worker, "build_kernel_async", build_kernel)
    monkeypatch.setattr(worker, "register_workers", Mock(return_value=executor))
    monkeypatch.setattr(worker, "_build_shared_codex_config", build_shared)
    monkeypatch.setattr(worker, "_find_manifest", lambda: "manifest.yaml")
    load_manifest = Mock(return_value=manifest)
    monkeypatch.setattr(worker, "load_manifest", load_manifest)
    monkeypatch.setattr(
        worker,
        "effective_manifest_from_desired",
        effective_manifest,
    )
    monkeypatch.setattr(
        worker,
        "record_permanent_fleet_startup_observation",
        record_observation,
    )
    monkeypatch.setattr(
        worker,
        "_publish_birth_profile_startup",
        publish_birth_profile,
    )
    monkeypatch.setattr(worker, "build_spawner", build_spawner)
    monkeypatch.setattr(worker, "build_org", build_org)
    monkeypatch.setattr(worker, "load_settings", Mock(return_value=object()))
    monkeypatch.setattr(worker, "build_codex_execution_stack", Mock(return_value=None))
    monkeypatch.setattr(worker, "_start_anchor_janitor", lambda *_args: None)
    monkeypatch.setattr(worker, "_start_hitl_expiry_janitor", lambda *_args: None)
    monkeypatch.setattr(worker, "_start_retention_janitor", lambda *_args: None)
    monkeypatch.delenv("REDIS_URL", raising=False)

    await worker._run()

    build_shared.assert_called_once_with()
    load_manifest.assert_called_once_with("manifest.yaml")
    model_catalogue = build_kernel.call_args.kwargs["model_catalogue"]
    build_kernel.assert_awaited_once_with(
        codex_config=codex_config,
        model_catalogue=model_catalogue,
        sensitive_endpoint_id=manifest.models.sensitive_endpoint,
        manifest_snapshot=manifest,
        manifest_path="manifest.yaml",
    )
    assert build_kernel.call_args.kwargs["codex_config"] is codex_config
    build_spawner.assert_called_once_with(
        kernel,
        codex_config=codex_config,
        model_catalogue=model_catalogue,
        sensitive_endpoint_id=manifest.models.sensitive_endpoint,
        spawn_rules=manifest.spawn_rules,
    )
    assert build_spawner.call_args.kwargs["codex_config"] is codex_config
    assert build_org.call_args.args[1] is spawner
    assert build_org.call_args.args[2] is manifest
    effective_manifest.assert_awaited_once_with(kernel.store, manifest)
    publish_birth_profile.assert_awaited_once_with(
        kernel,
        process_kind="fleet",
        manifest=manifest,
        addons_snapshot=worker._ADDONS,
        codex_config=codex_config,
        sensitive_endpoint_id=manifest.models.sensitive_endpoint,
    )
    record_observation.assert_awaited_once()
    kernel.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.invariant("CODEX-COMPOSITION-1")
@pytest.mark.invariant("SEC-WRK-30")
async def test_default_hatchet_bootstrap_shares_one_codex_provider_with_its_spawner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default Hatchet task resources use the same trusted composition."""
    import boltrig.addons as addon_module
    import boltrig.config as config_module
    from boltrig.api import bootstrap as bootstrap_module
    from boltrig.api import codex_execution as codex_execution_module
    from boltrig.config import permanent_fleet as permanent_fleet_module
    from boltrig.fleet import hatchet_app
    from boltrig.fleet import pump as pump_module
    from boltrig.fleet import spawn as spawn_module

    codex_config = {"trusted": True, "provider": object()}
    kernel = SimpleNamespace(store=object())
    spawner = object()
    pump = object()
    manifest = SimpleNamespace(
        tenant_id="hatchet-tenant",
        models=SimpleNamespace(sensitive_endpoint="local-sensitive"),
        spawn_rules=(object(),),
    )
    build_shared = Mock(return_value=codex_config)
    build_kernel = AsyncMock(return_value=kernel)
    build_spawner = Mock(return_value=spawner)
    build_org = Mock(return_value=pump)
    wire_hitl_resume = Mock()
    effective_manifest = AsyncMock(return_value=manifest)
    record_observation = AsyncMock(return_value=None)
    publish_birth_profile = AsyncMock(return_value=True)
    addons_snapshot = (object(),)

    monkeypatch.setattr(
        bootstrap_module,
        "build_kernel_async",
        build_kernel,
    )
    monkeypatch.setattr(bootstrap_module, "_find_manifest", lambda: "manifest.yaml")
    monkeypatch.setattr(
        bootstrap_module,
        "_build_shared_codex_config",
        build_shared,
    )
    monkeypatch.setattr(bootstrap_module, "wire_hitl_resume", wire_hitl_resume)
    monkeypatch.setattr(
        bootstrap_module,
        "_publish_birth_profile_startup",
        publish_birth_profile,
    )
    monkeypatch.setattr(addon_module, "active_addons", Mock(return_value=addons_snapshot))
    load_manifest = Mock(return_value=manifest)
    monkeypatch.setattr(config_module, "load_manifest", load_manifest)
    monkeypatch.setattr(config_module, "load_settings", Mock(return_value=object()))
    monkeypatch.setattr(
        permanent_fleet_module,
        "effective_manifest_from_desired",
        effective_manifest,
    )
    monkeypatch.setattr(
        permanent_fleet_module,
        "record_permanent_fleet_startup_observation",
        record_observation,
    )
    monkeypatch.setattr(
        codex_execution_module,
        "build_codex_execution_stack",
        Mock(return_value=None),
    )
    monkeypatch.setattr(spawn_module, "build_spawner", build_spawner)
    monkeypatch.setattr(pump_module, "build_org", build_org)

    resources = await hatchet_app._default_bootstrap()

    build_shared.assert_called_once_with()
    load_manifest.assert_called_once_with("manifest.yaml")
    model_catalogue = build_kernel.call_args.kwargs["model_catalogue"]
    build_kernel.assert_awaited_once_with(
        codex_config=codex_config,
        model_catalogue=model_catalogue,
        sensitive_endpoint_id=manifest.models.sensitive_endpoint,
        manifest_snapshot=manifest,
        manifest_path="manifest.yaml",
    )
    assert build_kernel.call_args.kwargs["codex_config"] is codex_config
    build_spawner.assert_called_once_with(
        kernel,
        codex_config=codex_config,
        model_catalogue=model_catalogue,
        sensitive_endpoint_id=manifest.models.sensitive_endpoint,
        spawn_rules=manifest.spawn_rules,
    )
    assert build_spawner.call_args.kwargs["codex_config"] is codex_config
    assert build_org.call_args.args[1] is spawner
    assert build_org.call_args.args[2] is manifest
    effective_manifest.assert_awaited_once_with(kernel.store, manifest)
    publish_birth_profile.assert_awaited_once_with(
        kernel,
        process_kind="hatchet",
        manifest=manifest,
        addons_snapshot=addons_snapshot,
        codex_config=codex_config,
        sensitive_endpoint_id=manifest.models.sensitive_endpoint,
    )
    record_observation.assert_awaited_once()
    wire_hitl_resume.assert_called_once_with(kernel, pump=pump)
    assert resources == {"kernel": kernel, "pump": pump, "spawner": spawner}


@pytest.mark.asyncio
@pytest.mark.invariant("SEC-WRK-27")
@pytest.mark.invariant("SEC-WRK-30")
async def test_hatchet_failed_manifest_overlay_cannot_claim_startup_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the exact desired hierarchy handed to build_org may be observed."""
    import boltrig.addons as addon_module
    import boltrig.config as config_module
    from boltrig.api import bootstrap as bootstrap_module
    from boltrig.api import codex_execution as codex_execution_module
    from boltrig.config import permanent_fleet as permanent_fleet_module
    from boltrig.fleet import hatchet_app
    from boltrig.fleet import pump as pump_module
    from boltrig.fleet import spawn as spawn_module

    codex_config = {"trusted": True, "provider": object()}
    kernel = SimpleNamespace(store=object())
    source_manifest = SimpleNamespace(models=SimpleNamespace(sensitive_endpoint="local-sensitive"))
    spawner = object()
    pump = object()
    build_spawner = Mock(return_value=spawner)
    build_org = Mock(return_value=pump)
    record_observation = AsyncMock(return_value=None)
    publish_birth_profile = AsyncMock(return_value=True)
    addons_snapshot = (object(),)
    wire_hitl_resume = Mock()

    load_manifest = Mock(return_value=source_manifest)
    build_kernel = AsyncMock(return_value=kernel)
    monkeypatch.setattr(
        bootstrap_module,
        "build_kernel_async",
        build_kernel,
    )
    monkeypatch.setattr(bootstrap_module, "_find_manifest", lambda: "manifest.yaml")
    monkeypatch.setattr(
        bootstrap_module,
        "_build_shared_codex_config",
        Mock(return_value=codex_config),
    )
    monkeypatch.setattr(bootstrap_module, "wire_hitl_resume", wire_hitl_resume)
    monkeypatch.setattr(
        bootstrap_module,
        "_publish_birth_profile_startup",
        publish_birth_profile,
    )
    monkeypatch.setattr(addon_module, "active_addons", Mock(return_value=addons_snapshot))
    monkeypatch.setattr(
        config_module,
        "load_manifest",
        load_manifest,
    )
    monkeypatch.setattr(config_module, "load_settings", Mock(return_value=object()))
    monkeypatch.setattr(
        permanent_fleet_module,
        "effective_manifest_from_desired",
        AsyncMock(side_effect=RuntimeError("desired overlay failed")),
    )
    monkeypatch.setattr(
        permanent_fleet_module,
        "record_permanent_fleet_startup_observation",
        record_observation,
    )
    monkeypatch.setattr(
        codex_execution_module,
        "build_codex_execution_stack",
        Mock(return_value=None),
    )
    monkeypatch.setattr(spawn_module, "build_spawner", build_spawner)
    monkeypatch.setattr(pump_module, "build_org", build_org)

    resources = await hatchet_app._default_bootstrap()

    load_manifest.assert_called_once_with("manifest.yaml")
    model_catalogue = build_kernel.call_args.kwargs["model_catalogue"]
    build_kernel.assert_awaited_once_with(
        codex_config=codex_config,
        model_catalogue=model_catalogue,
        sensitive_endpoint_id=source_manifest.models.sensitive_endpoint,
        manifest_snapshot=source_manifest,
        manifest_path="manifest.yaml",
    )
    build_spawner.assert_called_once_with(
        kernel,
        codex_config=codex_config,
        model_catalogue=model_catalogue,
        sensitive_endpoint_id=None,
    )
    assert build_org.call_args.args[2] is None
    publish_birth_profile.assert_awaited_once_with(
        kernel,
        process_kind="hatchet",
        manifest=None,
        addons_snapshot=addons_snapshot,
        codex_config=codex_config,
        sensitive_endpoint_id=None,
    )
    record_observation.assert_not_awaited()
    wire_hitl_resume.assert_called_once_with(kernel, pump=pump)
    assert resources == {"kernel": kernel, "pump": pump, "spawner": spawner}


@pytest.mark.asyncio
@pytest.mark.invariant("CODEX-COMPOSITION-1")
async def test_local_ultracode_task_uses_only_its_composition_owned_spawner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Durable task registration forwards the exact prebuilt spawner."""
    from boltrig.fleet import hatchet_ultracode
    from boltrig.fleet.hatchet_ultracode import (
        TASK_ULTRACODE_AGENT,
        register_local_ultracode_tasks,
    )
    from boltrig.fleet.workers import LocalDurableExecutor

    kernel = object()
    spawner = object()
    execute = AsyncMock(return_value={"status": "ok"})
    executor = LocalDurableExecutor()

    # Replace the lazy wrapper with a recorder while retaining the registration
    # closure under test.
    async def record(
        actual_kernel: object,
        payload: dict[str, object],
        *,
        spawner: object | None,
    ) -> dict[str, str]:
        return await execute(actual_kernel, payload, spawner=spawner)

    monkeypatch.setattr(hatchet_ultracode, "ultracode_agent_body", record)
    register_local_ultracode_tasks(executor, kernel, spawner=spawner)

    await executor.enqueue(TASK_ULTRACODE_AGENT, {"task": "bounded"})

    execute.assert_awaited_once_with(
        kernel,
        {"task": "bounded"},
        spawner=spawner,
    )
    assert execute.call_args.kwargs["spawner"] is spawner


@pytest.mark.invariant("CODEX-COMPOSITION-1")
def test_every_packaged_build_spawner_call_explicitly_threads_runtime_policy() -> None:
    """A new packaged spawner cannot drop provider or sensitive-route policy."""
    package = Path(__file__).resolve().parents[2] / "boltrig"
    missing: list[str] = []
    seen = 0
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if name != "build_spawner":
                continue
            seen += 1
            keywords = {keyword.arg for keyword in node.keywords}
            absent = {"codex_config", "sensitive_endpoint_id"} - keywords
            if absent:
                missing.append(
                    f"{path.relative_to(package.parent)}:{node.lineno}:{','.join(sorted(absent))}"
                )
    assert seen >= 7
    assert missing == []
