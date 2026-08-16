"""MailerSend password-recovery composition and transport boundaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from boltrig.api.password_reset_composition import compose_password_reset_delivery
from boltrig.identity import PasswordResetNotice
from boltrig.identity.mailersend_password_reset import (
    MailerSendPasswordResetConfig,
    MailerSendPasswordResetNotifier,
)


API_KEY = "mlsn." + "a" * 64
TOKEN = "boltrig_reset_exact-secret"
BASE_ENV = {
    "BOLTRIG_PASSWORD_RESET_PROVIDER": "mailersend",
    "BOLTRIG_MAILERSEND_API_KEY": API_KEY,
    "BOLTRIG_PASSWORD_RESET_FROM_EMAIL": "noreply@boltrig.io",
    "BOLTRIG_PASSWORD_RESET_FROM_NAME": "Boltrig",
    "BOLTRIG_PASSWORD_RESET_PUBLIC_ORIGIN": "https://dev.boltrig.io",
}


def _notice() -> PasswordResetNotice:
    return PasswordResetNotice(
        email="owner@example.io",
        token=TOKEN,
        expires_at=datetime(2026, 8, 14, tzinfo=UTC),
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-AUTH-RECOVERY-01")
async def test_mailersend_acceptance_uses_fixed_redacted_transport() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["body"] = json.loads(request.content)
        return httpx.Response(202, headers={"x-message-id": "message-1"})

    notifier, _probe = compose_password_reset_delivery(
        BASE_ENV, transport=httpx.MockTransport(handler)
    )
    assert await notifier(_notice()) is True
    request = captured["request"]
    assert isinstance(request, httpx.Request)
    assert request.url == "https://api.mailersend.com/v1/email"
    assert request.headers["authorization"] == f"Bearer {API_KEY}"
    assert request.headers["accept-encoding"] == "identity"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["to"] == [{"email": "owner@example.io"}]
    assert body["settings"] == {
        "track_clicks": False,
        "track_opens": False,
        "track_content": False,
    }
    assert "https://dev.boltrig.io/#/reset-password?token=" + TOKEN in body["text"]
    assert API_KEY not in repr(notifier)
    assert API_KEY not in repr(notifier._config)


@pytest.mark.security
@pytest.mark.invariant("SEC-AUTH-RECOVERY-01")
@pytest.mark.parametrize(
    "status,headers",
    [
        (202, {}),
        (202, {"x-message-id": "message-1", "x-send-paused": "true"}),
        (307, {"location": "https://attacker.invalid", "x-message-id": "message-1"}),
        (422, {"x-message-id": "message-1"}),
    ],
)
async def test_mailersend_refuses_unaccepted_or_redirected_delivery(
    status: int, headers: dict[str, str]
) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(status, headers=headers))
    notifier = MailerSendPasswordResetNotifier(
        MailerSendPasswordResetConfig(
            api_key=API_KEY,
            from_email="noreply@boltrig.io",
            public_origin="https://dev.boltrig.io",
        ),
        transport=transport,
    )
    assert await notifier(_notice()) is False


@pytest.mark.security
@pytest.mark.invariant("SEC-AUTH-RECOVERY-01")
async def test_mailersend_probe_is_read_only_bounded_and_quota_aware() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"quota": 1000, "remaining": 5})

    notifier, probe = compose_password_reset_delivery(
        BASE_ENV, transport=httpx.MockTransport(handler)
    )
    assert await probe() is True
    assert [request.method for request in requests] == ["GET"]
    assert requests[0].url == "https://api.mailersend.com/v1/api-quota"

    no_quota = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"quota": 1000, "remaining": 0})
    )
    notifier = MailerSendPasswordResetNotifier(notifier._config, transport=no_quota)
    assert await notifier.readiness_probe() is False

    compressed = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            content=b"not-decoded",
        )
    )
    notifier = MailerSendPasswordResetNotifier(notifier._config, transport=compressed)
    assert await notifier.readiness_probe() is False


@pytest.mark.security
@pytest.mark.invariant("SEC-AUTH-RECOVERY-01")
def test_mailersend_composition_fails_closed_on_partial_or_unsafe_config() -> None:
    assert compose_password_reset_delivery({}) == (None, None)
    with pytest.raises(RuntimeError, match="partially configured"):
        compose_password_reset_delivery({"BOLTRIG_MAILERSEND_API_KEY": API_KEY})
    with pytest.raises(RuntimeError, match="unsupported"):
        compose_password_reset_delivery({"BOLTRIG_PASSWORD_RESET_PROVIDER": "smtp"})
    with pytest.raises(ValueError, match="canonical HTTPS origin"):
        compose_password_reset_delivery(
            {**BASE_ENV, "BOLTRIG_PASSWORD_RESET_PUBLIC_ORIGIN": "http://localhost:1420"}
        )
    with pytest.raises(ValueError, match="sender"):
        compose_password_reset_delivery(
            {**BASE_ENV, "BOLTRIG_PASSWORD_RESET_FROM_EMAIL": "not-an-email"}
        )
