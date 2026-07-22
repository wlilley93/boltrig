"""Sensitive data routes only to local endpoints (SEC-12, US-PRIV-01).

A misroute (sensitive data to a hosted endpoint) is blocked and audited; a local
endpoint is accepted; a configured sensitive endpoint is substituted; standard
data is unconstrained. The guard is also enforced on the spawn path.
"""

import pytest

from boltrig.fleet import build_spawner
from boltrig.fleet.model_router import select_model_endpoint
from boltrig.fleet.spawn import Spawner
from boltrig.kernel import Kernel
from boltrig.kernel.audit import AuditWriter
from boltrig.models import (
    AgentCapability,
    AiConfig,
    GrantSet,
    InvocationContext,
    ModelEndpoint,
    Organisation,
    SensitiveDataMisrouted,
    Skill,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"


async def _store_with_endpoints() -> InMemoryStore:
    s = InMemoryStore()
    await s.upsert_model_endpoint(
        ModelEndpoint(id="hosted", tenant_id=T, kind="anthropic", model="claude",
                      data_class="standard")
    )
    await s.upsert_model_endpoint(
        ModelEndpoint(id="local", tenant_id=T, kind="vllm", model="local-llm",
                      data_class="sensitive")
    )
    return s


@pytest.mark.security
@pytest.mark.invariant("SEC-12")
async def test_sensitive_data_blocked_from_hosted_and_audited():
    s = await _store_with_endpoints()
    audit = AuditWriter(s)
    with pytest.raises(SensitiveDataMisrouted):
        await select_model_endpoint(s, T, "hosted", sensitive=True, audit=audit)
    events = await s.audit_query(T)
    assert events[-1].status == "sensitive_data_misrouted"


@pytest.mark.security
@pytest.mark.invariant("SEC-12")
async def test_sensitive_data_routes_to_local_endpoint():
    s = await _store_with_endpoints()
    ep = await select_model_endpoint(s, T, "local", sensitive=True)
    assert ep.id == "local" and ep.data_class == "sensitive"


@pytest.mark.security
async def test_sensitive_substitutes_configured_local_endpoint():
    s = await _store_with_endpoints()
    ep = await select_model_endpoint(
        s, T, "hosted", sensitive=True, sensitive_endpoint_id="local"
    )
    assert ep.id == "local"


@pytest.mark.security
async def test_standard_data_uses_its_endpoint():
    s = await _store_with_endpoints()
    ep = await select_model_endpoint(s, T, "hosted", sensitive=False)
    assert ep.id == "hosted"


@pytest.mark.security
@pytest.mark.invariant("SEC-12")
async def test_spawn_blocks_sensitive_on_hosted_capability():
    s = await _store_with_endpoints()
    s.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await s.upsert_capability(
        AgentCapability("hosted-worker", T, "claude-api", ["*"], 2, True, "standard",
                        model_endpoint="hosted")
    )
    await s.upsert_skill(
        Skill(id="analysis/x", tenant_id=T, version="1.0.0", prompt_fragment="p",
              tool_grants=[], context_requirements={})
    )
    spawner = build_spawner(Kernel(s))
    ctx = InvocationContext(
        tenant_id=T, grants=GrantSet.of(["*"]), actor="head",
        extra={"data_class": "sensitive"},
    )
    with pytest.raises(SensitiveDataMisrouted):
        await spawner.spawn(T, "handle sensitive record", ["analysis/x"], {}, ctx)


@pytest.mark.security
@pytest.mark.invariant("SEC-12")
async def test_sensitive_ignores_external_ai_config_and_routes_local(monkeypatch):
    # openai/claude-api are legacy lanes (decision 0012): enable them explicitly
    # so the routing assertions exercise the real runtimes.
    monkeypatch.setenv("BOLTRIG_ENABLE_LEGACY_RUNTIMES", "1")
    # An AI config ([2026] VJS-COUNTY 8, D5) that names an EXTERNAL provider must NOT
    # move sensitive data off the local endpoint: for a sensitive call the config's
    # provider/model/base_url are ignored and the local sensitive endpoint wins
    # (SEC-12 residency composes with COUNTY 5 - a config narrows/redirects a standard
    # route, never widens a sensitive one). The SAME config DOES route a NON-sensitive
    # call, proving the guard is what suppresses it, not a broken config.
    s = await _store_with_endpoints()
    s.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await s.create_org(
        Organisation(id=T, name="Acme", slug="acme", allow_own_ai_keys=True)
    )
    await s.set_credential_ref(T, "cred-user", {"secret": "sk-user"})
    await s.set_ai_config(AiConfig(
        tenant_id=T, level="user", scope_id="u1",
        provider="claude", model="claude-remote", credential_ref="cred-user",
        base_url="http://external/v1",
    ))
    # The capability's own endpoint is the LOCAL sensitive one (an openai-shaped vllm).
    cap = AgentCapability("worker", T, "openai", ["*"], 2, True, "standard",
                          model_endpoint="local")
    spawner = Spawner(Kernel(s))

    # SENSITIVE: the config is ignored - runtime stays the capability default and the
    # endpoint stays the local sensitive model, never the external claude route.
    sens_ctx = InvocationContext(tenant_id=T, actor="worker", on_behalf_of="u1",
                                 extra={"data_class": "sensitive"})
    rt = await spawner._runtime_for(T, cap, sens_ctx)
    assert rt.runtime == "openai"                 # NOT 'claude-api' from the config
    assert rt.endpoint.model == "local-llm"       # NOT 'claude-remote' from the config
    assert rt.endpoint.data_class == "sensitive"  # the local residency endpoint

    # NON-sensitive: the very same config now DOES route (provider + model applied),
    # so the suppression above is the residency guard, not an inert config.
    std_ctx = InvocationContext(tenant_id=T, actor="worker", on_behalf_of="u1")
    rt2 = await spawner._runtime_for(T, cap, std_ctx)
    assert rt2.runtime == "claude-api" and rt2.endpoint.model == "claude-remote"
