"""Deep, fail-closed readiness contract for /readyz (FR-OPS-03)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest
import fakeredis
from fastapi.testclient import TestClient
from fakeredis import aioredis as fake_aioredis

from boltrig.api.readiness import (
    EXPECTED_ALEMBIC_HEAD,
    REQUIRED_CONTROL_VERBS,
    ReadinessService,
)
from boltrig.config.control_plane import ControlPlaneAdapter
from boltrig.config.admin import AdminConfig
from boltrig.kernel import Kernel
from boltrig.kernel.redis_event_relay import RedisEventRelay
from boltrig.kernel.app import create_app
from boltrig.models import TargetType, VerbBinding
from boltrig.store import InMemoryStore
from boltrig.workflows import WorkflowLibrary

pytestmark = pytest.mark.unit


class _StatusProvider:
    def __init__(self, *, tool_status: str = "ok", gateway_status: str = "ok") -> None:
        self.tool_status = tool_status
        self.gateway_status = gateway_status

    async def snapshot(self, *, tenant_id: str, workspace_id: str | None) -> dict[str, Any]:
        del tenant_id, workspace_id
        components = [
            {"id": name, "status": self.tool_status, "metadata": {}}
            for name in ("herdr", "opencode", "browser-cli")
        ]
        components.append(
            {
                "id": "bifrost",
                "status": self.gateway_status,
                "metadata": {"live_health": self.gateway_status},
            }
        )
        return {"components": components, "runtimes": []}


class _HatchetClient:
    async def aio_get_engine_version(self) -> str:
        return "test-engine"


class _DurableExecutor:
    durable = True
    client = _HatchetClient()


async def _kernel(
    *,
    control: bool = True,
    collaborators: bool = True,
    shared_relay: bool = False,
) -> Kernel:
    store = InMemoryStore()
    relay = None
    if shared_relay:
        server = fakeredis.FakeServer()
        relay = RedisEventRelay(
            fakeredis.FakeRedis(server=server, decode_responses=True),
            fake_aioredis.FakeRedis(server=server, decode_responses=True),
            namespace="readiness",
        )
    kernel = Kernel(store, event_relay=relay)
    if control:
        adapter = ControlPlaneAdapter(
            store,
            loader=kernel.loader,
            registry=kernel.registry,
            admin=AdminConfig(store, tenant_id="acme", doc={}) if collaborators else None,
            workflows=WorkflowLibrary(store, kernel=kernel) if collaborators else None,
        )
        await kernel.register_adapter("acme", adapter)
    return kernel


async def _postgres_ok() -> tuple[bool, tuple[str, ...]]:
    return True, (EXPECTED_ALEMBIC_HEAD,)


async def _redis_ok(_url: str, _timeout: float) -> bool:
    return True


async def _herdr_ok(_env: Mapping[str, str], _timeout: float) -> bool:
    return True


async def _fleet_receipt_ok(
    _url: str,
    _tenant: str,
    _timeout: float,
    _max_age: float,
    _signing_key: bytes,
) -> tuple[bool, str]:
    return True, "ok"


@pytest.mark.invariant("FR-OPS-03")
async def test_readyz_keeps_optional_dependencies_disabled_in_development() -> None:
    report = await ReadinessService(
        await _kernel(),
        tenant_id="acme",
        env={},
        status_provider=_StatusProvider(),
    ).check()

    assert report["status"] == "ready"
    assert report["checks"]["control_plane"]["status"] == "ok"
    assert report["checks"]["stack_tools"]["status"] == "ok"
    for name in (
        "postgres",
        "redis",
        "migration",
        "hatchet",
        "model_gateway",
        "password_reset_delivery",
    ):
        assert report["checks"][name]["status"] == "disabled"
        assert report["checks"][name]["required"] is False


@pytest.mark.invariant("FR-OPS-03")
async def test_password_reset_delivery_readiness_requires_notifier_and_probe() -> None:
    env = {"BOLTRIG_REQUIRE_PASSWORD_RESET_DELIVERY": "1"}

    absent = await ReadinessService(
        await _kernel(),
        tenant_id="acme",
        env=env,
        status_provider=_StatusProvider(),
    ).check()
    assert absent["checks"]["password_reset_delivery"] == {
        "status": "failed",
        "required": True,
        "reason": "not_configured",
        "notifier_configured": False,
        "provider_delivery_proven": False,
    }

    def notifier(_notice) -> bool:
        return True

    unprobed = await ReadinessService(
        await _kernel(),
        tenant_id="acme",
        env=env,
        status_provider=_StatusProvider(),
        password_reset_notifier=notifier,
    ).check()
    assert unprobed["checks"]["password_reset_delivery"]["reason"] == (
        "readiness_probe_not_configured"
    )

    async def ready_probe() -> bool:
        return True

    ready = await ReadinessService(
        await _kernel(),
        tenant_id="acme",
        env=env,
        status_provider=_StatusProvider(),
        password_reset_notifier=notifier,
        password_reset_probe=ready_probe,
    ).check()
    assert ready["status"] == "ready"
    assert ready["checks"]["password_reset_delivery"] == {
        "status": "ok",
        "required": True,
        "notifier_configured": True,
        "provider_delivery_proven": False,
    }


@pytest.mark.invariant("FR-OPS-03")
async def test_readyz_requires_postgres_redis_and_migration_head_in_production() -> None:
    report = await ReadinessService(
        await _kernel(),
        tenant_id="acme",
        env={
            "BOLTRIG_ENV": "production",
            "BOLTRIG_AUDIT_HMAC_KEY": "test-readiness-key",
        },
        status_provider=_StatusProvider(),
        herdr_probe=_herdr_ok,
        fleet_receipt_probe=_fleet_receipt_ok,
    ).check()

    assert report["status"] == "not_ready"
    assert report["checks"]["postgres"]["reason"] == "not_configured"
    assert report["checks"]["redis"]["reason"] == "not_configured"
    assert report["checks"]["migration"]["reason"] == "postgres_unavailable"


@pytest.mark.invariant("FR-OPS-03")
async def test_readyz_rejects_a_process_local_relay_in_production() -> None:
    report = await ReadinessService(
        await _kernel(),
        tenant_id="acme",
        env={
            "BOLTRIG_ENV": "production",
            "REDIS_URL": "redis://redacted",
            "BOLTRIG_AUDIT_HMAC_KEY": "test-readiness-key",
        },
        status_provider=_StatusProvider(),
        redis_probe=_redis_ok,
        herdr_probe=_herdr_ok,
        fleet_receipt_probe=_fleet_receipt_ok,
    ).check()

    assert report["checks"]["redis"] == {
        "status": "failed",
        "required": True,
        "reason": "wrong_backend",
    }


@pytest.mark.invariant("FR-OPS-03")
async def test_readyz_requires_redis_stream_and_transaction_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = await _kernel(shared_relay=True)

    async def denied_capabilities() -> bool:
        return False

    monkeypatch.setattr(kernel.events, "readiness", denied_capabilities)
    report = await ReadinessService(
        kernel,
        tenant_id="acme",
        env={
            "BOLTRIG_ENV": "production",
            "REDIS_URL": "redis://redacted",
            "BOLTRIG_AUDIT_HMAC_KEY": "test-readiness-key",
        },
        status_provider=_StatusProvider(),
        redis_probe=_redis_ok,
        herdr_probe=_herdr_ok,
        fleet_receipt_probe=_fleet_receipt_ok,
    ).check()

    assert report["checks"]["redis"]["reason"] == "capability_failed"


@pytest.mark.invariant("FR-OPS-03")
async def test_readyz_probes_every_enabled_dependency() -> None:
    env = {
        "BOLTRIG_ENV": "production",
        "DATABASE_URL": "postgresql://redacted",
        "REDIS_URL": "redis://redacted",
        "BOLTRIG_HATCHET_HEALTH": "1",
        "BOLTRIG_MODEL_GATEWAY_HEALTH": "1",
        "BOLTRIG_MODEL_GATEWAY_URL": "http://bifrost:8080/v1",
        "BOLTRIG_AUDIT_HMAC_KEY": "test-readiness-key",
    }
    report = await ReadinessService(
        await _kernel(shared_relay=True),
        tenant_id="acme",
        executor=_DurableExecutor(),
        env=env,
        status_provider=_StatusProvider(),
        postgres_probe=_postgres_ok,
        redis_probe=_redis_ok,
        herdr_probe=_herdr_ok,
        fleet_receipt_probe=_fleet_receipt_ok,
    ).check()

    assert report["status"] == "ready"
    assert {
        item["status"]
        for item in report["checks"].values()
        if item["required"]
    } == {"ok"}
    for name in ("hitl_expiry_janitor", "retention_janitor"):
        assert report["checks"][name] == {
            "status": "unknown",
            "required": False,
            "reason": "attempt_evidence_not_observed",
            "evidence_kind": "bounded_attempt_receipt_not_liveness",
            "proves_liveness": False,
            "process_coverage": "bounded_receipts_not_replica_inventory",
            "observed_process_receipts": 0,
        }
    assert report["checks"]["migration"]["current"] == EXPECTED_ALEMBIC_HEAD
    assert report["checks"]["control_plane"]["registered"] == len(REQUIRED_CONTROL_VERBS)
    assert report["checks"]["stack_tools"]["live_health"] == "ok"
    assert "postgresql://" not in repr(report)
    assert "redis://" not in repr(report)


@pytest.mark.invariant("FR-OPS-03")
async def test_readyz_requires_persisted_control_verbs_and_control_owned_bindings() -> None:
    missing = await _kernel()
    missing.store._bindings.pop(("acme", "control.adapter.generate"))
    missing_report = await ReadinessService(
        missing, tenant_id="acme", env={}, status_provider=_StatusProvider()
    ).check()
    assert missing_report["status"] == "not_ready"
    assert missing_report["checks"]["control_plane"]["reason"] == "incomplete_persistence"

    hijacked = await _kernel()
    await hijacked.store.upsert_binding(
        VerbBinding("control.adapter.generate", "acme", TargetType.ADAPTER, "attacker")
    )
    hijacked_report = await ReadinessService(
        hijacked, tenant_id="acme", env={}, status_provider=_StatusProvider()
    ).check()
    assert hijacked_report["status"] == "not_ready"
    assert hijacked_report["checks"]["control_plane"]["reason"] == "invalid_bindings"


@pytest.mark.invariant("FR-OPS-03")
async def test_readyz_requires_control_runtime_collaborators() -> None:
    report = await ReadinessService(
        await _kernel(collaborators=False),
        tenant_id="acme",
        env={},
        status_provider=_StatusProvider(),
    ).check()
    assert report["status"] == "not_ready"
    assert report["checks"]["control_plane"]["reason"] == "collaborators_unavailable"


@pytest.mark.invariant("FR-OPS-03")
@pytest.mark.parametrize(
    ("receipt_reason", "expected_reason"),
    [
        ("missing", "fleet_receipt_missing"),
        ("stale", "fleet_receipt_stale"),
        ("malformed", "fleet_receipt_malformed"),
        ("degraded", "fleet_receipt_degraded"),
        ("unauthenticated", "fleet_receipt_unauthenticated"),
    ],
)
async def test_readyz_rejects_untrustworthy_fleet_tool_receipts_in_production(
    receipt_reason: str, expected_reason: str
) -> None:
    async def rejected_receipt(
        _url: str,
        _tenant: str,
        _timeout: float,
        _max_age: float,
        _signing_key: bytes,
    ) -> tuple[bool, str]:
        return False, receipt_reason

    report = await ReadinessService(
        await _kernel(),
        tenant_id="acme",
        env={
            "BOLTRIG_ENV": "production",
            "DATABASE_URL": "postgresql://redacted",
            "REDIS_URL": "redis://redacted",
            "BOLTRIG_AUDIT_HMAC_KEY": "test-readiness-key",
        },
        status_provider=_StatusProvider(),
        postgres_probe=_postgres_ok,
        redis_probe=_redis_ok,
        herdr_probe=_herdr_ok,
        fleet_receipt_probe=rejected_receipt,
    ).check()

    assert report["status"] == "not_ready"
    stack = report["checks"]["stack_tools"]
    assert stack["status"] == "failed"
    assert stack["reason"] == expected_reason
    assert stack["live_health"] == "failed"
    assert "redacted" not in repr(stack)


@pytest.mark.invariant("FR-OPS-03")
async def test_readyz_explicit_stack_tool_health_requires_kernel_owned_herdr() -> None:
    async def missing_herdr(_env: Mapping[str, str], _timeout: float) -> bool:
        return False

    report = await ReadinessService(
        await _kernel(),
        tenant_id="acme",
        env={
            "BOLTRIG_REQUIRE_STACK_TOOL_HEALTH": "1",
            "REDIS_URL": "redis://redacted",
            "BOLTRIG_AUDIT_HMAC_KEY": "test-readiness-key",
        },
        status_provider=_StatusProvider(),
        redis_probe=_redis_ok,
        herdr_probe=missing_herdr,
        fleet_receipt_probe=_fleet_receipt_ok,
    ).check()

    assert report["status"] == "not_ready"
    assert report["checks"]["stack_tools"]["reason"] == "herdr_probe_failed"


@pytest.mark.invariant("FR-OPS-03")
async def test_readyz_coalesces_concurrent_unauthenticated_probes() -> None:
    herdr_calls = 0
    receipt_calls = 0

    async def counted_herdr(_env: Mapping[str, str], _timeout: float) -> bool:
        nonlocal herdr_calls
        herdr_calls += 1
        await asyncio.sleep(0.03)
        return True

    async def counted_receipt(
        _url: str,
        _tenant: str,
        _timeout: float,
        _max_age: float,
        _signing_key: bytes,
    ) -> tuple[bool, str]:
        nonlocal receipt_calls
        receipt_calls += 1
        return True, "ok"

    readiness = ReadinessService(
        await _kernel(),
        tenant_id="acme",
        env={
            "BOLTRIG_REQUIRE_STACK_TOOL_HEALTH": "1",
            "BOLTRIG_AUDIT_HMAC_KEY": "test-readiness-key",
            "BOLTRIG_READINESS_CACHE_TTL": "1",
            "REDIS_URL": "redis://redacted",
        },
        status_provider=_StatusProvider(),
        redis_probe=_redis_ok,
        herdr_probe=counted_herdr,
        fleet_receipt_probe=counted_receipt,
    )

    reports = await asyncio.gather(*(readiness.check() for _ in range(12)))
    cached = await readiness.check()

    assert {report["status"] for report in reports} == {"ready"}
    assert cached["status"] == "ready"
    assert herdr_calls == 1
    assert receipt_calls == 1


@pytest.mark.invariant("FR-OPS-03")
def test_readyz_persists_the_fallback_service_across_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances = 0

    class FakeReadinessService:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal instances
            instances += 1

        async def check(self) -> dict[str, str]:
            return {"status": "ready"}

    monkeypatch.setattr(
        "boltrig.api.readiness.ReadinessService",
        FakeReadinessService,
    )
    client = TestClient(create_app(asyncio.run(_kernel()), platform={"status": _StatusProvider()}))

    first = client.get("/readyz")
    second = client.get("/readyz")

    assert first.status_code == second.status_code == 200
    assert instances == 1


@pytest.mark.invariant("FR-OPS-03")
def test_readyz_route_returns_503_with_redacted_component_failures() -> None:
    async def old_database() -> tuple[bool, tuple[str, ...]]:
        return True, ("0021-secret-catalogue-value",)

    async def dead_redis(_url: str, _timeout: float) -> bool:
        return False

    env: Mapping[str, str] = {
        "BOLTRIG_ENV": "production",
        "DATABASE_URL": "postgresql://user:secret@db/boltrig",
        "REDIS_URL": "redis://:secret@redis/0",
        "BOLTRIG_HATCHET_HEALTH": "1",
        "BOLTRIG_MODEL_GATEWAY_HEALTH": "1",
        "BOLTRIG_MODEL_GATEWAY_URL": "http://bifrost:8080/v1",
        "BOLTRIG_AUDIT_HMAC_KEY": "test-readiness-key",
    }
    kernel = asyncio.run(_kernel(control=False, shared_relay=True))
    readiness = ReadinessService(
        kernel,
        tenant_id="acme",
        executor=object(),
        env=env,
        status_provider=_StatusProvider(gateway_status="down"),
        postgres_probe=old_database,
        redis_probe=dead_redis,
        herdr_probe=_herdr_ok,
        fleet_receipt_probe=_fleet_receipt_ok,
    )
    response = TestClient(create_app(kernel, platform={"readiness": readiness})).get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["migration"]["reason"] == "head_mismatch"
    assert body["checks"]["redis"]["reason"] == "probe_failed"
    assert body["checks"]["control_plane"]["reason"] == "not_registered"
    assert body["checks"]["hatchet"]["reason"] == "durable_executor_unavailable"
    assert body["checks"]["model_gateway"]["reason"] == "probe_failed"
    assert "secret" not in response.text
    assert "postgresql://" not in response.text
    assert "redis://" not in response.text
