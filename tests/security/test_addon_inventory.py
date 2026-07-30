"""Runtime add-on inventory is canonical, scoped, cached, and secret-free."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

import boltrig.addons as addon_module
from boltrig.addons import Addon, AddonError, AddonRequirement
from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.models import AdapterRecord
from boltrig.store import InMemoryStore

T = "addon-tenant"
H = {
    "x-boltrig-tenant": T,
    "x-boltrig-subject": "member",
    "x-boltrig-role": "member",
    "x-boltrig-workspace": "workspace-a",
}


class _Adapter:
    def __init__(self, adapter_id: str) -> None:
        self.id = adapter_id


class _ScopedStatus:
    def __init__(self, snapshots: dict[tuple[str, str | None], object]) -> None:
        self.snapshots = snapshots
        self.reads: list[tuple[str, str | None]] = []

    def cached_snapshot(
        self, *, tenant_id: str, workspace_id: str | None
    ) -> object:
        self.reads.append((tenant_id, workspace_id))
        return self.snapshots.get((tenant_id, workspace_id))

    async def snapshot(self, **_scope) -> dict:
        raise AssertionError("add-on inventory must never initiate a status probe")


def _record(tenant_id: str, adapter_id: str) -> AdapterRecord:
    return AdapterRecord(
        id=adapter_id,
        tenant_id=tenant_id,
        version="1.0.0",
        runtime="script",
        source="builtin",
        module_ref="private.module.path",
        activated=True,
    )


def _client(kernel: Kernel, status: object | None = None) -> TestClient:
    return TestClient(
        create_app(kernel, platform={"status": status} if status is not None else {})
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-26")
async def test_inventory_uses_exact_registry_activation_and_closed_aggregation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    addons = (
        Addon(name="z-inactive", version="7.0.1"),
        Addon(name="a-free", version="1.2.3"),
        Addon(
            name="b-ready",
            version="2.0.0",
            requirements=(
                AddonRequirement(
                    id="credential-ready",
                    kind="credential_ref",
                    ref="private-ready-credential",
                ),
            ),
        ),
        Addon(
            name="c-missing",
            version="3.0.0",
            requirements=(
                AddonRequirement(
                    id="environment-missing",
                    kind="environment",
                    ref="PRIVATE_MISSING_SETTING",
                ),
            ),
        ),
        Addon(
            name="d-unavailable",
            version="4.0.0",
            requirements=(
                AddonRequirement(
                    id="adapter-not-loaded",
                    kind="adapter",
                    ref="stored-only",
                ),
            ),
        ),
        Addon(
            name="e-unverified",
            version="5.0.0",
            requirements=(
                AddonRequirement(
                    id="component-unknown",
                    kind="component",
                    ref="unknown-component",
                ),
            ),
        ),
        Addon(
            name="f-degraded",
            version="6.0.0",
            requirements=(
                AddonRequirement(
                    id="optional-adapter-degraded",
                    kind="adapter",
                    ref="degraded-adapter",
                    required=False,
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        addon_module, "_REGISTRY", {addon.name: addon for addon in addons}
    )
    monkeypatch.setenv(
        "BOLTRIG_ADDONS",
        ",".join(addon.name for addon in addons if addon.name != "z-inactive"),
    )
    monkeypatch.delenv("PRIVATE_MISSING_SETTING", raising=False)

    store = InMemoryStore()
    await store.set_credential_ref(
        T, "private-ready-credential", {"value": "NEVER-SERIALIZE"}
    )
    await store.upsert_adapter(_record(T, "stored-only"))
    await store.upsert_adapter(_record(T, "degraded-adapter"))
    kernel = Kernel(store)
    kernel.loader.register(T, _Adapter("degraded-adapter"))  # type: ignore[arg-type]
    kernel.loader._health[(T, "degraded-adapter")] = "degraded"
    status = _ScopedStatus(
        {
            (T, "workspace-a"): {
                "components": [{"id": "unknown-component", "status": "mystery"}]
            }
        }
    )

    async def resolver(request: Request) -> Principal:
        if request.headers.get("authorization") != "Bearer member-session":
            raise HTTPException(status_code=401, detail="invalid session")
        return Principal(
            tenant_id=T,
            subject="member",
            role="member",
            active_workspace_id="workspace-a",
        )

    client = TestClient(
        create_app(
            kernel,
            principal_resolver=resolver,
            platform={"status": status},
        )
    )
    assert client.get("/v1/addons").status_code == 401
    response = client.get(
        "/v1/addons", headers={"authorization": "Bearer member-session"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == {"tenant_id": T, "workspace_id": "workspace-a"}
    assert [item["id"] for item in body["addons"]] == sorted(
        addon.name for addon in addons
    )
    assert [item["version"] for item in body["addons"]] == [
        "1.2.3",
        "2.0.0",
        "3.0.0",
        "4.0.0",
        "5.0.0",
        "6.0.0",
        "7.0.1",
    ]
    by_id = {item["id"]: item for item in body["addons"]}
    assert by_id["a-free"]["configuration"]["status"] == "not_required"
    assert by_id["a-free"]["runtime"] == {"status": "ready", "reason": None}
    assert by_id["b-ready"]["runtime"] == {"status": "ready", "reason": None}
    assert by_id["c-missing"]["runtime"] == {
        "status": "unavailable",
        "reason": "not_configured",
    }
    assert by_id["d-unavailable"]["runtime"] == {
        "status": "unavailable",
        "reason": "not_loaded",
    }
    assert by_id["e-unverified"]["runtime"] == {
        "status": "unverified",
        "reason": "health_unverified",
    }
    assert by_id["f-degraded"]["runtime"] == {
        "status": "degraded",
        "reason": "health_degraded",
    }
    assert by_id["z-inactive"]["activation"] == "inactive"
    assert by_id["z-inactive"]["runtime"] == {"status": "inactive", "reason": None}
    requirement_states = {
        requirement["status"]
        for addon in body["addons"]
        for requirement in addon["configuration"]["requirements"]
    }
    assert requirement_states == {
        "ready",
        "missing",
        "degraded",
        "unavailable",
        "unverified",
    }
    assert status.reads == [(T, "workspace-a")]
    assert "NEVER-SERIALIZE" not in response.text

    monkeypatch.setenv("BOLTRIG_ADDONS", "not-registered")
    with pytest.raises(AddonError, match="unregistered"):
        client.get("/v1/addons", headers={"authorization": "Bearer member-session"})


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-26")
async def test_inventory_evidence_is_tenant_and_workspace_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    addon = Addon(
        name="scoped",
        version="1.0.0",
        requirements=(
            AddonRequirement(id="adapter", kind="adapter", ref="same-adapter"),
            AddonRequirement(
                id="credential", kind="credential_ref", ref="same-credential"
            ),
            AddonRequirement(id="component", kind="component", ref="same-component"),
        ),
    )
    monkeypatch.setattr(addon_module, "_REGISTRY", {addon.name: addon})
    monkeypatch.setenv("BOLTRIG_ADDONS", addon.name)
    store = InMemoryStore()
    await store.upsert_adapter(_record("other-tenant", "same-adapter"))
    await store.set_credential_ref(
        "other-tenant", "same-credential", {"value": "OTHER-TENANT-SECRET"}
    )
    kernel = Kernel(store)
    kernel.loader.register(
        "other-tenant", _Adapter("same-adapter")  # type: ignore[arg-type]
    )
    kernel.loader._health[("other-tenant", "same-adapter")] = "ok"
    status = _ScopedStatus(
        {
            (T, "workspace-b"): {
                "components": [{"id": "same-component", "status": "ok"}]
            }
        }
    )
    client = _client(kernel, status)

    view = client.get("/v1/addons", headers=H).json()["addons"][0]

    requirements = {
        requirement["id"]: requirement
        for requirement in view["configuration"]["requirements"]
    }
    assert requirements["adapter"]["status"] == "missing"
    assert requirements["credential"]["status"] == "missing"
    assert requirements["component"]["status"] == "unverified"
    assert status.reads == [(T, "workspace-a")]

    await store.upsert_adapter(_record(T, "same-adapter"))
    await store.set_credential_ref(
        T, "same-credential", {"value": "OWN-TENANT-SECRET"}
    )
    kernel.loader.register(T, _Adapter("same-adapter"))  # type: ignore[arg-type]
    kernel.loader._health[(T, "same-adapter")] = "ok"
    status.snapshots[(T, "workspace-a")] = {
        "components": [{"id": "same-component", "status": "ok"}]
    }
    ready = client.get("/v1/addons", headers=H).json()["addons"][0]
    assert ready["runtime"] == {"status": "ready", "reason": None}


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-26")
async def test_inventory_redacts_private_declarations_and_evaluator_faults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets = {
        "PRIVATE HARNESS TEXT",
        "PRIVATE_ENVIRONMENT_NAME",
        "private-credential-id",
        "private-adapter-id",
        "private-component-id",
        "PRIVATE_ENVIRONMENT_VALUE",
        "PRIVATE EVALUATOR EXCEPTION",
    }
    addon = Addon(
        name="faulted",
        version="9.0.0",
        harness="PRIVATE HARNESS TEXT",
        adapter_id="private-adapter-id",
        requirements=(
            AddonRequirement(
                id="adapter-check", kind="adapter", ref="private-adapter-id"
            ),
            AddonRequirement(
                id="credential-check",
                kind="credential_ref",
                ref="private-credential-id",
            ),
            AddonRequirement(
                id="environment-check",
                kind="environment",
                ref="PRIVATE_ENVIRONMENT_NAME",
            ),
            AddonRequirement(
                id="component-check",
                kind="component",
                ref="private-component-id",
            ),
        ),
    )
    monkeypatch.setattr(addon_module, "_REGISTRY", {addon.name: addon})
    monkeypatch.setenv("BOLTRIG_ADDONS", addon.name)
    monkeypatch.setenv("PRIVATE_ENVIRONMENT_NAME", "PRIVATE_ENVIRONMENT_VALUE")

    class _FaultStore(InMemoryStore):
        async def get_adapter(self, tenant_id: str, adapter_id: str):
            raise RuntimeError("PRIVATE EVALUATOR EXCEPTION")

        async def has_credential_ref(self, tenant_id: str, cred_id: str) -> bool:
            raise RuntimeError("PRIVATE EVALUATOR EXCEPTION")

    class _FaultStatus:
        def cached_snapshot(self, **_scope):
            raise RuntimeError("PRIVATE EVALUATOR EXCEPTION")

    response = _client(Kernel(_FaultStore()), _FaultStatus()).get(
        "/v1/addons", headers=H
    )

    assert response.status_code == 200
    view = response.json()["addons"][0]
    requirements = view["configuration"]["requirements"]
    faulted = [
        requirement
        for requirement in requirements
        if requirement["id"] != "environment-check"
    ]
    assert all(requirement["status"] == "unavailable" for requirement in faulted)
    assert all(
        requirement["reason"] == "evidence_unavailable"
        for requirement in faulted
    )
    assert next(
        requirement
        for requirement in requirements
        if requirement["id"] == "environment-check"
    )["status"] == "ready"
    serialized = json.dumps(response.json())
    assert all(secret not in serialized for secret in secrets)
