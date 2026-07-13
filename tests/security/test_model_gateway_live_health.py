"""Optional Bifrost live health stays internal, bounded, and redacted."""

from __future__ import annotations

import asyncio

import pytest

from boltrig.fleet.model_gateway_status import ModelGatewayStatusProvider


def _snapshot(provider: ModelGatewayStatusProvider) -> dict:
    return asyncio.run(provider.snapshot(tenant_id="acme", workspace_id=None))


@pytest.mark.security
@pytest.mark.invariant("FR-GW-04")
def test_model_gateway_live_health_polls_internal_endpoint_and_redacts_payload():
    seen = {}

    async def probe(url: str, timeout_s: float):
        seen.update({"url": url, "timeout": timeout_s})
        return "ok", {
            "providers": [{"name": "openai", "api_key": "secret"}],
            "cache": {"hits": 12, "misses": 3, "hit_rate": 0.8},
            "base_url": "http://bifrost:8080/v1",
        }

    body = _snapshot(ModelGatewayStatusProvider(
        env={
            "BOLTRIG_MODEL_GATEWAY_URL": "http://bifrost:8080/v1",
            "BOLTRIG_MODEL_GATEWAY_HEALTH": "1",
            "BOLTRIG_MODEL_GATEWAY_HEALTH_TIMEOUT": "0.2",
        },
        health_probe=probe,
    ))
    component = {item["id"]: item for item in body["components"]}["bifrost"]
    runtime = {item["id"]: item for item in body["runtimes"]}["model-gateway"]

    assert seen == {"url": "http://bifrost:8080/health", "timeout": 0.2}
    assert component["status"] == "ok"
    assert component["metadata"]["live_health"] == "ok"
    assert component["metadata"]["health_source"] == "derived"
    assert component["metadata"]["provider_count"] == 1
    assert component["metadata"]["cache_hits"] == 12
    assert component["metadata"]["cache_misses"] == 3
    assert component["metadata"]["cache_hit_rate"] == 0.8
    assert runtime["metadata"]["live_health"] == "ok"

    rendered = repr(body).lower()
    assert "api_key" not in rendered
    assert "secret" not in rendered
    assert "http://bifrost" not in rendered
    assert "base_url" not in rendered


@pytest.mark.security
@pytest.mark.invariant("FR-GW-04")
def test_model_gateway_live_health_rejects_external_hosts_without_polling():
    async def probe(url: str, timeout_s: float):  # pragma: no cover - must not run
        raise AssertionError(f"unexpected poll {url} {timeout_s}")

    body = _snapshot(ModelGatewayStatusProvider(
        env={
            "BOLTRIG_MODEL_GATEWAY_URL": "https://gateway.example.com/v1",
            "BOLTRIG_MODEL_GATEWAY_HEALTH": "1",
        },
        health_probe=probe,
    ))
    component = {item["id"]: item for item in body["components"]}["bifrost"]

    assert component["status"] == "degraded"
    assert component["metadata"]["live_health"] == "degraded"
    assert component["metadata"]["health_error"] == "external_host_rejected"
    assert "gateway.example.com" not in repr(body)


@pytest.mark.security
@pytest.mark.invariant("FR-GW-04")
def test_model_gateway_live_health_probe_failure_degrades_not_crashes():
    async def probe(url: str, timeout_s: float):  # noqa: ARG001
        raise TimeoutError("gateway did not answer")

    body = _snapshot(ModelGatewayStatusProvider(
        env={
            "BOLTRIG_MODEL_GATEWAY_URL": "http://bifrost:8080/v1",
            "BOLTRIG_MODEL_GATEWAY_HEALTH_URL": "http://bifrost:8080/healthz",
        },
        health_probe=probe,
    ))
    component = {item["id"]: item for item in body["components"]}["bifrost"]

    assert component["status"] == "degraded"
    assert component["metadata"]["live_health"] == "down"
    assert component["metadata"]["health_source"] == "explicit"
    assert component["metadata"]["health_error"] == "probe_failed"
    assert "healthz" not in repr(body)
