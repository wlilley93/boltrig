"""End-to-end password recovery invariants (SEC-AUTH-RECOVERY-01)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from boltrig.identity import (
    PasswordResetNotice,
    build_session_resolver,
    hash_password,
    hash_password_reset_token,
)
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    GrantSet,
    TenantPermissions,
    TwoFactorChallenge,
    User,
    utcnow,
)
from boltrig.store import InMemoryStore

T = "default"
EMAIL = "owner@example.io"
OLD_PASSWORD = "old-password-123"
NEW_PASSWORD = "new-password-456"


def _run(coro):
    return asyncio.run(coro)


class CaptureNotifier:
    def __init__(self) -> None:
        self.notices: list[PasswordResetNotice] = []

    async def __call__(self, notice: PasswordResetNotice) -> None:
        self.notices.append(notice)


def _app(notifier=...):
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    platform = {} if notifier is ... else {"password_reset_notifier": notifier}
    app = create_app(
        kernel,
        principal_resolver=build_session_resolver(T),
        platform=platform,
    )
    return kernel, store, app


async def _seed(store, *, must_change_password=False):
    await store.upsert_user(
        User(
            id=EMAIL,
            tenant_id=T,
            email=EMAIL,
            role="superadmin",
            scope={"all": True},
            status="active",
            source="initiate",
            must_change_password=must_change_password,
        )
    )
    await store.set_password_credential(T, EMAIL, hash_password(OLD_PASSWORD))


@pytest.mark.security
@pytest.mark.invariant("SEC-AUTH-RECOVERY-01")
def test_request_is_non_enumerating_hash_only_and_fails_closed_without_delivery(
    monkeypatch,
):
    monkeypatch.setenv("BOLTRIG_SESSION_COOKIE_SECURE", "0")
    notifier = CaptureNotifier()
    _kernel, store, app = _app(notifier)
    _run(_seed(store))
    client = TestClient(app)

    known = client.post("/v1/auth/password-reset/request", json={"email": f" {EMAIL.upper()} "})
    assert known.status_code == 202
    assert len(notifier.notices) == 1
    notice = notifier.notices[0]
    assert notice.email == EMAIL
    assert notice.token not in repr(notice)

    stored = store._password_reset_tokens[(T, EMAIL)]
    assert stored.token_hash == hash_password_reset_token(notice.token)
    assert notice.token != stored.token_hash
    assert notice.token not in json.dumps(stored.__dict__, default=str)
    assert (
        client.post(
            "/v1/auth/login",
            json={"email": EMAIL, "password": OLD_PASSWORD},
        ).status_code
        == 200
    )
    posture = client.get("/v1/platform/status").json()[
        "password_reset_delivery"
    ]
    assert posture == {
        "configuration": "configured",
        "configuration_reason": None,
        "evidence_kind": "bounded_audit_attempt_not_provider_receipt",
        "proves_recipient_delivery": False,
        "target_disclosed": False,
        "audit_tail_limit": 500,
        "evidence_status": "available",
        "last_attempt_at": posture["last_attempt_at"],
        "last_outcome": "accepted_by_notifier",
    }
    assert EMAIL not in repr(posture)
    assert notice.token not in repr(posture)

    unknown = client.post("/v1/auth/password-reset/request", json={"email": "absent@example.io"})
    assert unknown.status_code == 202
    assert known.content == unknown.content
    assert len(notifier.notices) == 1
    latest = client.get("/v1/platform/status").json()[
        "password_reset_delivery"
    ]
    assert latest["last_outcome"] == "not_accepted_by_notifier"
    assert EMAIL not in repr(latest)

    _kernel2, store2, app2 = _app()
    _run(_seed(store2))
    response = TestClient(app2).post("/v1/auth/password-reset/request", json={"email": EMAIL})
    assert response.status_code == 202
    assert getattr(store2, "_password_reset_tokens", {}) == {}
    events = _run(store2.audit_query(T, limit=100))
    assert any(
        event.verb == "auth.password_reset.delivery" and event.detail == {"outcome": "unavailable"}
        for event in events
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-AUTH-RECOVERY-01")
def test_delivery_attempt_evidence_cannot_become_an_account_enumeration_or_receipt():
    notifier = CaptureNotifier()
    _kernel, store, app = _app(notifier)
    _run(_seed(store))
    client = TestClient(app)
    assert client.post(
        "/v1/auth/password-reset/request",
        json={"email": EMAIL},
    ).status_code == 202

    # A non-author session can see only configuration posture, not a recent
    # attempt outcome that could become a reset-request enumeration oracle.
    async def member_resolver(_request):
        from boltrig.kernel.app import Principal

        return Principal(
            tenant_id=T,
            subject="member@example.io",
            role="member",
            grants=GrantSet.of([]),
            scope={},
        )

    member_app = create_app(
        Kernel(store),
        principal_resolver=member_resolver,
        platform={"password_reset_notifier": notifier},
    )
    posture = TestClient(member_app).get(
        "/v1/platform/status"
    ).json()["password_reset_delivery"]
    assert posture["configuration"] == "configured"
    assert posture["evidence_status"] == "restricted"
    assert posture["last_attempt_at"] is None
    assert posture["last_outcome"] is None
    assert posture["proves_recipient_delivery"] is False
    assert EMAIL not in repr(posture)


@pytest.mark.security
@pytest.mark.invariant("SEC-AUTH-RECOVERY-01")
def test_reset_is_one_use_revokes_sessions_and_never_audits_secrets(monkeypatch):
    monkeypatch.setenv("BOLTRIG_SESSION_COOKIE_SECURE", "0")
    notifier = CaptureNotifier()
    _kernel, store, app = _app(notifier)
    _run(_seed(store))

    first_session = TestClient(app)
    second_session = TestClient(app)
    assert (
        first_session.post(
            "/v1/auth/login", json={"email": EMAIL, "password": OLD_PASSWORD}
        ).status_code
        == 200
    )
    assert (
        second_session.post(
            "/v1/auth/login", json={"email": EMAIL, "password": OLD_PASSWORD}
        ).status_code
        == 200
    )
    user = _run(store.get_user(T, EMAIL))
    user.must_change_password = True
    _run(store.upsert_user(user))
    challenge = TwoFactorChallenge(
        tenant_id=T,
        token_hash="c" * 64,
        user_id=EMAIL,
        expires_at=utcnow() + timedelta(minutes=5),
    )
    _run(store.add_two_factor_challenge(challenge))

    recovery_client = TestClient(app)
    assert (
        recovery_client.post("/v1/auth/password-reset/request", json={"email": EMAIL}).status_code
        == 202
    )
    token = notifier.notices[0].token
    success = recovery_client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    assert success.status_code == 200
    assert success.json() == {"status": "ok"}

    replay = recovery_client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    unknown = recovery_client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": "boltrig_reset_unknown", "new_password": NEW_PASSWORD},
    )
    assert replay.status_code == unknown.status_code == 400
    assert replay.content == unknown.content

    user = _run(store.get_user(T, EMAIL))
    assert user.must_change_password is False
    assert all(session.revoked for session in _run(store.list_sessions(T, EMAIL)))
    assert _run(store.get_two_factor_challenge(T, challenge.token_hash)) is None
    assert first_session.get("/v1/me/settings").status_code == 401
    assert second_session.get("/v1/me/settings").status_code == 401
    assert (
        TestClient(app)
        .post("/v1/auth/login", json={"email": EMAIL, "password": OLD_PASSWORD})
        .status_code
        == 401
    )
    assert (
        TestClient(app)
        .post("/v1/auth/login", json={"email": EMAIL, "password": NEW_PASSWORD})
        .status_code
        == 200
    )

    audit = _run(store.audit_query(T, limit=1000))
    security = store._security.get(T, [])
    persisted = json.dumps(
        {
            "audit": [event.__dict__ for event in audit],
            "security": [event.__dict__ for event in security],
        },
        default=str,
    )
    assert token not in persisted
    assert NEW_PASSWORD not in persisted
    assert OLD_PASSWORD not in persisted


@pytest.mark.security
@pytest.mark.invariant("SEC-AUTH-RECOVERY-01")
def test_expired_and_invalid_tokens_share_one_rejection_and_requests_are_limited():
    notifier = CaptureNotifier()
    _kernel, store, app = _app(notifier)
    _run(_seed(store))
    client = TestClient(app)
    assert client.post("/v1/auth/password-reset/request", json={"email": EMAIL}).status_code == 202
    notice = notifier.notices[0]
    key = (T, EMAIL)
    store._password_reset_tokens[key] = replace(
        store._password_reset_tokens[key], expires_at=utcnow() - timedelta(seconds=1)
    )
    expired = client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": notice.token, "new_password": NEW_PASSWORD},
    )
    invalid = client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": "unknown", "new_password": NEW_PASSWORD},
    )
    assert expired.status_code == invalid.status_code == 400
    assert expired.content == invalid.content

    # The first request above consumed one of the per-identity hourly slots.
    assert client.post("/v1/auth/password-reset/request", json={"email": EMAIL}).status_code == 202
    assert client.post("/v1/auth/password-reset/request", json={"email": EMAIL}).status_code == 202
    limited = client.post("/v1/auth/password-reset/request", json={"email": EMAIL})
    assert limited.status_code == 429
    assert limited.json() == {"status": "error", "reason": "too many attempts"}

    # The invalid-token call above consumed one of the token's five minute slots.
    for _ in range(4):
        assert (
            client.post(
                "/v1/auth/password-reset/confirm",
                json={"token": "unknown", "new_password": NEW_PASSWORD},
            ).status_code
            == 400
        )
    confirm_limited = client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": "unknown", "new_password": NEW_PASSWORD},
    )
    assert confirm_limited.status_code == 429
    assert confirm_limited.json() == {"status": "error", "reason": "too many attempts"}
