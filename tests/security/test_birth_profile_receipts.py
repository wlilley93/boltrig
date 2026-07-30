"""Redacted cross-process birth-profile observation contract."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from boltrig.config.birth_profile import (
    birth_profile_view,
    instance_identity,
    make_birth_profile_receipt,
)
from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.models import utcnow
from boltrig.store import InMemoryStore

T = "birth-profile-tenant"


def _receipt(
    process_kind: str,
    *,
    observed_at=None,
    addons=(),
    codex_identity: str = "cp_" + "a" * 24,
    sensitive: str | None = "local-sensitive",
):
    return make_birth_profile_receipt(
        tenant_id=T,
        process_kind=process_kind,
        manifest={
            "tenant_id": T,
            "policy": {"generation": 7},
        },
        addons=addons,
        codex_config={
            "trusted": True,
            "provider": object(),
            "receipt_identity": codex_identity,
        },
        sensitive_endpoint_id=sensitive,
        boot_identity_token=f"boot-{process_kind}",
        observed_at=observed_at or utcnow(),
        ttl_seconds=300,
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-30")
async def test_projection_compares_every_instance_to_a_reference_without_claiming_parity():
    store = InMemoryStore()
    api = _receipt("api")
    fleet_a = replace(
        api,
        process_kind="fleet",
        instance_identity="bi_" + "b" * 24,
    )
    fleet_b = replace(
        api,
        process_kind="fleet",
        instance_identity="bi_" + "c" * 24,
        addon_set_identity="as_" + "d" * 24,
    )
    hatchet = replace(
        api,
        process_kind="hatchet",
        instance_identity="bi_" + "e" * 24,
    )
    for receipt in (api, fleet_a, fleet_b, hatchet):
        await store.upsert_birth_profile_receipt(receipt)

    view = await birth_profile_view(store, T, now=api.observed_at)

    assert view["status"] == "observed_mismatch"
    assert view["reference"]["source_process"] == "api"
    assert view["reference"]["basis"] == "latest_api_startup_receipt"
    assert "desired" not in view
    assert view["reference"]["liveness_claimed"] is False
    rows = view["observations"]
    assert len([row for row in rows if row["process_kind"] == "fleet"]) == 2
    assert any(row["matches_reference"] is True for row in rows if row["process_kind"] == "fleet")
    mismatched = next(row for row in rows if row["instance_identity"] == fleet_b.instance_identity)
    assert mismatched["matches_reference"] is False
    assert mismatched["mismatches"] == ["addon_set_identity"]
    assert all(row["liveness_claimed"] is False for row in rows)
    assert view["summary"]["retained_instance_count"] == 4
    assert view["summary"]["replica_coverage_claimed"] is False


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-30")
async def test_stale_and_absent_processes_are_explicitly_unavailable():
    store = InMemoryStore()
    observed = utcnow() - timedelta(minutes=10)
    api = _receipt("api", observed_at=observed)
    fleet = replace(
        api,
        process_kind="fleet",
        instance_identity="bi_" + "b" * 24,
    )
    await store.upsert_birth_profile_receipt(api)
    await store.upsert_birth_profile_receipt(fleet)

    view = await birth_profile_view(store, T, now=utcnow())

    assert view["status"] == "process_kind_unavailable"
    assert view["reference"]["status"] == "stale_startup_liveness_unknown"
    rows = {row["process_kind"]: row for row in view["observations"]}
    assert rows["api"]["evidence_state"] == "stale_startup_liveness_unknown"
    assert rows["fleet"]["evidence_state"] == "stale_startup_liveness_unknown"
    assert rows["hatchet"] == {
        "process_kind": "hatchet",
        "instance_identity": None,
        "evidence_state": "unavailable",
        "reason": "no_startup_receipt",
        "matches_reference": None,
        "mismatches": [],
        "manifest_generation": None,
        "addon_set_identity": None,
        "codex_provider_identity": None,
        "codex_provider_state": "unavailable",
        "sensitive_role_identity": None,
        "sensitive_role_state": "unavailable",
        "receipt_kind": None,
        "observed_at": None,
        "expires_at": None,
        "liveness_claimed": False,
    }


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-30")
async def test_route_is_tenant_scoped_and_returns_only_opaque_identities():
    store = InMemoryStore()
    secrets = {
        "url": "https://private.example.test/model",
        "path": "/srv/private/codex",
        "owner": "owner@example.test",
        "credential_ref": "MODEL_GATEWAY_KEY",
        "secret": "do-not-return",
    }
    addon = SimpleNamespace(
        name="opbox",
        version="1.0.0",
        harness="private harness text",
    )
    receipt = make_birth_profile_receipt(
        tenant_id=T,
        process_kind="api",
        manifest=secrets,
        addons=(addon,),
        codex_config={
            "trusted": True,
            "provider": object(),
            "stack_root": secrets["path"],
            "receipt_identity": "cp_" + "a" * 24,
        },
        sensitive_endpoint_id="private-local-endpoint",
        boot_identity_token="private-boot-token",
    )
    await store.upsert_birth_profile_receipt(receipt)
    await store.upsert_birth_profile_receipt(
        replace(
            receipt,
            tenant_id="other",
            instance_identity="bi_" + "f" * 24,
        )
    )

    async def resolver(request: Request) -> Principal:
        if request.headers.get("authorization") != "Bearer operator-session":
            raise HTTPException(status_code=401, detail="invalid session")
        return Principal(tenant_id=T, subject="operator", role="org-admin")

    client = TestClient(create_app(Kernel(store), principal_resolver=resolver))

    assert client.get("/v1/birth-profile").status_code == 401
    response = client.get(
        "/v1/birth-profile",
        headers={"authorization": "Bearer operator-session"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == T
    serialized = json.dumps(body, sort_keys=True)
    for prohibited in (
        *secrets.values(),
        addon.name,
        addon.version,
        addon.harness,
        "private-local-endpoint",
        "private-boot-token",
        "other",
    ):
        assert prohibited not in serialized
    assert receipt.manifest_generation in serialized
    assert receipt.codex_provider_identity in serialized


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-30")
def test_receipt_contract_rejects_unbounded_or_incoherent_evidence():
    receipt = _receipt("api")
    with pytest.raises(ValueError):
        replace(receipt, process_kind="unknown")
    with pytest.raises(ValueError):
        replace(
            receipt,
            codex_provider_state="off",
            codex_provider_identity="cp_" + "a" * 24,
        )
    with pytest.raises(ValueError):
        replace(
            receipt,
            expires_at=receipt.observed_at + timedelta(hours=2),
        )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-30")
def test_boot_identity_does_not_derive_from_hostname(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("HOSTNAME", "dictionary-fingerprintable-hostname")

    first = instance_identity("fleet", "random-token-a")
    second = instance_identity("fleet", "random-token-b")

    assert first != second
    assert "HOSTNAME" not in inspect.getsource(instance_identity)
    assert "dictionary-fingerprintable-hostname" not in first
    assert "dictionary-fingerprintable-hostname" not in second


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-30")
def test_receipt_persistence_is_per_instance_and_rls_fenced():
    root = Path(__file__).resolve().parents[2]
    migration = (root / "migrations/versions/0056_birth_profile_receipts.py").read_text()
    schema = (root / "boltrig/store/schema.sql").read_text()
    rls = (root / "boltrig/store/rls.sql").read_text()

    primary_key = "PRIMARY KEY (tenant_id, process_kind, instance_identity)"
    assert primary_key in migration
    assert primary_key in schema
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "'birth_profile_receipts'" in rls
    store_source = (root / "boltrig/store/birth_profiles.py").read_text()
    assert "OFFSET $3" in store_source
    assert "LIMIT $2" in store_source
    assert "BIRTH_PROFILE_RECEIPTS_PER_PROCESS" in store_source
