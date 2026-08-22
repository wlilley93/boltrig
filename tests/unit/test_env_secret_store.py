"""The env secret store resolves INTEGRATION material, never process config.

A control-plane operator with integration-registration rights can choose the
credential REF. Pointed at a process-critical variable (the audit chain's HMAC
key, the database DSN), the old fetch handed it to the adapter as material -
and the MCP transport would post it as a bearer to a registered external
server: privilege escalation plus exfiltration in one ref."""

from __future__ import annotations

import pytest

from boltrig.kernel.credentials import CredentialResolution, EnvSecretStore

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "ref",
    ("DATABASE_URL", "REDIS_URL", "BOLTRIG_AUDIT_HMAC_KEY", "BOLTRIG_DEV_AUTH"),
)
async def test_process_critical_env_refs_are_refused(ref, monkeypatch):
    monkeypatch.setenv(ref, "secret-material-that-must-never-cross")
    with pytest.raises(CredentialResolution, match="process configuration"):
        await EnvSecretStore().fetch("env", ref)


@pytest.mark.parametrize("ref", ("DATABASE_URL", "BOLTRIG_AUDIT_HMAC_KEY"))
async def test_process_critical_env_refs_are_refused_even_when_unset(ref):
    # The refusal is about the NAME, not the value: an unset critical var must
    # not fall through to the generic "not set" error and invite a retry.
    import os

    saved = os.environ.pop(ref, None)
    try:
        with pytest.raises(CredentialResolution, match="process configuration"):
            await EnvSecretStore().fetch("env", ref)
    finally:
        if saved is not None:
            os.environ[ref] = saved


async def test_an_integration_env_ref_still_resolves(monkeypatch):
    monkeypatch.setenv("MY_JIRA_KEY", '{"token": "abc"}')
    material = await EnvSecretStore().fetch("env", "MY_JIRA_KEY")
    assert material == {"token": "abc"}
