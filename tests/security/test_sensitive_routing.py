"""Sensitive data routes only to local endpoints (SEC-12, US-PRIV-01).

A misroute (sensitive data to a hosted endpoint) is blocked and audited; a local
endpoint is accepted; a configured sensitive endpoint is substituted; standard
data is unconstrained. The guard is also enforced on the spawn path.
"""

import pytest

from boltrig.fleet import build_spawner
from boltrig.fleet.model_router import select_model_endpoint
from boltrig.kernel import Kernel
from boltrig.kernel.audit import AuditWriter
from boltrig.models import (
    AgentCapability,
    GrantSet,
    InvocationContext,
    ModelEndpoint,
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
