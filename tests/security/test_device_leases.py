"""Decision-0021 enrolled-device and exact-action lease security contracts."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.device import build_device_adapter
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.kernel.device_crypto import DeviceLeaseSigner, b64url_encode
from boltrig.kernel.device_route_support import owner_lease_view
from boltrig.models import (
    GrantSet,
    TenantPermissions,
    utcnow,
)
from boltrig.models.devices import DeviceLease
from boltrig.store import InMemoryStore

T = "device-tenant"


def _headers(
    subject: str = "alice", *, tenant: str = T, role: str = "member"
) -> dict[str, str]:
    return {
        "x-boltrig-tenant": tenant,
        "x-boltrig-subject": subject,
        "x-boltrig-role": role,
        "x-boltrig-grants": "*",
        "x-boltrig-tier": "human",
    }


def _device_public_key() -> str:
    public = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return b64url_encode(public)


def _client() -> tuple[TestClient, InMemoryStore, DeviceLeaseSigner]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    signer = DeviceLeaseSigner.from_seed(b"d" * 32)
    asyncio.run(kernel.register_adapter(T, build_device_adapter(store, signer)))
    app = create_app(kernel)
    app.state.device_lease_signer = signer
    return TestClient(app), store, signer


def _enrol(
    client: TestClient,
) -> tuple[str, str, str]:
    started = client.post(
        "/v1/devices/enrollment/start",
        json={"label": "Alice laptop"},
        headers=_headers(),
    )
    assert started.status_code == 200, started.text
    code = started.json()["authorization_code"]
    verifier = started.json()["lease_verifier"]
    completed = client.post(
        "/v1/device-agent/enrollment/complete",
        json={
            "authorization_code": code,
            "device_public_key": _device_public_key(),
        },
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["lease_verifier"] == verifier
    return body["device"]["id"], body["session_token"], code


def _root(
    client: TestClient,
    device_id: str,
    *,
    scope: str = "read_write",
    command_enabled: bool = False,
) -> str:
    response = client.post(
        f"/v1/devices/{device_id}/roots",
        json={
            "label": "Chosen workspace",
            "scope": scope,
            "command_enabled": command_enabled,
        },
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    return response.json()["root"]["id"]


def _invoke_body(
    verb: str,
    device_id: str,
    root_id: str,
    action: dict,
    *,
    approval_id: str | None = None,
) -> dict:
    body = {
        "noun": "device",
        "verb": verb,
        "params": {"device_id": device_id, "root_id": root_id, **action},
    }
    if approval_id is not None:
        body["approval_id"] = approval_id
    return body


def _request_and_approve(
    client: TestClient,
    verb: str,
    device_id: str,
    root_id: str,
    action: dict,
    *,
    respondent: str = "reviewer",
) -> str:
    pending = client.post(
        "/v1/invoke",
        json=_invoke_body(verb, device_id, root_id, action),
        headers=_headers(),
    )
    assert pending.status_code == 202, pending.text
    approval_id = pending.json()["hitl_request_id"]
    answered = client.post(
        f"/v1/hitl/{approval_id}/respond",
        json={"decision": "approve"},
        headers=_headers(respondent, role="org-admin"),
    )
    assert answered.status_code == 200, answered.text
    return approval_id


def _invoke_approved(
    client: TestClient,
    verb: str,
    device_id: str,
    root_id: str,
    action: dict,
    approval_id: str,
):
    return client.post(
        "/v1/invoke",
        json=_invoke_body(
            verb,
            device_id,
            root_id,
            action,
            approval_id=approval_id,
        ),
        headers=_headers(),
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
def test_enrollment_and_sessions_are_single_use_digest_only_and_owner_scoped():
    client, store, _ = _client()
    device_id, session_token, code = _enrol(client)

    assert code not in repr(store._device_enrollments)
    assert session_token not in repr(store._devices)
    assert asyncio.run(
        store.authenticate_device_session(T, device_id, session_token)
    ) is None

    replay = client.post(
        "/v1/device-agent/enrollment/complete",
        json={
            "authorization_code": code,
            "device_public_key": _device_public_key(),
        },
    )
    assert replay.status_code == 401
    assert client.get("/v1/devices", headers=_headers("mallory")).json() == {
        "devices": []
    }
    assert client.post(
        f"/v1/devices/{device_id}/roots",
        json={"label": "stolen", "scope": "read_write"},
        headers=_headers("mallory"),
    ).status_code == 404

    rotated = client.post(
        f"/v1/device-agent/{device_id}/session/rotate",
        headers={"authorization": f"Bearer {session_token}"},
    )
    assert rotated.status_code == 200, rotated.text
    new_token = rotated.json()["session_token"]
    assert session_token not in repr(store._devices)
    assert new_token not in repr(store._devices)
    assert client.get(
        f"/v1/device-agent/{device_id}/leases",
        headers={"authorization": f"Bearer {session_token}"},
    ).status_code == 401
    assert client.get(
        f"/v1/device-agent/{device_id}/leases",
        headers={"authorization": f"Bearer {new_token}"},
    ).status_code == 200

    assert client.delete(
        f"/v1/devices/{device_id}", headers=_headers()
    ).status_code == 200
    assert client.get(
        f"/v1/device-agent/{device_id}/leases",
        headers={"authorization": f"Bearer {new_token}"},
    ).status_code == 401


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
def test_no_direct_user_lease_materialization_route_exists():
    client, _, _ = _client()
    device_id, _, _ = _enrol(client)
    paths = client.app.openapi()["paths"]
    template = "/v1/devices/{device_id}/leases"
    assert template not in paths or "post" not in paths[template]

    response = client.post(
        f"/v1/devices/{device_id}/leases",
        json={
            "root_id": "root",
            "verb": "device.file.read",
            "approval_id": "approval",
            "action": {"relative_path": "safe.txt", "max_bytes": 10},
        },
        headers=_headers(),
    )

    assert response.status_code in {404, 405}


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
def test_owner_lease_projection_is_scoped_bounded_and_authority_free():
    client, _, _ = _client()
    device_id, session_token, _ = _enrol(client)
    root_id = _root(client, device_id)
    action = {"relative_path": "safe/report.txt", "max_bytes": 100}
    approval_id = _request_and_approve(
        client, "device.file.read", device_id, root_id, action
    )
    issued = _invoke_approved(
        client,
        "device.file.read",
        device_id,
        root_id,
        action,
        approval_id,
    )
    assert issued.status_code == 200, issued.text
    lease_id = issued.json()["output"]["lease_id"]

    before = client.get(
        f"/v1/devices/{device_id}/leases", headers=_headers()
    )
    assert before.status_code == 200, before.text
    assert before.json()["leases"][0] == {
        "id": lease_id,
        "device_id": device_id,
        "root_id": root_id,
        "verb": "device.file.read",
        "status": "issued",
        "issued_at": before.json()["leases"][0]["issued_at"],
        "expires_at": before.json()["leases"][0]["expires_at"],
        "settled_at": None,
        "receipt": None,
    }
    assert client.get(
        f"/v1/devices/{device_id}/leases", headers=_headers("mallory")
    ).status_code == 404
    assert client.get(
        f"/v1/devices/{device_id}/leases",
        headers=_headers("alice", tenant="rival"),
    ).status_code == 404

    auth = {"authorization": f"Bearer {session_token}"}
    pending = client.get(
        f"/v1/device-agent/{device_id}/leases", headers=auth
    ).json()["leases"][0]
    claimed = client.post(
        f"/v1/device-agent/{device_id}/leases/{lease_id}/claim",
        json={"signature": pending["signature"]},
        headers=auth,
    )
    claim_token = claimed.json()["claim_token"]
    receipt = {
        "byte_size": 4,
        "content_digest": "b" * 64,
        "local_result_available": True,
        "path": "/private/safe/report.txt",
        "argv": ["not", "projected"],
        "owner_id": "alice",
        "signature": "not-projected",
        "arbitrary": {"secret": "not-projected"},
    }
    settled = client.post(
        f"/v1/device-agent/{device_id}/leases/{lease_id}/receipt",
        json={
            "claim_token": claim_token,
            "status": "completed",
            "receipt": receipt,
        },
        headers=auth,
    )
    assert settled.status_code == 200, settled.text

    projected = client.get(
        f"/v1/devices/{device_id}/leases", headers=_headers()
    ).json()["leases"][0]
    assert set(projected) == {
        "id", "device_id", "root_id", "verb", "status",
        "issued_at", "expires_at", "settled_at", "receipt",
    }
    assert projected["status"] == "completed"
    assert projected["receipt"] == {
        "byte_size": 4,
        "content_digest": "b" * 64,
        "reported_local_result_available": True,
    }
    serialized = repr(projected)
    for forbidden in (
        claim_token, approval_id, "/private/safe/report.txt",
        "not-projected", "owner_id", "signature", "arbitrary",
    ):
        assert forbidden not in serialized


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
def test_file_listing_receipts_project_only_bounded_relative_metadata():
    now = utcnow()
    lease = DeviceLease(
        id="lease-list",
        tenant_id=T,
        device_id="device",
        root_id="root",
        owner_id="alice",
        verb="device.file.list",
        action={"relative_path": "src", "max_entries": 2},
        action_digest="a" * 64,
        approval_id="approval",
        issued_at=now,
        expires_at=now + timedelta(minutes=2),
        status="completed",
        settled_at=now,
        receipt={
            "entries": [
                {
                    "name": "main.py",
                    "path": "src/main.py",
                    "kind": "file",
                    "byte_size": 120,
                    "absolute_path": "/private/work/src/main.py",
                },
                {
                    "name": "linked",
                    "path": "src/linked",
                    "kind": "symlink",
                    "byte_size": None,
                    "target": "/etc/passwd",
                },
            ],
            "truncated": False,
            "root_path": "/private/work",
        },
    )

    projected = owner_lease_view(lease)["receipt"]
    assert projected == {
        "relative_path": "src",
        "entries": [
            {
                "name": "main.py",
                "path": "src/main.py",
                "kind": "file",
                "byte_size": 120,
            },
            {
                "name": "linked",
                "path": "src/linked",
                "kind": "symlink",
                "byte_size": None,
            },
        ],
        "truncated": False,
    }
    assert "/private" not in repr(projected)
    assert "/etc/passwd" not in repr(projected)

    escaped = replace(
        lease,
        receipt={
            "entries": [
                {
                    "name": "secret",
                    "path": "../secret",
                    "kind": "file",
                    "byte_size": 1,
                }
            ],
            "truncated": False,
        },
    )
    assert owner_lease_view(escaped)["receipt"] is None
    outside_approved_directory = replace(
        lease,
        receipt={
            "entries": [
                {
                    "name": "secret",
                    "path": "other/secret",
                    "kind": "file",
                    "byte_size": 1,
                }
            ],
            "truncated": False,
        },
    )
    assert owner_lease_view(outside_approved_directory)["receipt"] is None
    invalid_unicode = replace(
        lease,
        receipt={
            "entries": [
                {
                    "name": "\ud800",
                    "path": "src/\ud800",
                    "kind": "file",
                    "byte_size": 1,
                }
            ],
            "truncated": False,
        },
    )
    assert owner_lease_view(invalid_unicode)["receipt"] is None
    above_approved_count = replace(
        lease,
        receipt={
            "entries": [
                {
                    "name": f"item-{index}",
                    "path": f"src/item-{index}",
                    "kind": "file",
                    "byte_size": 1,
                }
                for index in range(3)
            ],
            "truncated": True,
        },
    )
    assert owner_lease_view(above_approved_count)["receipt"] is None
    too_many = replace(
        lease,
        receipt={
            "entries": [
                {
                    "name": f"item-{index}",
                    "path": f"src/item-{index}",
                    "kind": "file",
                    "byte_size": 1,
                }
                for index in range(101)
            ],
            "truncated": True,
        },
    )
    assert owner_lease_view(too_many)["receipt"] is None


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
def test_owner_projection_expires_an_unsettleable_claim_without_mutating_store():
    now = utcnow()
    lease = DeviceLease(
        id="lease-claimed-expired",
        tenant_id=T,
        device_id="device",
        root_id="root",
        owner_id="alice",
        verb="device.command.run",
        action={"argv": ["true"], "timeout_seconds": 10},
        action_digest="a" * 64,
        approval_id="approval",
        issued_at=now - timedelta(minutes=6),
        expires_at=now - timedelta(minutes=4),
        status="claimed",
        claim_expires_at=now - timedelta(seconds=1),
    )

    assert owner_lease_view(lease)["status"] == "expired"
    assert lease.status == "claimed"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
def test_signed_lease_requires_consumed_exact_action_and_is_single_use():
    client, store, signer = _client()
    device_id, session_token, _ = _enrol(client)
    root_id = _root(client, device_id)
    exact_action = {"relative_path": "reports/final.txt", "max_bytes": 4096}
    wrong_action = {"relative_path": "reports/other.txt", "max_bytes": 4096}

    pending_self = client.post(
        "/v1/invoke",
        json=_invoke_body(
            "device.file.read", device_id, root_id, exact_action
        ),
        headers=_headers(),
    )
    assert pending_self.status_code == 202
    self_approval = pending_self.json()["hitl_request_id"]
    self_answer = client.post(
        f"/v1/hitl/{self_approval}/respond",
        json={"decision": "approve"},
        headers=_headers(),
    )
    assert self_answer.status_code == 403
    assert asyncio.run(
        store.list_pending_device_leases(T, device_id)
    ) == []

    approval_id = _request_and_approve(
        client,
        "device.file.read",
        device_id,
        root_id,
        exact_action,
    )

    wrong_replay = _invoke_approved(
        client,
        "device.file.read",
        device_id,
        root_id,
        wrong_action,
        approval_id,
    )
    assert wrong_replay.status_code == 202
    issued_response = _invoke_approved(
        client,
        "device.file.read",
        device_id,
        root_id,
        exact_action,
        approval_id,
    )
    assert issued_response.status_code == 200, issued_response.text
    output = issued_response.json()["output"]
    assert set(output) == {
        "status",
        "lease_id",
        "device_id",
        "root_id",
        "verb",
        "expires_at",
    }
    assert "action" not in output and "signature" not in output

    duplicate = _invoke_approved(
        client,
        "device.file.read",
        device_id,
        root_id,
        exact_action,
        approval_id,
    )
    assert duplicate.status_code == 409

    auth = {"authorization": f"Bearer {session_token}"}
    pending = client.get(
        f"/v1/device-agent/{device_id}/leases", headers=auth
    )
    leases = pending.json()["leases"]
    assert [row["id"] for row in leases] == [output["lease_id"]]
    lease = leases[0]
    assert lease["action"] == exact_action
    assert lease["signing_key_id"] == signer.key_id
    assert "claim_token" not in lease
    claimed = client.post(
        f"/v1/device-agent/{device_id}/leases/{lease['id']}/claim",
        json={"signature": lease["signature"]},
        headers=auth,
    )
    assert claimed.status_code == 200, claimed.text
    claim_token = claimed.json()["claim_token"]
    assert claim_token not in repr(store._device_leases)
    assert client.post(
        f"/v1/device-agent/{device_id}/leases/{lease['id']}/claim",
        json={"signature": lease["signature"]},
        headers=auth,
    ).status_code == 409
    assert client.post(
        f"/v1/device-agent/{device_id}/leases/{lease['id']}/receipt",
        json={
            "claim_token": "wrong",
            "status": "completed",
            "receipt": {"bytes": 42},
        },
        headers=auth,
    ).status_code == 409
    assert client.post(
        f"/v1/device-agent/{device_id}/leases/{lease['id']}/receipt",
        json={
            "claim_token": claim_token,
            "status": "completed",
            "receipt": {"bytes": 42},
        },
        headers=auth,
    ).status_code == 200
    assert claim_token not in repr(store._device_leases)
    assert client.post(
        f"/v1/device-agent/{device_id}/leases/{lease['id']}/receipt",
        json={"claim_token": claim_token, "status": "completed"},
        headers=auth,
    ).status_code == 409


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
def test_paths_write_digests_and_command_opt_in_fail_closed():
    client, store, signer = _client()
    device_id, session_token, _ = _enrol(client)
    root_id = _root(client, device_id, scope="read")

    traversal = client.post(
        "/v1/invoke",
        json=_invoke_body(
            "device.file.read",
            device_id,
            root_id,
            {"relative_path": "../secret", "max_bytes": 100},
        ),
        headers=_headers(),
    )
    assert traversal.status_code == 400
    dot_segment = client.post(
        "/v1/invoke",
        json=_invoke_body(
            "device.file.read",
            device_id,
            root_id,
            {"relative_path": "reports/./secret", "max_bytes": 100},
        ),
        headers=_headers(),
    )
    assert dot_segment.status_code == 400
    no_digest = client.post(
        "/v1/invoke",
        json=_invoke_body(
            "device.file.write",
            device_id,
            root_id,
            {
                "relative_path": "result.txt",
                "byte_size": 4,
                "overwrite": False,
            },
        ),
        headers=_headers(),
    )
    assert no_digest.status_code == 400
    write = {
        "relative_path": "result.txt",
        "content_digest": "b" * 64,
        "byte_size": 4,
        "overwrite": False,
    }
    read_only = client.post(
        "/v1/invoke",
        json=_invoke_body(
            "device.file.write", device_id, root_id, write
        ),
        headers=_headers(),
    )
    assert read_only.status_code == 403
    assert read_only.json()["reason"] == "root_is_read_only"
    shell_string = client.post(
        "/v1/invoke",
        json=_invoke_body(
            "device.command.run",
            device_id,
            root_id,
            {
                "argv": "rm -rf anything",
                "cwd_relative": None,
                "timeout_seconds": 30,
            },
        ),
        headers=_headers(),
    )
    assert shell_string.status_code == 400

    command = {
        "argv": ["git", "status"],
        "cwd_relative": None,
        "timeout_seconds": 30,
    }
    disabled = client.post(
        "/v1/invoke",
        json=_invoke_body(
            "device.command.run", device_id, root_id, command
        ),
        headers=_headers(),
    )
    assert disabled.status_code == 403
    assert disabled.json()["reason"] == "command_disabled"

    rotated_signer = DeviceLeaseSigner.from_seed(b"r" * 32)
    asyncio.run(
        client.app.state.kernel.register_adapter(
            T, build_device_adapter(store, rotated_signer)
        )
    )
    stale_verifier = client.post(
        "/v1/invoke",
        json=_invoke_body(
            "device.file.read",
            device_id,
            root_id,
            {"relative_path": "safe.txt", "max_bytes": 100},
        ),
        headers=_headers(),
    )
    assert stale_verifier.status_code == 409
    assert stale_verifier.json()["reason"] == "device_verifier_stale"
    asyncio.run(
        client.app.state.kernel.register_adapter(
            T, build_device_adapter(store, signer)
        )
    )

    revoke_action = {"relative_path": "safe.txt", "max_bytes": 100}
    approval_id = _request_and_approve(
        client,
        "device.file.read",
        device_id,
        root_id,
        revoke_action,
    )
    issued_response = _invoke_approved(
        client,
        "device.file.read",
        device_id,
        root_id,
        revoke_action,
        approval_id,
    )
    assert issued_response.status_code == 200, issued_response.text
    issued = asyncio.run(
        store.get_device_lease(
            T, device_id, issued_response.json()["output"]["lease_id"]
        )
    )
    assert issued is not None
    assert client.delete(
        f"/v1/devices/{device_id}/roots/{root_id}", headers=_headers()
    ).status_code == 200
    auth = {"authorization": f"Bearer {session_token}"}
    assert client.get(
        f"/v1/device-agent/{device_id}/leases", headers=auth
    ).json()["leases"] == []
    assert client.post(
        f"/v1/device-agent/{device_id}/leases/{issued.id}/claim",
        json={"signature": issued.signature},
        headers=auth,
    ).status_code == 409


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
def test_ed25519_verifier_rejects_any_tampered_lease_field():
    signer = DeviceLeaseSigner.from_seed(b"s" * 32)
    now = utcnow()
    signed = signer.sign(
        DeviceLease(
            id="lease",
            tenant_id=T,
            device_id="device",
            root_id="root",
            owner_id="alice",
            verb="device.file.read",
            action={"relative_path": "safe.txt", "max_bytes": 10},
            action_digest="a" * 64,
            approval_id="approval",
            issued_at=now,
            expires_at=now + timedelta(minutes=2),
        )
    )
    assert signer.verify(signed)
    assert not signer.verify(
        replace(
            signed,
            action={"relative_path": "other.txt", "max_bytes": 10},
        )
    )
    assert not signer.verify(replace(signed, root_id="other-root"))


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
def test_only_registered_validation_reasons_reach_the_caller():
    """The device routes forward `str(exc)` - so what CAN be in it is the control.

    Every `raise ValueError` in device_routes uses a fixed token today, which is
    why returning the message is safe AND useful: a caller learns which field was
    wrong instead of retrying the identical request. But "safe because five call
    sites happen to agree" is the shape this repository has been bitten by, and
    CodeQL flagged the forward as information exposure for exactly that reason.

    So the property is pinned here rather than assumed. The seeded case is the
    one that matters: an exception message NOBODY registered - the kind a future
    `raise ValueError(f"bad scope {value!r}")` would produce - must come back as
    the generic token, not as itself.
    """
    from boltrig.kernel.device_routes import _VALIDATION_REASONS, _validation_reason

    for token in sorted(_VALIDATION_REASONS):
        assert _validation_reason(ValueError(token)) == token

    # THE seeded case: an unregistered message, carrying a value.
    leaky = ValueError("bad scope '/etc/shadow' for actor act_7f3 on tenant acme")
    assert _validation_reason(leaky) == "invalid_request"
    assert "act_7f3" not in _validation_reason(leaky)

    # And the shapes an exception can take that are not str-clean.
    assert _validation_reason(ValueError()) == "invalid_request"
    assert _validation_reason(ValueError("invalid_label", "extra")) == "invalid_request"

    # Every token the module can raise must be registered, or the allowlist is
    # the thing that breaks the API rather than the thing that guards it.
    import re
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "boltrig" / "kernel" / "device_routes.py"
    raised = set(re.findall(r'raise ValueError\("([^"]+)"\)', source.read_text(encoding="utf-8")))
    assert raised, "scanned nothing: no `raise ValueError(\"...\")` found in device_routes"
    assert raised <= _VALIDATION_REASONS, f"unregistered reason(s): {raised - _VALIDATION_REASONS}"
