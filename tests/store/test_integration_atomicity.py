"""Failure-injection coverage for the PostgreSQL integration transaction helpers."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import replace

import pytest

from boltrig.models.integrations import IntegrationConnection
from boltrig.store.integration_atomic import create_pg, revoke_pg

T = "integration-atomic"


class _Transaction(AbstractAsyncContextManager):
    def __init__(self, connection):
        self.connection = connection
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.rolled_back = exc is not None
        if self.rolled_back:
            self.connection.pending_credential = False
            self.connection.pending_revoke = False
        else:
            self.connection.credential_committed |= self.connection.pending_credential
            self.connection.revoke_committed |= self.connection.pending_revoke
        return False


class _Acquire(AbstractAsyncContextManager):
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


def _row(connection: IntegrationConnection) -> dict:
    return {
        "id": connection.id,
        "tenant_id": connection.tenant_id,
        "integration_id": connection.integration_id,
        "adapter_id": connection.adapter_id,
        "label": connection.label,
        "health": connection.health,
        "credential_ref": connection.credential_ref,
        "credential_owned": connection.credential_owned,
        "accounts": connection.accounts,
        "last_checked_at": connection.last_checked_at,
        "revoked_at": connection.revoked_at,
        "created_at": connection.created_at,
        "updated_at": connection.updated_at,
    }


class _CreateConnection:
    def __init__(self, *, fail_after_credential: bool):
        self.fail_after_credential = fail_after_credential
        self.pending_credential = False
        self.pending_revoke = False
        self.credential_committed = False
        self.revoke_committed = False
        self.tx = _Transaction(self)

    def transaction(self):
        return self.tx

    async def execute(self, query, *args):
        return "SELECT 1"

    async def fetchrow(self, query, *args):
        if "INSERT INTO credential_refs" in query:
            self.pending_credential = True
            return {"id": args[0]}
        if self.fail_after_credential:
            raise RuntimeError("injected connection insert failure")
        return None


class _RevokeConnection(_CreateConnection):
    def __init__(self, connection: IntegrationConnection):
        super().__init__(fail_after_credential=False)
        self.connection = connection

    async def fetchrow(self, query, *args):
        if "SELECT * FROM integration_connections" in query:
            return _row(self.connection)
        if "UPDATE integration_connections" in query:
            self.pending_revoke = True
            return _row(
                replace(
                    self.connection,
                    health="revoked",
                    credential_ref=None,
                    credential_owned=False,
                )
            )
        raise AssertionError("unexpected query")

    async def execute(self, query, *args):
        if "DELETE FROM credential_refs" in query:
            raise RuntimeError("injected credential delete failure")
        return "SELECT 1"


def _connection() -> IntegrationConnection:
    return IntegrationConnection(
        id="conn-atomic",
        tenant_id=T,
        integration_id="tickets",
        adapter_id="tickets-adapter",
        label="Tickets",
        credential_ref="cred-atomic",
        credential_owned=True,
    )


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-06")
@pytest.mark.parametrize("fail_after_credential", [False, True])
async def test_pg_create_rolls_back_staged_credential_on_conflict_or_failure(
    fail_after_credential,
):
    connection = _CreateConnection(fail_after_credential=fail_after_credential)
    if fail_after_credential:
        with pytest.raises(RuntimeError, match="injected connection insert failure"):
            await create_pg(
                _Pool(connection),
                _connection(),
                {"kind": "integration_manual_secret", "fields": {"opaque": "secret"}},
            )
    else:
        assert not await create_pg(
            _Pool(connection),
            _connection(),
            {"kind": "integration_manual_secret", "fields": {"opaque": "secret"}},
        )
    assert connection.tx.rolled_back
    assert not connection.credential_committed


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-06")
async def test_pg_revoke_rolls_back_connection_when_owned_credential_delete_fails():
    connection = _RevokeConnection(_connection())
    with pytest.raises(RuntimeError, match="injected credential delete failure"):
        await revoke_pg(_Pool(connection), T, "conn-atomic")
    assert connection.tx.rolled_back
    assert not connection.revoke_committed
