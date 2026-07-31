"""The RLS fence's exemptions must stay narrow, and stay the ones we reasoned about.

WHY THIS FILE EXISTS. On 2026-07-31 enabling ``BOLTRIG_RLS=1`` silently stopped
two janitors for nine hours. ``run_anchor_sweep_detailed`` and ``run_hitl_expiry_sweep``
both start by enumerating tenants with ``store.list_orgs()``; under the fence that
read ran unbound, the ``organisations`` policy matched nothing, and it returned
ZERO rows. Both sweeps then iterated nothing, wrote no receipt, logged nothing and
returned 0 - indistinguishable from idle. Overdue HITL approvals stopped timing
out (SEC-14) and audit-chain anchoring stopped (COUNTY 9 D4).

``list_orgs`` is now deliberately exempt, because being cross-tenant is the point
of a control-plane enumeration. An exemption is only safe while the properties
that justify it hold, and NONE of them are enforced by the exemption itself:

  * no caller input, so there is no parameter to confuse;
  * returns org metadata, never tenant content;
  * reachable ONLY from the fleet janitors, never from a request path.

The third is the one a later edit breaks by accident, and it is the one that turns
a documented exemption into a cross-tenant leak. So it is pinned here: wiring an
exempt read into an HTTP surface fails the build.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "boltrig"

# The exempt read -> the ONLY modules permitted to call it. Adding a caller is a
# decision about tenant isolation, so it must be made HERE, in the file that
# explains what the exemption costs, and not incidentally at the call site.
EXEMPT_READ_CALLERS = {
    "list_orgs": {
        "boltrig/fleet/anchor.py",
        "boltrig/kernel/hitl_expiry.py",
    },
}

# Where an exempt read is allowed to be DEFINED. Keeping the definitions in one
# module is what makes "which reads skip the fence?" a question with an answer.
EXEMPT_DEFINITION_MODULES = {
    "boltrig/store/control_plane_reads.py",
    "boltrig/store/memory.py",  # the in-memory store has no RLS to skip
    "boltrig/store/base.py",  # protocol declaration only
}


def _python_files() -> list[pathlib.Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


def _rel(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT))


def _calls_named(tree: ast.AST, name: str) -> bool:
    """Whether this module CALLS ``name`` (``store.list_orgs()``), not merely mentions it."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == name:
            return True
        if isinstance(func, ast.Name) and func.id == name:
            return True
    return False


def test_only_the_reasoned_callers_reach_an_rls_exempt_read():
    """The property that makes the exemption safe: no request path can reach it.

    This is the guard that matters. list_orgs runs OUTSIDE tenant isolation, so a
    route that calls it hands every tenant's org list to whoever asked.
    """
    for read, permitted in EXEMPT_READ_CALLERS.items():
        actual = set()
        for path in _python_files():
            rel = _rel(path)
            if rel in EXEMPT_DEFINITION_MODULES:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            if _calls_named(tree, read):
                actual.add(rel)
        unexpected = actual - permitted
        assert not unexpected, (
            f"{read}() bypasses RLS and is now called from {sorted(unexpected)}. "
            "If that is a request-scoped surface it leaks every tenant. Either bind "
            "the read to a tenant, or add the caller to EXEMPT_READ_CALLERS and say "
            "why it is safe."
        )
        missing = permitted - actual
        assert not missing, (
            f"{read}() is no longer called from {sorted(missing)}, so this entry is "
            "stale. A guard listing callers that do not exist protects nothing."
        )


def test_an_exempt_read_is_defined_where_the_exemption_is_documented():
    """A fence-skipping read must not be scattered through the fenced store."""
    for read in EXEMPT_READ_CALLERS:
        definitions = set()
        for path in _python_files():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    if node.name == read:
                        definitions.add(_rel(path))
        stray = definitions - EXEMPT_DEFINITION_MODULES
        assert not stray, (
            f"{read}() is defined in {sorted(stray)}, outside the modules where the "
            "RLS exemption is documented and guarded."
        )


def test_the_exempt_read_uses_an_unfenced_connection_on_purpose():
    """It must use ``acquire()``, and the reason must survive in the source.

    ``_RlsPool.fetch`` applies ``SET LOCAL ROLE boltrig_app``; ``acquire()`` passes
    through without it. If someone "tidies" this back to ``self._pool.fetch`` the
    janitors go silently dead again, so pin the mechanism, not just the outcome.
    """
    src = (SRC / "store/control_plane_reads.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "list_orgs"
    )
    body = ast.get_source_segment(src, fn) or ""
    assert "_pool.acquire()" in body, (
        "list_orgs must take an unfenced connection via acquire(); the fenced "
        "convenience calls switch role and the read then returns zero rows"
    )
    assert "_pool.fetch(" not in body, (
        "self._pool.fetch applies the role switch, which is what broke both janitors"
    )
    assert "current_setting" not in body, "an exempt read has no tenant to bind"


def test_the_module_records_what_the_exemption_costs():
    """Prose is not enforcement, but an undocumented bypass is worse than a documented one.

    The next reader must find out from the module itself that this skips tenant
    isolation, rather than discovering it from an incident.
    """
    doc = ast.get_docstring(
        ast.parse((SRC / "store/control_plane_reads.py").read_text(encoding="utf-8"))
    )
    assert doc, "the exemption module must carry a docstring"
    lowered = doc.lower()
    for required in ("rls", "cross-tenant", "unbound"):
        assert required in lowered, (
            f"the exemption module docstring must state {required!r} so the bypass "
            "cannot be mistaken for an ordinary read"
        )


# The COMPLETE set of store coroutines that carry no tenant argument, and so
# cannot be tenant-bound. Every one is a candidate for the list_orgs failure: an
# unbound read under RLS returns zero rows and the caller cannot tell.
TENANTLESS_STORE_COROUTINES = {
    "apply_rls": "installs the policies; there is no tenant yet",
    "close": "no query",
    "list_orgs": "the discovery query; EXEMPTED, see this module's docstring",
    "readiness_snapshot": "global catalogue facts, documented as outside the fence",
}


def test_the_set_of_tenantless_store_reads_is_closed():
    """Answers "what ELSE reads unbound?" with a measurement, not a hope.

    ``list_orgs`` cost nine hours of two dead janitors. The generalisable question
    is which OTHER reads have no tenant to bind, because each one behaves the same
    way under the fence: zero rows, no error, and a caller that cannot distinguish
    that from an empty database.

    Measured 2026-07-31: exactly four, all accounted for. Pinning the set means a
    future tenantless method is a deliberate decision reviewed against this failure
    rather than a silent repeat of it.
    """
    import inspect

    from boltrig.store.postgres import PostgresStore

    found = set()
    for name in dir(PostgresStore):
        if name.startswith("_"):
            continue
        fn = inspect.getattr_static(PostgresStore, name, None)
        if not inspect.iscoroutinefunction(fn):
            continue
        if getattr(fn, "_boltrig_binds_tenant", False):
            continue
        found.add(name)

    expected = set(TENANTLESS_STORE_COROUTINES)
    added = found - expected
    assert not added, (
        f"new store coroutine(s) with no tenant to bind: {sorted(added)}. Under RLS "
        "an unbound read returns ZERO ROWS with no error - the failure that killed "
        "the anchor and hitl-expiry janitors. Decide explicitly whether each is a "
        "control-plane exemption or needs a tenant, then record it here."
    )
    gone = expected - found
    assert not gone, (
        f"{sorted(gone)} now bind a tenant (or no longer exist), so this list is "
        "stale. A guard describing methods that are not there protects nothing."
    )
