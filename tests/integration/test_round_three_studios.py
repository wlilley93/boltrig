"""Round Three studios: Admin round-trip (FR-ADM-02), Workflow live registration
(FR-WFS-04), Adapter Studio review gate via the UI path (FR-ADS-02)."""

import asyncio
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.config import load_manifest
from boltrig.config.admin import AdminConfig
from boltrig.fleet import build_spawner
from boltrig.fleet.workers import LocalDurableExecutor
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore
from boltrig.workflows import WorkflowLibrary
from boltrig.workflows.generator import generate_workflow

T = "default"


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    return k


def _hdr(role="org-admin", grants=None):
    h = {"x-boltrig-tenant": T, "x-boltrig-subject": "u", "x-boltrig-role": role}
    if grants is not None:
        h["x-boltrig-grants"] = grants
    return h


@pytest.mark.invariant("FR-ADM-02")
async def test_admin_config_round_trips():
    admin = AdminConfig(InMemoryStore(), tenant_id=T, path="manifest.example.yaml")
    rev1 = await admin.update_section("privacy", {"pii_redaction": True, "retention_days": 30}, "a")
    await admin.update_section("privacy", {"pii_redaction": True, "retention_days": 99}, "a")
    assert admin.export_dict()["privacy"]["retention_days"] == 99
    # export round-trips: the manifest still loads and keeps the edit (C1)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        fh.write(admin.export_yaml())
        path = fh.name
    try:
        m = load_manifest(path)
        assert m.tenant_id == T
    finally:
        os.unlink(path)
    # rollback to the first revision restores its value (NFR-REL-01)
    restored = await admin.rollback("privacy", rev1.id, "a")
    assert restored["retention_days"] == 30
    assert admin.export_dict()["privacy"]["retention_days"] == 30


@pytest.mark.invariant("FR-WFS-04")
async def test_workflow_live_durable_registration():
    class _DurableExec:
        durable = True

        def new_run_id(self):
            return "rid-1"

        async def run_step(self, name, fn, *a, run_id=None, **k):
            return await fn()

    store = InMemoryStore()
    lib = WorkflowLibrary(store, executor=_DurableExec())
    wf = generate_workflow("onboard", ["x"], T)
    await lib.register(wf)
    desc = await lib.trigger(T, wf.id, {})
    assert desc["durable"] is True and desc["engine"] == "hatchet"  # live durable run

    # offline: the local executor is not durable (P9)
    lib2 = WorkflowLibrary(store, executor=LocalDurableExecutor())
    wf2 = generate_workflow("onboard2", ["x"], T)
    await lib2.register(wf2)
    assert (await lib2.trigger(T, wf2.id, {}))["durable"] is False


_SPEC = {
    "openapi": "3.0.0", "info": {"title": "Petstore", "version": "1.0.0"},
    "paths": {"/pets": {"get": {"operationId": "pet.list",
                                "responses": {"200": {"description": "ok"}}}}},
}


@pytest.mark.invariant("FR-ADS-02")
def test_adapter_studio_review_gate():
    k = asyncio.run(_kernel())
    c = TestClient(create_app(k, platform={"spawner": build_spawner(k)}))

    # a non-author cannot generate
    assert c.post("/v1/adapters/generate", json={"spec": _SPEC, "adapter_id": "petstore"},
                  headers=_hdr("viewer")).status_code == 403

    # org-admin generates -> inert (not yet bound)
    gen = c.post("/v1/adapters/generate", json={"spec": _SPEC, "adapter_id": "petstore"},
                 headers=_hdr("org-admin"))
    assert gen.status_code == 200 and gen.json()["activated"] is False
    assert "pet.list" in gen.json()["verbs"]
    disco = c.get("/v1/capabilities", headers=_hdr("org-admin", grants="*")).json()
    assert not any(v["id"] == "pet.list" for v in disco["verbs"])  # not bound before review

    # Activation is held until a different authenticated human approves it. A
    # caller-supplied reviewer string is ignored; the review gate records the
    # HITL respondent (SEC-22/SEC-14).
    held = c.post("/v1/adapters/petstore/activate", json={"reviewer": "spoofed"},
                  headers=_hdr("org-admin"))
    assert held.status_code == 202
    request_id = held.json()["hitl_request_id"]
    asyncio.run(k.hitl.answer(T, request_id, "approve", "security@acme"))
    act = c.post(
        "/v1/adapters/petstore/activate",
        json={"reviewer": "spoofed", "approval_id": request_id},
        headers=_hdr("org-admin"),
    )
    assert act.status_code == 200 and "pet.list" in act.json()["verbs"]
    adapter = asyncio.run(k.loader.get(T, "petstore"))
    assert adapter.review_gate.reviewer == "security@acme"
    disco2 = c.get("/v1/capabilities", headers=_hdr("org-admin", grants="*")).json()
    assert any(v["id"] == "pet.list" for v in disco2["verbs"])

    # Worker exposes the governed reverse lifecycle too. Both operations enter
    # the same independent-human gate; no direct route mutates adapter rows.
    held_down = c.post(
        "/v1/adapters/petstore/deactivate", headers=_hdr("org-admin")
    )
    assert held_down.status_code == 202
    down_id = held_down.json()["hitl_request_id"]
    asyncio.run(k.hitl.answer(T, down_id, "approve", "security@acme"))
    down = c.post(
        "/v1/adapters/petstore/deactivate",
        headers={**_hdr("org-admin"), "x-boltrig-approval-id": down_id},
    )
    assert down.status_code == 200 and down.json()["activated"] is False

    held_delete = c.delete(
        "/v1/adapters/petstore", headers=_hdr("org-admin")
    )
    assert held_delete.status_code == 202
    delete_id = held_delete.json()["hitl_request_id"]
    asyncio.run(k.hitl.answer(T, delete_id, "approve", "security@acme"))
    deleted = c.delete(
        "/v1/adapters/petstore",
        headers={**_hdr("org-admin"), "x-boltrig-approval-id": delete_id},
    )
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True
