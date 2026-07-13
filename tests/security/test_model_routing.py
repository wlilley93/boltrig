"""Model / provider ROUTING from an AI config ([2026] VJS-COUNTY 8, D5).

The AI-key resolver already picks the SEALED key by org/workspace/user. This suite
proves it now also drives WHICH runtime + model + endpoint a call uses:

FR-AIKEY-03 : a resolved (non-default) ai_config's provider selects the RUNTIME and
              its model / base_url override the endpoint, so a config routes the call
              - while a tenant with NO config dispatches byte-for-byte as before (the
              capability's env-default runtime + endpoint model), and an UNKNOWN
              provider degrades to that default rather than crashing the run (P9).

The SEC-12 residency composition (a sensitive call ignores an external config and
routes local) is proven in tests/security/test_sensitive_routing.py.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from boltrig.config import apply_manifest, load_manifest
from boltrig.fleet.runtime import runtime_for_provider
from boltrig.fleet.spawn import Spawner
from boltrig.identity import resolve_ai_key
from boltrig.kernel import Kernel
from boltrig.models import (
    AgentCapability,
    AiConfig,
    GrantSet,
    InvocationContext,
    ModelEndpoint,
    Organisation,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"


def _run(coro):
    return asyncio.run(coro)


async def _store(*, allow_own: bool = True) -> InMemoryStore:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.create_org(
        Organisation(id=T, name="Acme", slug="acme", allow_own_ai_keys=allow_own)
    )
    return store


async def _put_config(store, *, provider, model, base_url=None, key="sk-user") -> None:
    await store.set_credential_ref(T, "cred-user", {"secret": key})
    await store.set_ai_config(AiConfig(
        tenant_id=T, level="user", scope_id="u1",
        provider=provider, model=model, credential_ref="cred-user", base_url=base_url,
    ))


async def _capability(store, *, runtime="claude-api") -> AgentCapability:
    await store.upsert_model_endpoint(
        ModelEndpoint(id="ep", tenant_id=T, kind="anthropic", model="claude",
                      base_url="http://default/v1", data_class="standard")
    )
    return AgentCapability("w", T, runtime, ["*"], 2, True, "standard",
                           model_endpoint="ep")


def _ctx(**extra) -> InvocationContext:
    return InvocationContext(tenant_id=T, actor="w", on_behalf_of="u1", extra=extra)


# --- FR-AIKEY-03: provider selects the runtime + model/base_url the endpoint ------
@pytest.mark.invariant("FR-AIKEY-03")
def test_no_config_dispatches_the_env_default_runtime_and_model():
    # Backward-compat: with NO ai_config the runtime + endpoint model are the
    # capability's env default, byte-for-byte as before the routing seam existed.
    async def go():
        store = await _store()
        cap = await _capability(store, runtime="claude-api")
        rt = await Spawner(Kernel(store))._runtime_for(T, cap, _ctx())
        assert rt.runtime == "claude-api"           # capability's own runtime
        assert rt.endpoint is not None
        assert rt.endpoint.model == "claude"        # the endpoint's own model
        assert rt.endpoint.base_url == "http://default/v1"

    _run(go())


@pytest.mark.invariant("FR-AIKEY-03")
def test_ai_config_provider_and_model_select_runtime_and_endpoint():
    # A resolved user config (provider=openai) selects the OpenAI runtime and pins the
    # endpoint to the config's model + base_url - not the capability's claude default.
    async def go():
        store = await _store()
        cap = await _capability(store, runtime="claude-api")
        await _put_config(store, provider="openai", model="gpt-4o",
                          base_url="http://byo/v1", key="sk-user")
        rt = await Spawner(Kernel(store))._runtime_for(T, cap, _ctx())
        assert rt.runtime == "openai"               # provider selected the runtime
        assert rt.endpoint.model == "gpt-4o"        # config model pins the endpoint
        assert rt.endpoint.base_url == "http://byo/v1"   # config base_url routes it
        assert rt._api_key() == "sk-user"           # the sealed key still wired in

    _run(go())


@pytest.mark.invariant("FR-AIKEY-03")
def test_config_without_base_url_keeps_the_endpoint_host():
    # base_url is OPTIONAL: a config that names only provider+model routes the runtime
    # + model but keeps the resolved endpoint's own host (no base_url override).
    async def go():
        store = await _store()
        cap = await _capability(store, runtime="claude-api")
        await _put_config(store, provider="openai", model="gpt-4o", base_url=None)
        rt = await Spawner(Kernel(store))._runtime_for(T, cap, _ctx())
        assert rt.runtime == "openai" and rt.endpoint.model == "gpt-4o"
        assert rt.endpoint.base_url == "http://default/v1"  # endpoint host retained

    _run(go())


@pytest.mark.invariant("FR-AIKEY-03")
def test_unknown_provider_degrades_to_the_env_default_without_crashing():
    # A config naming an UNKNOWN provider must not crash the run: routing degrades to
    # the capability's default runtime + endpoint model, while the sealed KEY still
    # resolves (the key seam is independent of the routing degrade).
    async def go():
        store = await _store()
        cap = await _capability(store, runtime="claude-api")
        await _put_config(store, provider="frobnicator", model="whatever",
                          base_url="http://x", key="sk-user")
        rt = await Spawner(Kernel(store))._runtime_for(T, cap, _ctx())
        assert rt.runtime == "claude-api"           # degraded to the default runtime
        assert rt.endpoint.model == "claude"        # endpoint model NOT overridden
        assert rt.endpoint.base_url == "http://default/v1"
        assert rt._api_key() == "sk-user"           # key seam unaffected

        # The mapping itself is the fail-safe: known providers map, unknown -> None
        # (the degrade signal), and it is case-insensitive.
        assert runtime_for_provider("OpenAI") == "openai"
        assert runtime_for_provider("bifrost") == "openai"
        assert runtime_for_provider("cerebras") == "openai"
        assert runtime_for_provider("fireworks") == "openai"
        assert runtime_for_provider("runpod") == "openai"
        assert runtime_for_provider("anthropic") == "claude-api"
        assert runtime_for_provider("hermes") == "hermes"
        assert runtime_for_provider("frobnicator") is None
        assert runtime_for_provider(None) is None

        # And the resolver carried the selection through (provider/model/base_url).
        r = await resolve_ai_key(store, T, workspace_id=None, user_id="u1")
        assert r.provider == "frobnicator" and r.model == "whatever"
        assert r.base_url == "http://x"

    _run(go())


@pytest.mark.invariant("FR-GW-02")
def test_model_profile_selects_provider_model_and_route(monkeypatch):
    async def go():
        store = await _store()
        cap = await _capability(store, runtime="claude-api")
        profiles = {
            "code": {
                "provider": "bifrost",
                "model": "kimi-k2.7",
                "base_url": "http://bifrost:8080/v1",
            }
        }
        monkeypatch.setenv("BOLTRIG_MODEL_PROFILES", json.dumps(profiles))
        ctx = _ctx(model_profile="code")

        rt = await Spawner(Kernel(store))._runtime_for(T, cap, ctx)

        assert rt.runtime == "openai"
        assert rt.endpoint.model == "kimi-k2.7"
        assert rt.endpoint.base_url == "http://bifrost:8080/v1"
        assert rt.model_route == {
            "profile": "code",
            "provider": "bifrost",
            "model": "kimi-k2.7",
            "runtime": "openai",
            "base_url": "http://bifrost:8080/v1",
        }

    _run(go())


@pytest.mark.invariant("FR-GW-02")
@pytest.mark.invariant("SEC-12")
def test_model_profile_is_ignored_for_sensitive_data(monkeypatch):
    async def go():
        store = await _store()
        await store.upsert_model_endpoint(
            ModelEndpoint(
                id="local",
                tenant_id=T,
                kind="vllm",
                model="local-sensitive",
                base_url="http://local/v1",
                data_class="sensitive",
            )
        )
        cap = AgentCapability(
            "w", T, "openai", ["*"], 2, True, "standard", model_endpoint="local"
        )
        profiles = {
            "deep": {
                "provider": "anthropic",
                "model": "claude-remote",
                "base_url": "http://external/v1",
            }
        }
        monkeypatch.setenv("BOLTRIG_MODEL_PROFILES", json.dumps(profiles))
        ctx = _ctx(model_profile="deep", data_class="sensitive")

        rt = await Spawner(Kernel(store))._runtime_for(T, cap, ctx)

        assert rt.runtime == "openai"
        assert rt.endpoint.model == "local-sensitive"
        assert rt.endpoint.base_url == "http://local/v1"
        assert not hasattr(rt, "model_route")

    _run(go())


@pytest.mark.invariant("FR-GW-02")
@pytest.mark.invariant("FR-GW-04")
def test_manifest_model_profiles_feed_runtime_resolver(monkeypatch, tmp_path):
    async def go():
        monkeypatch.delenv("BOLTRIG_MODEL_PROFILES", raising=False)
        monkeypatch.delenv("BOLTRIG_MODEL_GATEWAY_URL", raising=False)
        monkeypatch.delenv("BOLTRIG_MODEL_GATEWAY_HEALTH", raising=False)
        monkeypatch.delenv("BOLTRIG_MODEL_GATEWAY_HEALTH_PATH", raising=False)
        monkeypatch.delenv("BOLTRIG_MODEL_GATEWAY_HEALTH_TIMEOUT", raising=False)
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(
            """
organisation: Acme
tenant_id: acme
models:
  endpoints:
    - id: standard
      kind: anthropic
      model: claude
      data_class: standard
runtimes:
  gateway:
    base_url: http://bifrost:8080/v1
    cache_ttl_seconds: 900
    health:
      enabled: true
      path: /health
      timeout: 0.25
    model_profiles:
      code:
        provider: bifrost
        model: kimi-k2.7
        base_url: http://bifrost:8080/v1
""",
            encoding="utf-8",
        )
        kernel = Kernel(InMemoryStore())
        await apply_manifest(kernel, load_manifest(str(manifest_path)),
                             load_builtin_adapters=False)
        cap = AgentCapability(
            "w", T, "claude-api", ["*"], 2, True, "standard",
            model_endpoint="standard",
        )

        rt = await Spawner(kernel)._runtime_for(T, cap, _ctx(model_profile="code"))

        assert rt.runtime == "openai"
        assert rt.endpoint.model == "kimi-k2.7"
        assert rt.endpoint.base_url == "http://bifrost:8080/v1"
        assert rt.model_route["profile"] == "code"
        assert os.environ["BOLTRIG_MODEL_GATEWAY_HEALTH"] == "1"
        assert os.environ["BOLTRIG_MODEL_GATEWAY_HEALTH_PATH"] == "/health"
        assert os.environ["BOLTRIG_MODEL_GATEWAY_HEALTH_TIMEOUT"] == "0.25"

    _run(go())
