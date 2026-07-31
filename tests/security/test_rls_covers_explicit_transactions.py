"""Every explicit transaction must be subject to RLS, not merely labelled as such.

THE DEFECT, measured 2026-07-31. ``_apply_guc``'s own docstring says it:

    ``assume_role`` drops to ``boltrig_app``; WITHOUT IT THE POLICIES DO NOTHING,
    because the app connects as the owner and a superuser bypasses RLS even under
    FORCE.

Confirmed on the beelink: ``boltrig`` is ``rolsuper=t rolbypassrls=t``. And then 22
call sites omitted the switch. An AST sweep of every method holding its own
``_pool.acquire()`` found 28 of 31 applying no role switch at all - among them
``consume_ai_key_secret_proposal``, the integration-credential writes,
``set_recovery_codes``, ``answer_hitl`` and ``reserve_budgets_atomic``. Five
carried the comment "RLS-live: scope this explicit transaction" while enforcing
nothing.

Setting ``app.tenant_id`` is NOT the same as being subject to the policy. A
superuser with the GUC set is simply a superuser. That is why this guard keys on
the ROLE SWITCH and not on the presence of the GUC: the GUC was always there.

The fenced path (``_RlsPool.fetch``/``fetchrow``/``execute``) is covered by
construction. This file is about the methods that opt OUT of that facade by
holding their own transaction, because those are invisible to it.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SEARCH = [ROOT / "boltrig" / "store", ROOT / "boltrig" / "knowledge"]

# Methods that legitimately run OUTSIDE the fence, each for a stated reason. This
# is the entire set; anything else holding its own transaction must bind.
OWNER_LEVEL = {
    # Genuinely owner-level: there is NO tenant to bind, so the fence is
    # inapplicable rather than merely skipped. Each entry states why.
    #
    # NOTHING ELSE BELONGS HERE. add_org_member/remove_org_member were briefly
    # listed and did not belong: both bind properly via _apply_guc, and org_members
    # IS in the rls.sql scoped list, so exempting them would have made the guard
    # skip two methods that pass on merit.
    #
    # NOTHING ELSE BELONGS HERE. Every method that HAS a tenant must bind it and
    # is checked below. An earlier draft of this file listed all 22 converted
    # methods here as "binds per tenant internally", which made the guard skip
    # precisely the methods it existed to cover - a check that could not fail,
    # built by widening the allowlist until the test passed.
    "_scoped": "the fence's own implementation; it applies the switch",
    "acquire": "passthrough by design, so a caller can opt out explicitly",
    "close": "no query",
    "connect": "bootstrap, before any tenant exists",
    "apply_rls": "installs the policies; cannot be subject to them",
    "with_tenant": "sets the role and the GUC itself",
    "readiness_snapshot": "global catalogue facts, documented as outside the fence",
    "list_orgs": "cross-tenant control-plane enumeration (see test_rls_exemptions)",
}

# The two ways a transaction may become subject to the policies. Anything else -
# notably a bare set_config - leaves a superuser unfenced.
_BINDERS = ("bind_conn_to_tenant", "_bind_tenant", "_apply_guc", "SET LOCAL ROLE")


def _functions_holding_a_transaction():
    """Every function that acquires its own connection, with its source."""
    for root in SEARCH:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            src = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(src)
            except SyntaxError:  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    continue
                body = ast.get_source_segment(src, node) or ""
                if ".acquire()" not in body:
                    continue
                yield path.relative_to(ROOT), node.name, body


def test_an_explicit_transaction_binds_the_tenant_or_is_a_declared_exemption():
    """The guard. A new hand-rolled transaction must bind, or say why it does not."""
    unfenced = []
    for rel, name, body in _functions_holding_a_transaction():
        if name in OWNER_LEVEL:
            continue
        if any(binder in body for binder in _BINDERS):
            continue
        unfenced.append(f"{rel}:{name}")
    assert not unfenced, (
        "these hold their own transaction and never drop to boltrig_app, so RLS "
        f"does not apply to them: {sorted(unfenced)}. Call bind_conn_to_tenant, or "
        "add the method to OWNER_LEVEL with the reason it must run as owner."
    )


def test_setting_the_guc_alone_is_not_accepted_as_binding():
    """The precise mistake: GUC set, role not switched, policy never consulted.

    Every remaining bare ``set_config('app.tenant_id', ...)`` must sit inside a
    helper that ALSO switches role. A new one written inline is the 22-site defect
    starting over, and it reads as though it fenced something.
    """
    offenders = []
    for root in SEARCH:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            src = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(src)
            except SyntaxError:  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    continue
                body = ast.get_source_segment(src, node) or ""
                if "set_config('app.tenant_id'" not in body.replace('"', "'"):
                    continue
                # Permitted only where the role switch is right there with it.
                if "SET LOCAL ROLE" in body or "assumes_role" in body:
                    continue
                offenders.append(f"{path.relative_to(ROOT)}:{node.name}")
    assert not offenders, (
        "these set app.tenant_id without switching role, which under a superuser "
        f"owner enforces nothing: {sorted(offenders)}. Use bind_conn_to_tenant."
    )


def test_the_role_decision_has_exactly_one_source():
    """It must be read off the pool, never copied onto each store.

    The fence already had a two-sources-of-truth bug: ``_apply_guc`` read a
    contextvar while every method took the tenant as an argument, and enabling RLS
    killed the kernel at boot. Duplicating the ROLE decision the same way would be
    the identical mistake with a different field.
    """
    scope = (ROOT / "boltrig/store/tenant_scope.py").read_text(encoding="utf-8")
    assert "def pool_assumes_app_role" in scope
    assert 'getattr(pool, "assumes_role", False)' in scope, (
        "the decision must be read off the pool, which is the object that knows "
        "whether rls.sql was applied"
    )

    fence = (ROOT / "boltrig/store/rls_pool.py").read_text(encoding="utf-8")
    assert "def assumes_role" in fence, "_RlsPool must expose the answer"


def test_the_helper_switches_role_before_setting_the_guc():
    """Order matters: SET LOCAL ROLE must not be issued after the policy is read.

    Pins the mechanism rather than the intent, because the intent was already
    documented at 22 sites that did not deliver it.
    """
    src = (ROOT / "boltrig/store/tenant_scope.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "bind_conn_to_tenant"
    )
    body = ast.get_source_segment(src, fn) or ""
    assert body.index("SET LOCAL ROLE") < body.index("set_config"), (
        "the role must be assumed before the tenant GUC is set"
    )
    assert "pool_assumes_app_role" in body, "it must consult the pool, not a literal"


def test_the_binding_is_INERT_where_rls_was_never_applied():
    """Every deployment except one has never run rls.sql, and must be unaffected.

    ``bind_conn_to_tenant`` replaced 22 inline ``set_config`` calls. If it emitted
    ``SET LOCAL ROLE boltrig_app`` unconditionally, every deployment that never
    applied the overlay would fail on a role that does not exist - turning a
    security improvement into a fleet-wide outage.

    So the three states are pinned. Only the third, where rls.sql HAS been applied
    and the role exists, may differ from the original behaviour.
    """
    import asyncio

    from boltrig.store.rls_pool import _RlsPool
    from boltrig.store.tenant_scope import bind_conn_to_tenant

    class _Raw:  # what the store holds when BOLTRIG_RLS is unset
        def acquire(self):  # pragma: no cover - never called here
            raise AssertionError

    class _Conn:
        def __init__(self):
            self.statements = []

        async def execute(self, query, *args):
            self.statements.append(query)

    async def _emitted(pool):
        conn = _Conn()
        await bind_conn_to_tenant(conn, "t1", pool=pool)
        return conn.statements

    guc = "SELECT set_config('app.tenant_id', $1, true)"

    # RLS off entirely: byte-identical to the code this replaced.
    assert asyncio.run(_emitted(_Raw())) == [guc]
    # RLS requested but rls.sql absent, so boltrig_app does not exist: still inert.
    assert asyncio.run(_emitted(_RlsPool(_Raw(), assume_role=False))) == [guc]
    # The overlay applied: and ONLY here is the role assumed.
    assert asyncio.run(_emitted(_RlsPool(_Raw(), assume_role=True))) == [
        "SET LOCAL ROLE boltrig_app",
        guc,
    ]
