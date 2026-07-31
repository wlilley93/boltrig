"""RLS-live wiring (SEC-65): the _RlsPool sets app.tenant_id from the request
context before every statement, and is fail-closed when no tenant is bound.

Together with the rls.sql fence test (test_rls.py), this proves RLS is ACTIVE in
the running app: the policies enforce isolation (fence test) and every store call
arrives with the right app.tenant_id (this test) - without touching any of the
store's ~100 method bodies.
"""

import asyncio

import pytest

from boltrig.store.postgres import PostgresStore, _RlsPool, set_current_tenant


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


@pytest.mark.invariant("SEC-65")
def test_set_recovery_codes_applies_tenant_guc_before_writing():
    # The explicit-transaction 2FA path must scope RLS before its DELETE/INSERT,
    # exactly like its budget/HITL siblings (answer_hitl, consume_budget). Without
    # the GUC, under BOLTRIG_RLS=1 the generic user_recovery_codes policy sees no
    # bound tenant, deletes zero rows and errors on INSERT WITH CHECK.
    pool = _FakePool()
    store = PostgresStore(pool)
    set_current_tenant("acme")
    asyncio.run(store.set_recovery_codes("acme", "u1", ["h1", "h2"]))
    # the FIRST statement inside the explicit transaction is the GUC set
    op, query, args = pool.log[0]
    assert op == "execute"
    assert "set_config('app.tenant_id'" in query
    assert args[0] == "acme"
    # only AFTER the GUC does the first data statement (the DELETE) run
    assert "DELETE FROM user_recovery_codes" in pool.log[1][1]
    set_current_tenant(None)  # leave the context clean for other tests


@pytest.mark.invariant("SEC-65")
def test_every_tenant_carrying_store_method_binds_the_guc_itself():
    """The fence must not depend on the CALLER having bound the contextvar.

    This is the structural half of the 2026-07-30 defect. _apply_guc read a
    contextvar while every store method already takes the tenant as an argument,
    and the two were kept in step by hand: 318 public tenant-carrying coroutines
    against 51 set_current_tenant call sites, with no request middleware. Turning
    BOLTRIG_RLS on in that state killed the kernel at boot on model_endpoints, and
    the read case is worse than the write case because an unbound read returns zero
    rows silently instead of raising.

    Only four methods may be exempt, and each takes NO tenant at all, so there is
    nothing to bind: apply_rls and close are pool/DDL level, list_orgs is
    cross-tenant by design, and readiness_snapshot documents its own bypass.
    """
    import inspect

    exempt = {"apply_rls", "close", "list_orgs", "readiness_snapshot", "with_tenant"}
    unbound = []
    for name in dir(PostgresStore):
        if name.startswith("_") or name in exempt:
            continue
        fn = inspect.getattr_static(PostgresStore, name, None)
        if not inspect.iscoroutinefunction(fn):
            continue
        if not getattr(fn, "_boltrig_binds_tenant", False):
            unbound.append(name)
    assert not unbound, (
        f"{len(unbound)} store coroutine(s) do not bind the tenant GUC from their "
        f"own argument, so RLS depends on the caller remembering: {unbound[:10]}"
    )


@pytest.mark.invariant("SEC-65")
def test_store_method_binds_the_guc_from_its_argument_not_the_caller():
    """The behavioural half: bind from the argument, with the caller UNBOUND.

    Red-seed by deleting the @bind_tenant_on_store_methods decorator: the GUC then
    carries '' (fail-closed) instead of the tenant the call was made for, which is
    exactly the zero-rows-silently failure.
    """
    from boltrig.store.postgres import _current_tenant

    pool = _FakePool()
    store = PostgresStore.__new__(PostgresStore)
    store._pool = _RlsPool(pool)
    store._assume_app_role = False

    set_current_tenant(None)  # the caller binds NOTHING, which is the whole point
    assert _current_tenant.get() is None

    asyncio.run(store.list_model_endpoints("tenant-from-the-argument"))

    guc = [e for e in pool.log if e[0] == "execute" and "app.tenant_id" in e[1]]
    assert guc, "no GUC statement was issued at all"
    assert guc[0][2][0] == "tenant-from-the-argument"

    # and the binding is scoped to the call, not leaked into the caller's context
    assert _current_tenant.get() is None


@pytest.mark.invariant("SEC-65")
def test_binding_works_when_the_tenant_is_passed_as_a_KEYWORD():
    """These methods are called both ways, and the first wrapper only took one.

    Taking the tenant positionally (`async def wrapper(self, first, *args)`) broke
    every keyword call: record_background_job_attempt(tenant_id=T, ...) raised
    "missing 1 required positional argument: 'first'". Two [postgres] store tests
    caught it. The GUC must be bound from whichever shape the caller used.
    """
    from boltrig.store.postgres import _current_tenant

    pool = _FakePool()
    store = PostgresStore.__new__(PostgresStore)
    store._pool = _RlsPool(pool)
    store._assume_app_role = False
    set_current_tenant(None)

    # keyword, not positional - this is the shape that regressed
    asyncio.run(store.list_model_endpoints(tenant_id="kw-tenant"))

    guc = [e for e in pool.log if e[0] == "execute" and "app.tenant_id" in e[1]]
    assert guc, "no GUC statement was issued for a keyword-passed tenant"
    assert guc[0][2][0] == "kw-tenant"
    assert _current_tenant.get() is None


@pytest.mark.invariant("SEC-65")
def test_every_holder_of_an_rls_pool_binds_the_tenant():
    """Decorating PostgresStore is NOT sufficient, and this is how we know.

    PostgresKnowledgeRepository holds its own _RlsPool and sits OUTSIDE the
    PostgresStore MRO, so the class decorator there never reached it. With
    BOLTRIG_RLS=1 the kernel got past model_endpoints and died on
    `new row violates row-level security policy for table "knowledge_providers"`.

    So the invariant is not "PostgresStore is decorated", it is "every class that
    issues statements through an _RlsPool binds the tenant". This walks the source
    for _pool users and fails on any that is neither a PostgresStore mixin (covered
    transitively) nor decorated itself - which is what makes a THIRD such class,
    added later, fail here rather than at some future boot.
    """
    import importlib
    import inspect
    import pathlib
    import re

    from boltrig.store.postgres import PostgresStore
    from boltrig.store.rls_pool import _RlsPool as _Fence

    covered = {c.__module__ for c in PostgresStore.__mro__}

    root = pathlib.Path(__file__).resolve().parents[2] / "boltrig"
    uses_pool = re.compile(r"self\._pool\.(execute|fetch|fetchrow)\b")
    offenders = []
    for path in root.rglob("*.py"):
        if not uses_pool.search(path.read_text(encoding="utf-8", errors="ignore")):
            continue
        module = ".".join(path.relative_to(root.parent).with_suffix("").parts)
        if module in covered or module == "boltrig.store.postgres":
            continue
        # Do NOT trust a name allowlist - that is a check that cannot fail. Import
        # the module and require that its _pool-using classes are ACTUALLY
        # decorated. Removing the decorator must turn this red.
        mod = importlib.import_module(module)
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if cls.__module__ != module:
                continue
            # _RlsPool IS the fence, not a consumer of one: it is the thing that
            # applies the binding, so requiring it to be decorated is circular.
            # Excluded BY IDENTITY rather than by module, so a genuine consumer
            # added to rls_pool.py later still fails here.
            if cls is _Fence:
                continue
            methods = [
                inspect.getattr_static(cls, a, None)
                for a in dir(cls)
                if not a.startswith("_")
            ]
            coros = [f for f in methods if inspect.iscoroutinefunction(f)]
            if not coros:
                continue
            if not any(getattr(f, "_boltrig_binds_tenant", False) for f in coros):
                offenders.append(f"{module}.{cls.__name__}")

    assert not offenders, (
        "these modules issue statements through an _RlsPool but are neither a "
        f"PostgresStore mixin nor decorated, so their tenant is unbound: {offenders}"
    )


@pytest.mark.invariant("SEC-65")
def test_the_knowledge_repository_is_decorated():
    """The concrete half of the sweep above: the class that actually broke boot."""
    import inspect

    from boltrig.knowledge.postgres_repository import PostgresKnowledgeRepository

    bound = [
        name
        for name in dir(PostgresKnowledgeRepository)
        if not name.startswith("_")
        and getattr(
            inspect.getattr_static(PostgresKnowledgeRepository, name, None),
            "_boltrig_binds_tenant",
            False,
        )
    ]
    assert "ensure_providers" in bound, "ensure_providers is the one that killed boot"
    assert len(bound) >= 17, f"only {len(bound)} methods bound"
