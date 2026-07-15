"""Enforce the control-plane direct-write chokepoint (SEC-140).

The control plane is migrating console mutations off direct Store writes and onto
governed control.* verbs through the ONE kernel chokepoint (SEC-75). Some writes
legitimately STAY direct - a caller acting on their OWN scope, or channel ingress
authenticated by the channel signature rather than a principal. This AST scan
pins the exact set of direct k.store / kernel.store mutations across every
console authoring route so:

  - a NEW direct write cannot be added silently: it must be added to
    SANCTIONED_DIRECT_WRITES in the same change, which is the review signal; and
  - the debt can only shrink: when a verb migration lands, its call site leaves
    both the module and this allowlist (e.g. control.invitation.revoke, migrated
    in this same change, is intentionally ABSENT below).

Modelled on the ast-walking style of tests/security/test_severability.py.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
_KERNEL = _REPO / "boltrig" / "kernel"

# Every console HTTP surface that contains, or historically contained, a direct
# Store mutation. Platform authoring modules stay in the ratchet even after their
# debt reaches zero so a regression cannot silently reintroduce a write.
_MODULES = (
    "access_routes.py",
    "channel_routes.py",
    "platform_routes/eval_routes.py",
    "platform_routes/personal.py",
)

# A store MUTATION: a method on a k.store / kernel.store receiver whose name
# begins with one of these verbs. Reads (get_/list_/find_/audit_query) are not
# writes and are ignored.
_MUTATOR = re.compile(r"^(upsert|update|create|add|remove|delete|set|mark|request|bump|consume)_")
_STORE_RECEIVERS = frozenset({"k", "kernel"})

# The COMPLETE set of sanctioned direct writes, keyed by a STABLE scan key
# (module, enclosing_function, method) - never a line number, so the freeze
# survives edits that move code around. This is the state AFTER
# control.invitation.revoke is migrated (its revoke_invite/update_invitation site
# is intentionally absent).
SANCTIONED_DIRECT_WRITES: frozenset[tuple[str, str, str]] = frozenset(
    {
        # --- stay-direct-by-design: caller's OWN scope + channel ingress ------
        ("access_routes.py", "put_settings", "upsert_user_setting"),
        ("access_routes.py", "delete_my_conversation", "update_conversation"),
        ("access_routes.py", "rename_my_conversation", "update_conversation"),
        ("access_routes.py", "regenerate_message", "mark_message_superseded"),
        ("access_routes.py", "cancel_run", "request_run_cancel"),
        ("access_routes.py", "revoke_my_token", "update_pat"),
        ("access_routes.py", "revoke_my_session", "update_session"),
        ("access_routes.py", "switch_active_context", "update_session"),
        ("access_routes.py", "switch_active_org", "update_session"),
        # channel INGRESS: authenticated by the channel signature, not a
        # principal; the intake + pairing internals are the ingress seam.
        ("channel_routes.py", "channel_inbound", "create_work_item"),
        ("channel_routes.py", "_consume_pairing", "bump_channel_pairing_attempts"),
        ("channel_routes.py", "_consume_pairing", "consume_channel_pairing"),
        ("channel_routes.py", "_consume_pairing", "upsert_channel_binding"),
        # Caller-owned personal-agent configuration intentionally requires no
        # control.* grant; dispatching it as authoring would widen authority or
        # break the delegated-only contract pinned by SEC-30.
        ("personal.py", "configure_personal_agent", "upsert_personal_agent"),
    }
)


def _mutation_method(node: ast.Call) -> str | None:
    """Return the method name if node is a k.store/kernel.store MUTATION call,
    else None. Matches `(k|kernel).store.<mutator>_...(...)` (await-wrapped or
    not; the Await node's child Call is visited normally)."""
    func = node.func
    if not isinstance(func, ast.Attribute) or not _MUTATOR.match(func.attr):
        return None
    recv = func.value
    if not (isinstance(recv, ast.Attribute) and recv.attr == "store"):
        return None
    base = recv.value
    if isinstance(base, ast.Name) and base.id in _STORE_RECEIVERS:
        return func.attr
    return None


def _scan_module(path: pathlib.Path) -> set[tuple[str, str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[tuple[str, str, str]] = set()
    stack: list[str] = []

    class _V(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

        def visit_Call(self, node: ast.Call) -> None:
            method = _mutation_method(node)
            if method is not None and stack:
                found.add((path.name, stack[-1], method))
            self.generic_visit(node)

    _V().visit(tree)
    return found


@pytest.mark.security
@pytest.mark.invariant("SEC-140")
def test_control_plane_direct_writes_are_all_sanctioned():
    found: set[tuple[str, str, str]] = set()
    for name in _MODULES:
        found |= _scan_module(_KERNEL / name)

    unsanctioned = found - SANCTIONED_DIRECT_WRITES
    assert not unsanctioned, (
        "unsanctioned direct Store write(s) in the control-plane routes - route "
        "the mutation through a governed control.* verb (SEC-75), or, if it must "
        "stay direct, add it to SANCTIONED_DIRECT_WRITES with a reason:\n"
        + "\n".join(f"  {m}::{fn} -> {meth}" for m, fn, meth in sorted(unsanctioned))
    )

    stale = SANCTIONED_DIRECT_WRITES - found
    assert not stale, (
        "SANCTIONED_DIRECT_WRITES lists a site that no longer exists (the debt "
        "only decreases - remove the stale entry, e.g. after a verb migration):\n"
        + "\n".join(f"  {m}::{fn} -> {meth}" for m, fn, meth in sorted(stale))
    )

    # Tripwire on the closed ledger: only 14 self-scope/ingress writes remain.
    assert len(SANCTIONED_DIRECT_WRITES) == 14
