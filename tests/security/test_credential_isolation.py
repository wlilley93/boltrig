"""Credentials never reach an agent or the audit log (SEC-05, K-20)."""

import pytest

from boltrig.adapters.base import Credential
from tests.conftest import TENANT, make_ctx


@pytest.mark.security
@pytest.mark.invariant("SEC-05")
def test_credential_repr_never_leaks_material():
    """The defence ~14 modules' docstrings rest on when they say the material is
    "never logged". `material` carries `repr=False`, and that is the half doing the
    work: seeded both ways, removing it fails this test, while removing the
    overridden `__str__` does NOT - `str()` then falls back to the dataclass repr,
    which already omits the material. So `__str__` is belt-and-braces, and this
    docstring says so rather than implying the property needs both.

    Bound to SEC-05 as of 2026-07-27. It was bound to NOTHING - the only guard on
    a defence the record asserts everywhere, itself enforceable by nothing, which
    is the exact shape of the order-D8 finding. Deleting this test broke no gate,
    and with it gone `repr=False` could come off in a tidy-up and every one of
    those docstrings would quietly become false."""
    c = Credential(id="jira", kind="oauth", material={"token": "sk-supersecretvalue123456"})
    assert "supersecret" not in repr(c)
    assert "supersecret" not in str(c)
    # The wrapper is what is defended; formatting it every way a caller might.
    assert "supersecret" not in f"{c}" and "supersecret" not in f"{c!r}"
    assert "supersecret" not in "%s" % (c,) and "supersecret" not in "{}".format(c)


@pytest.mark.security
@pytest.mark.invariant("SEC-05")
async def test_secret_material_never_enters_audit(kernel, monkeypatch):
    # Bind a credential with a known secret so the resolver actually runs, then
    # drive a normal call and assert no audit row carries the resolved material.
    secret = "sk-cred-isolation-9f8e7d6c5b4a"
    monkeypatch.setenv("BOLTRIG_TEST_TICKET_SECRET", secret)
    await kernel.store.set_credential_ref(
        TENANT, "cred-ticket",
        {"store": "env", "ref": "BOLTRIG_TEST_TICKET_SECRET", "kind": "api_key"},
    )
    kernel.credentials.bind_adapter_credential(TENANT, "memory-tickets", "cred-ticket")
    out = await kernel.invoke(
        "ticket", "ticket.create", {"title": "Fix login"}, make_ctx(["ticket.create"])
    )
    assert "id" in out
    events = await kernel.store.audit_query(TENANT)
    blob = repr([e.detail for e in events])
    assert secret not in blob
    assert "sk-" not in blob and "token" not in blob.lower()


@pytest.mark.security
@pytest.mark.invariant("K-20")
async def test_audit_scrubs_secret_in_detail(kernel):
    # Write an audit event whose detail contains a secret; the writer must scrub it.
    from boltrig.models import ActionType, AuditEvent, utcnow

    await kernel.audit.write(
        AuditEvent(
            tenant_id=TENANT,
            ts=utcnow(),
            actor="x",
            action_type=ActionType.MODEL_CALL,
            status="ok",
            detail={"prompt": "my api key is sk-abcdefghijklmnopqrstuvwxyz"},
        )
    )
    events = await kernel.store.audit_query(TENANT)
    last = events[-1]
    assert last.detail["prompt"].get("_scrubbed") is True
    assert "sk-abcdef" not in repr(last.detail)
