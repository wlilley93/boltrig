"""RLS-live wiring (SEC-65): the _RlsPool sets app.tenant_id from the request
context before every statement, and is fail-closed when no tenant is bound.

Together with the rls.sql fence test (test_rls.py), this proves RLS is ACTIVE in
the running app: the policies enforce isolation (fence test) and every store call
arrives with the right app.tenant_id (this test) - without touching any of the
store's ~100 method bodies.
"""

import asyncio

import pytest

from boltrig.store.postgres import _RlsPool, set_current_tenant


class _FakeConn:
    def __init__(self, log):
        self.log = log

    def transaction(self):
        class _T:
            async def __aenter__(self_inner):
                return None

            async def __aexit__(self_inner, *a):
                return False

        return _T()

    async def execute(self, q, *a):
        self.log.append(("execute", q, a))
        return "OK"

    async def fetch(self, q, *a):
        self.log.append(("fetch", q, a))
        return []


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self):
        self.log: list = []
        self.conn = _FakeConn(self.log)

    def acquire(self):
        return _Acquire(self.conn)


@pytest.mark.invariant("SEC-65")
def test_rls_pool_sets_tenant_guc_before_each_statement():
    pool = _FakePool()
    rls = _RlsPool(pool)
    set_current_tenant("acme")
    asyncio.run(rls.fetch("SELECT 1"))
    # the FIRST statement on the connection is the GUC set for the bound tenant
    op, query, args = pool.log[0]
    assert op == "execute"
    assert "set_config('app.tenant_id'" in query
    assert args[0] == "acme"
    # then the actual query runs
    assert pool.log[1][0] == "fetch"


@pytest.mark.invariant("SEC-65")
def test_rls_pool_is_fail_closed_when_no_tenant_bound():
    pool = _FakePool()
    rls = _RlsPool(pool)
    set_current_tenant(None)
    asyncio.run(rls.execute("UPDATE x SET y=1"))
    # an unbound tenant becomes '' so the RLS predicate is never true (no rows)
    assert pool.log[0][2][0] == ""
    set_current_tenant(None)  # leave the context clean for other tests
