"""Device actions are ordinary dispatcher data and materialize one exact lease."""

from __future__ import annotations

from datetime import timedelta

import pytest

from boltrig.adapters.builtin.device import (
    DEVICE_VERBS,
    build_device_adapter,
    device_specs,
)
from boltrig.kernel import Kernel
from boltrig.kernel.approval_digest import approval_action_digest
from boltrig.kernel.device_crypto import DeviceLeaseSigner, token_digest
from boltrig.models import (
    AdapterFailure,
    GrantSet,
    HITLStateConflict,
    HITLStatus,
    InvocationContext,
    PendingHuman,
    SchemaValidationError,
    TargetType,
    TenantPermissions,
    utcnow,
)
from boltrig.models.device_actions import canonical_device_action
from boltrig.models.devices import DeviceEnrollment, DeviceRoot, EnrolledDevice
from boltrig.store import InMemoryStore

T = "device-dispatch-tenant"
SIGNER = DeviceLeaseSigner.from_seed(b"v" * 32)


def _context(*, run_id: str | None = None) -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(["device.*"]),
        actor="alice",
        actor_tier="human",
        run_id=run_id,
        extra={"principal_role": "member", "principal_scope": {"all": True}},
    )


async def _kernel(
    *, scope: str = "read_write", command_enabled: bool = True
) -> tuple[Kernel, str, str]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["device.*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(T, build_device_adapter(store, SIGNER))
    now = utcnow()
    enrollment = DeviceEnrollment(
        id="enrollment",
        tenant_id=T,
        owner_id="alice",
        label="Alice laptop",
        authorization_code_hash=token_digest("enrollment-secret"),
        expires_at=now + timedelta(minutes=5),
    )
    await store.create_device_enrollment(enrollment)
    device = await store.complete_device_enrollment(
        T,
        enrollment.id,
        token_digest("enrollment-secret"),
        EnrolledDevice(
            id="device_1",
            tenant_id=T,
            owner_id="untrusted",
            label="untrusted",
            public_key="device-public",
            public_key_fingerprint="f" * 64,
            lease_verify_key_id=SIGNER.key_id,
            session_token_hash=token_digest("device-session"),
            session_expires_at=now + timedelta(hours=1),
        ),
    )
    assert device is not None
    root = DeviceRoot(
        id="root_1",
        tenant_id=T,
        device_id=device.id,
        label="Opaque workspace",
        scope=scope,
        command_enabled=command_enabled,
    )
    assert await store.create_device_root(root, "alice")
    return kernel, device.id, root.id


async def _pending(
    kernel: Kernel,
    verb: str,
    params: dict,
    context: InvocationContext,
    *,
    idempotency_key: str | None = None,
) -> str:
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke(
            "device",
            verb,
            params,
            context,
            idempotency_key=idempotency_key,
        )
    return held.value.hitl_request_id


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
async def test_device_verbs_register_as_high_consequence_adapter_data() -> None:
    kernel, _, _ = await _kernel()
    specs = {spec.verb_id: spec for spec in device_specs()}

    assert tuple(specs) == DEVICE_VERBS
    assert all(spec.consequence == "high" for spec in specs.values())
    assert all(spec.idempotency_mode == "cacheable" for spec in specs.values())
    for verb in DEVICE_VERBS:
        stored = await kernel.store.get_verb(T, verb)
        binding = await kernel.store.get_binding(T, verb)
        assert stored is not None and stored.consequence.value == "high"
        assert binding is not None
        assert binding.target_type == TargetType.ADAPTER
        assert binding.target_ref == "device"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
async def test_file_listing_is_exact_bounded_and_never_becomes_a_direct_read() -> None:
    kernel, device_id, root_id = await _kernel(scope="read")
    params = {
        "device_id": device_id,
        "root_id": root_id,
        "relative_path": "src",
        "max_entries": 40,
    }
    request_id = await _pending(kernel, "device.file.list", params, _context())
    request = await kernel.hitl.get(T, request_id)
    assert request is not None
    action, digest = canonical_device_action(
        device_id,
        root_id,
        "device.file.list",
        {"relative_path": "src", "max_entries": 40},
    )
    assert action == {"relative_path": "src", "max_entries": 40}
    assert request.action_digest == digest

    await kernel.hitl.answer(T, request_id, "approve", "reviewer")
    output = await kernel.invoke(
        "device",
        "device.file.list",
        params,
        _context(),
        approval_id=request_id,
    )
    assert output["verb"] == "device.file.list"
    assert "src" not in repr(output)
    lease = await kernel.store.get_device_lease(T, device_id, output["lease_id"])
    assert lease is not None and lease.action == action

    with pytest.raises(AdapterFailure) as traversal:
        await kernel.invoke(
            "device",
            "device.file.list",
            {**params, "relative_path": "../secret"},
            _context(),
        )
    assert traversal.value.reason == "invalid_relative_path"
    for invalid in ({**params, "max_entries": 101}, {**params, "recursive": True}):
        with pytest.raises(SchemaValidationError):
            await kernel.invoke(
                "device", "device.file.list", invalid, _context()
            )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
async def test_dispatch_consumes_exact_nonself_approval_and_materializes_once() -> None:
    kernel, device_id, root_id = await _kernel()
    params = {
        "device_id": device_id,
        "root_id": root_id,
        "relative_path": "reports/final.txt",
        "max_bytes": 4096,
    }
    context = _context()
    request_id = await _pending(
        kernel,
        "device.file.read",
        params,
        context,
        idempotency_key="read-final-once",
    )
    request = await kernel.hitl.get(T, request_id)
    assert request is not None
    _, canonical_digest = canonical_device_action(
        device_id,
        root_id,
        "device.file.read",
        {"relative_path": "reports/final.txt", "max_bytes": 4096},
    )
    assert request.action_digest == canonical_digest
    assert request.action_digest == approval_action_digest(
        noun="device", verb="device.file.read", params=params
    )

    await kernel.hitl.answer(T, request_id, "approve", "independent-reviewer")
    output = await kernel.invoke(
        "device",
        "device.file.read",
        params,
        context,
        idempotency_key="read-final-once",
        approval_id=request_id,
    )
    assert set(output) == {
        "status",
        "lease_id",
        "device_id",
        "root_id",
        "verb",
        "expires_at",
    }
    assert output["status"] == "leased"
    assert "reports/final.txt" not in repr(output)
    assert "signature" not in output and "action" not in output

    leases = await kernel.store.list_pending_device_leases(T, device_id)
    assert len(leases) == 1
    lease = leases[0]
    assert lease.id == output["lease_id"]
    assert lease.action == {
        "relative_path": "reports/final.txt",
        "max_bytes": 4096,
    }
    assert lease.action_digest == request.action_digest
    assert SIGNER.verify(lease)
    assert (await kernel.hitl.get(T, request_id)).status == HITLStatus.CONSUMED

    with pytest.raises(HITLStateConflict):
        await kernel.invoke(
            "device",
            "device.file.read",
            params,
            context,
            approval_id=request_id,
        )
    assert len(kernel.store._device_leases) == 1
    audits = await kernel.store.audit_query(T)
    assert "reports/final.txt" not in repr(audits)
    assert any(
        event.verb == "device.file.read"
        and event.target_adapter == "device"
        and event.status == "ok"
        for event in audits
    )

    replay = await kernel.invoke(
        "device",
        "device.file.read",
        params,
        context,
        idempotency_key="read-final-once",
    )
    assert replay == output
    assert len(kernel.store._device_leases) == 1


@pytest.mark.parametrize(
    ("verb", "action"),
    [
        (
            "device.file.write",
            {
                "relative_path": "reports/result.txt",
                "content_digest": "a" * 64,
                "byte_size": 4,
                "overwrite": False,
            },
        ),
        (
            "device.command.run",
            {
                "argv": ["git", "status", "--short"],
                "cwd_relative": "reports",
                "timeout_seconds": 30,
            },
        ),
    ],
)
@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
async def test_write_and_command_dispatch_bind_every_exact_action_field(
    verb: str, action: dict,
) -> None:
    kernel, device_id, root_id = await _kernel()
    params = {"device_id": device_id, "root_id": root_id, **action}
    request_id = await _pending(kernel, verb, params, _context())
    request = await kernel.hitl.get(T, request_id)
    assert request is not None
    _, digest = canonical_device_action(
        device_id, root_id, verb, action
    )
    assert request.action_digest == digest

    await kernel.hitl.answer(T, request_id, "approve", "reviewer")
    output = await kernel.invoke(
        "device", verb, params, _context(), approval_id=request_id
    )
    lease = await kernel.store.get_device_lease(
        T, device_id, output["lease_id"]
    )
    assert lease is not None
    assert lease.action == action
    assert lease.action_digest == digest
    assert SIGNER.verify(lease)


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
async def test_self_approval_never_materializes_a_device_lease() -> None:
    kernel, device_id, root_id = await _kernel()
    params = {
        "device_id": device_id,
        "root_id": root_id,
        "relative_path": "safe.txt",
        "max_bytes": 100,
    }
    request_id = await _pending(
        kernel, "device.file.read", params, _context()
    )
    await kernel.hitl.answer(T, request_id, "approve", "alice")

    with pytest.raises(AdapterFailure) as denied:
        await kernel.invoke(
            "device",
            "device.file.read",
            params,
            _context(),
            approval_id=request_id,
        )
    assert denied.value.status_code == 403
    assert await kernel.store.list_pending_device_leases(T, device_id) == []


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
async def test_schema_root_policy_and_command_opt_in_fail_before_approval() -> None:
    kernel, device_id, root_id = await _kernel(
        scope="read", command_enabled=False
    )
    with pytest.raises(SchemaValidationError):
        await kernel.invoke(
            "device",
            "device.file.write",
            {
                "device_id": device_id,
                "root_id": root_id,
                "relative_path": "result.txt",
                "content_digest": "a" * 64,
                "byte_size": 1,
            },
            _context(),
        )
    with pytest.raises(AdapterFailure) as read_only:
        await kernel.invoke(
            "device",
            "device.file.write",
            {
                "device_id": device_id,
                "root_id": root_id,
                "relative_path": "result.txt",
                "content_digest": "a" * 64,
                "byte_size": 1,
                "overwrite": False,
            },
            _context(),
        )
    assert read_only.value.reason == "root_is_read_only"
    with pytest.raises(AdapterFailure) as command_disabled:
        await kernel.invoke(
            "device",
            "device.command.run",
            {
                "device_id": device_id,
                "root_id": root_id,
                "argv": ["git", "status"],
                "cwd_relative": None,
                "timeout_seconds": 30,
            },
            _context(),
        )
    assert command_disabled.value.reason == "command_disabled"
    assert await kernel.hitl.list_pending(T) == []


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
async def test_cancelled_run_cannot_materialize_or_claim_a_device_lease() -> None:
    kernel, device_id, root_id = await _kernel()
    params = {
        "device_id": device_id,
        "root_id": root_id,
        "relative_path": "cancelled.txt",
        "max_bytes": 100,
    }
    context = _context(run_id="run-cancel-before")
    request_id = await _pending(
        kernel, "device.file.read", params, context
    )
    await kernel.hitl.answer(T, request_id, "approve", "reviewer")
    await kernel.store.request_run_cancel(T, context.run_id, "alice")

    with pytest.raises(AdapterFailure) as cancelled:
        await kernel.invoke(
            "device",
            "device.file.read",
            params,
            context,
            approval_id=request_id,
        )
    assert cancelled.value.reason == "run_cancelled"
    assert (await kernel.hitl.get(T, request_id)).status == HITLStatus.ANSWERED
    assert await kernel.store.list_pending_device_leases(T, device_id) == []

    live_context = _context(run_id="run-cancel-after")
    live_request = await _pending(
        kernel, "device.file.read", params, live_context
    )
    await kernel.hitl.answer(T, live_request, "approve", "reviewer")
    output = await kernel.invoke(
        "device",
        "device.file.read",
        params,
        live_context,
        approval_id=live_request,
    )
    lease = await kernel.store.get_device_lease(
        T, device_id, output["lease_id"]
    )
    assert lease is not None
    await kernel.store.request_run_cancel(T, live_context.run_id, "alice")
    assert await kernel.store.list_pending_device_leases(T, device_id) == []
    assert await kernel.store.claim_device_lease(
        T,
        device_id,
        lease.id,
        lease.signature,
        token_digest("claim-after-cancel"),
        utcnow() + timedelta(minutes=5),
    ) is None


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-07")
async def test_boot_registration_is_key_gated_and_uses_canonical_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from boltrig.api.device_bootstrap import register_device_actions
    from boltrig.kernel.device_crypto import b64url_encode

    store = InMemoryStore()
    kernel = Kernel(store)
    monkeypatch.delenv("BOLTRIG_DEVICE_LEASE_SIGNING_KEY", raising=False)
    await register_device_actions(kernel, T)
    assert await store.get_verb(T, "device.file.read") is None

    monkeypatch.setenv(
        "BOLTRIG_DEVICE_LEASE_SIGNING_KEY", b64url_encode(b"k" * 32)
    )
    await register_device_actions(kernel, T)
    assert await store.get_verb(T, "device.file.read") is not None
    assert kernel.loader.peek(T, "device") is not None
