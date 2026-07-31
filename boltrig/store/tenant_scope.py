"""Which tenant a store call is acting for, and binding it to the RLS GUC.

Split out of ``postgres.py`` because it is a self-contained concern and that file
is already at its size ratchet. ``set_current_tenant`` and ``_current_tenant`` are
re-exported from ``postgres`` so existing imports keep working.
"""

from __future__ import annotations

import contextvars
import functools
import inspect

# RLS LIVE (opt-in): the active tenant for the current async context, set by the
# API per request (set_current_tenant). The _RlsPool reads it to scope every
# statement, so the opt-in RLS policies activate through the store's UNCHANGED
# method bodies - no per-method retrofit. Default off; the running app is
# unaffected until BOLTRIG_RLS is set and the app connects as boltrig_app.
_current_tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "boltrig_current_tenant", default=None
)


def set_current_tenant(tenant_id: str | None) -> None:
    """Bind the active tenant for RLS for this async context (the API calls this
    per request from the resolved Principal)."""
    _current_tenant.set(tenant_id)


def _tenant_of(value: object) -> str | None:
    """The tenant a store call is operating on, from either calling shape."""
    if isinstance(value, str):
        return value
    tid = getattr(value, "tenant_id", None)
    return tid if isinstance(tid, str) else None


def _bind_tenant_from_argument(fn):
    """Set ``_current_tenant`` from this call's own argument, so ``_apply_guc``
    cannot read a tenant different from the one being queried.

    THE SECOND SOURCE OF TRUTH WAS THE BUG: ``_apply_guc`` read a contextvar while
    every method takes the tenant as an argument, kept in step by hand. On
    2026-07-30, 318 tenant-carrying coroutines against 51 ``set_current_tenant``
    sites and no middleware. Enabling BOLTRIG_RLS then killed the kernel at boot on
    ``model_endpoints``: the bootstrap write passed a tenant the fence never saw.
    That WRITE is the lucky case - an unbound READ returns ZERO ROWS silently.

    What it does NOT buy: fence and WHERE clause now agree by construction, so this
    cannot catch a caller passing the WRONG tenant. It catches a missing or wrong
    WHERE clause, which is the failure ``rls.sql`` was written for. A call with no
    discoverable tenant is left as it was, so this only ever narrows.
    """

    # The first parameter's NAME, captured once, because these methods are called
    # BOTH ways. An earlier version took `first` positionally and broke every
    # keyword call - record_background_job_attempt(tenant_id=T, ...) raised
    # "missing 1 required positional argument: 'first'". The suite caught it.
    _params = list(inspect.signature(fn).parameters)
    _first_name = _params[1] if len(_params) > 1 else None

    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs):
        if args:
            candidate = args[0]
        elif _first_name is not None and _first_name in kwargs:
            candidate = kwargs[_first_name]
        else:
            candidate = None
        tenant_id = _tenant_of(candidate)
        if tenant_id is None:
            return await fn(self, *args, **kwargs)
        token = _current_tenant.set(tenant_id)
        try:
            return await fn(self, *args, **kwargs)
        finally:
            _current_tenant.reset(token)

    wrapper._boltrig_binds_tenant = True  # type: ignore[attr-defined]
    return wrapper


def pool_assumes_app_role(pool: object) -> bool:
    """Whether statements on ``pool``'s connections must drop to ``boltrig_app``.

    ONE place decides, and it is the pool, because the pool is the thing that knows
    whether ``rls.sql`` was ever applied. Copying the answer onto each store that
    holds a pool is how the fence acquired a second source of truth once already.

    Absent on a raw asyncpg pool (RLS off), so the default is False and nothing
    changes for a deployment that never opted in.
    """
    return bool(getattr(pool, "assumes_role", False))


async def bind_conn_to_tenant(conn, tenant_id: str, *, pool: object) -> None:
    """Make ``conn`` subject to the tenant policies for ``tenant_id``, for real.

    THE ROLE SWITCH IS THE WHOLE MECHANISM, AND 22 SITES OMITTED IT. The app
    connects as the table owner, which on every deployment measured is a SUPERUSER,
    and **a superuser bypasses RLS unconditionally - even under FORCE ROW LEVEL
    SECURITY**. So a transaction that sets ``app.tenant_id`` and nothing else is not
    fenced at all: the GUC is set, the policy is never consulted, and the code reads
    as though isolation is enforced. Five of those sites carried the comment
    "RLS-live: scope this explicit transaction" while enforcing nothing.

    Use this for any explicit transaction the ``_RlsPool`` facade cannot wrap.
    ``acquire()`` deliberately passes through without the switch, so a method that
    holds its own transaction gets no fence unless it asks for one here.

    The tenant is passed EXPLICITLY rather than read from the contextvar, because a
    method that already has the tenant in hand must not be able to bind a different
    one - that disagreement was the 2026-07-30 boot failure.
    """
    if pool_assumes_app_role(pool):
        await conn.execute("SET LOCAL ROLE boltrig_app")
    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)


def bind_tenant_on_store_methods(cls):
    """Apply _bind_tenant_from_argument to every public tenant-carrying coroutine.

    Done here, once, rather than as 319 decorators: a per-method opt-in is the
    same hand-maintained correspondence that failed in the first place, and the
    319th method to be added would simply be forgotten.

    ``with_tenant`` is excluded because it opens its own transaction and sets the
    GUC itself, and ``readiness_snapshot`` is untouched because it takes no tenant
    and documents that it deliberately reads outside the fence.
    """
    for name in dir(cls):
        if name.startswith("_") or name == "with_tenant":
            continue
        fn = inspect.getattr_static(cls, name, None)
        if not inspect.iscoroutinefunction(fn):
            continue
        if getattr(fn, "_boltrig_binds_tenant", False):
            continue
        try:
            params = list(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            continue
        if len(params) < 2:
            continue
        setattr(cls, name, _bind_tenant_from_argument(fn))
    return cls


