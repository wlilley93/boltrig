#!/usr/bin/env python3
"""Offline, in-process smoke test of the Nankle kernel guarantees.

No docker, no database, no network: it builds an InMemoryStore + Kernel, loads
the builtin ``memory-tickets`` adapter, and exercises the dispatch chokepoint
end to end through the public kernel API. It demonstrates the four behaviours
that define the kernel:

  1. a granted create + read succeeds            (happy path, P2)
  2. an ungranted call is denied                 (grant enforcement, SEC-07)
  3. a gated verb pauses for approval, then       (HITL gate, SEC-14)
     resumes once approved
  4. a call degrades when the backend is down     (graceful degradation, P9)

Each step prints a PASS/FAIL line; the process exits non-zero if any step fails.

Usage:  python scripts/smoke.py      (or: make smoke)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Run straight from a checkout (no editable install needed): put the repo root
# on the path before importing the package, so `make smoke` works out of the box.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nankle.adapters.builtin.memory_tickets import build as build_tickets  # noqa: E402
from nankle.kernel import Kernel  # noqa: E402
from nankle.models import (  # noqa: E402
    DegradedMode,
    GrantMissing,
    GrantSet,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
)
from nankle.store import InMemoryStore  # noqa: E402

TENANT = "acme"
_results: list[tuple[str, bool, str]] = []


def _ctx(grants: list[str], *, run_id: str = "smoke-run") -> InvocationContext:
    return InvocationContext(
        tenant_id=TENANT,
        grants=GrantSet.of(grants),
        actor="smoke-agent",
        actor_tier="ephemeral",
        run_id=run_id,
        depth=0,
    )


async def _build_kernel(blocking_verbs: set[str] | None = None):
    """A kernel on the in-memory store with the tenant ceiling and adapter set."""
    store = InMemoryStore()
    # Tenant ceiling permits the whole ticket noun (role-derived in production).
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["ticket.*"])))
    kernel = Kernel(store, blocking_verbs=blocking_verbs or set())
    adapter = build_tickets()
    await kernel.register_adapter(TENANT, adapter)
    return kernel, adapter


def _record(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    tag = "PASS" if ok else "FAIL"
    suffix = f"  ({detail})" if detail else ""
    print(f"[{tag}] {name}{suffix}")


async def step_granted_create_and_read() -> None:
    name = "granted create + read succeeds"
    try:
        kernel, _ = await _build_kernel()
        created = await kernel.invoke(
            "ticket", "ticket.create", {"title": "Fix login"}, _ctx(["ticket.create"])
        )
        assert created.get("status") == "open" and created.get("id"), created
        read = await kernel.invoke(
            "ticket", "ticket.read", {"id": created["id"]}, _ctx(["ticket.read"])
        )
        assert read["id"] == created["id"], read
        _record(name, True, f"ticket {created['id']} created and read back")
    except Exception as exc:  # noqa: BLE001 - smoke reports, never raises
        _record(name, False, f"{type(exc).__name__}: {exc}")


async def step_ungranted_is_denied() -> None:
    name = "ungranted call is denied"
    try:
        kernel, _ = await _build_kernel()
        try:
            await kernel.invoke(
                "ticket", "ticket.create", {"title": "x"}, _ctx([])  # no grants
            )
        except GrantMissing:
            _record(name, True, "GrantMissing raised as expected")
            return
        _record(name, False, "expected GrantMissing, but the call was allowed")
    except Exception as exc:  # noqa: BLE001
        _record(name, False, f"{type(exc).__name__}: {exc}")


async def step_gated_pause_then_resume() -> None:
    name = "gated verb pauses, then resumes after approval"
    try:
        kernel, _ = await _build_kernel(blocking_verbs={"ticket.create"})
        # First attempt must pause for a human decision.
        try:
            await kernel.invoke(
                "ticket", "ticket.create", {"title": "x"}, _ctx(["ticket.create"])
            )
        except PendingHuman as pending:
            req_id = pending.hitl_request_id
        else:
            _record(name, False, "expected PendingHuman, but the call ran immediately")
            return
        # The pending request is on the queue.
        outstanding = await kernel.hitl.list_pending(TENANT)
        assert any(r.id == req_id for r in outstanding), "request not listed as pending"
        # Approve it, then resume by replaying with the approval id.
        await kernel.hitl.answer(TENANT, req_id, "approve", "lead@acme")
        out = await kernel.invoke(
            "ticket", "ticket.create", {"title": "x"}, _ctx(["ticket.create"]),
            approval_id=req_id,
        )
        assert out.get("status") == "open", out
        _record(name, True, f"paused on {req_id[:8]}, approved, then created")
    except Exception as exc:  # noqa: BLE001
        _record(name, False, f"{type(exc).__name__}: {exc}")


async def step_degraded_when_backend_down() -> None:
    name = "call degrades when the backend is down"
    try:
        kernel, adapter = await _build_kernel()
        adapter._fail = True  # flip the builtin adapter to simulate an outage
        try:
            await kernel.invoke(
                "ticket", "ticket.create", {"title": "x"}, _ctx(["ticket.create"])
            )
        except DegradedMode as degraded:
            reason = degraded.output.get("_degraded", {}).get("reason")
            assert reason == "backend_unavailable", degraded.output
            assert degraded.deferred is True
            _record(name, True, f"degraded result deferred (reason={reason})")
            return
        _record(name, False, "expected DegradedMode, but the call returned a normal result")
    except Exception as exc:  # noqa: BLE001
        _record(name, False, f"{type(exc).__name__}: {exc}")


# --- live adapter smoke (opt-in: real reads through the builtin adapters) ------
# Each entry: (adapter_id, builder import path, read verb, params, credential env).
# The credential env holds the reference *material* as JSON (an OAuth/token dict,
# or a SQL DSN dict); the kernel never inlines secrets, it resolves references.
_LIVE_TARGETS = [
    ("jira", "nankle.adapters.builtin.jira", "ticket.search",
     {"jql": "order by created DESC", "max_results": 1}, "JIRA_OAUTH", "oauth"),
    ("ms-graph", "nankle.adapters.builtin.ms_graph", "directory.get_user",
     {"id": "me"}, "GRAPH_APP", "oauth"),
    ("crm-sql", "nankle.adapters.builtin.crm_sql", "contact.search",
     {"query": ""}, "CRM_DB_RO", "basic"),
]


async def live_adapter_smoke() -> list[tuple[str, bool, str]]:
    """One real read per adapter when its credential env is present (P2-1).

    Returns per-adapter (name, ok, detail). Adapters with no credential env are
    reported as skipped (ok=True) so the live run is green where it cannot test.
    Only invoked when NANKLE_LIVE_SMOKE=1.
    """
    import importlib

    from nankle.adapters.base import Credential

    out: list[tuple[str, bool, str]] = []
    for adapter_id, module_path, verb, params, cred_env, kind in _LIVE_TARGETS:
        name = f"live read: {adapter_id} {verb}"
        raw = os.environ.get(cred_env)
        if not raw:
            print(f"[SKIP] {name}  (set {cred_env} to test)")
            out.append((name, True, "skipped (no credential)"))
            continue
        try:
            adapter = importlib.import_module(module_path).build()
            material = json.loads(raw) if raw.strip().startswith("{") else {"value": raw}
            cred = Credential(id=adapter_id, kind=kind, material=material)
            result = await adapter.execute(verb, params, cred, _ctx([f"{verb.split('.')[0]}.read"]))
            ok = result.ok
            detail = "ok" if ok else f"{result.error.error_class.value}: {result.error.message}"
            print(f"[{'PASS' if ok else 'FAIL'}] {name}  ({detail})")
            out.append((name, ok, detail))
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {name}  ({type(exc).__name__}: {exc})")
            out.append((name, False, f"{type(exc).__name__}: {exc}"))
    return out


async def main() -> int:
    print("Nankle offline smoke test (in-process, no docker)\n")
    await step_granted_create_and_read()
    await step_ungranted_is_denied()
    await step_gated_pause_then_resume()
    await step_degraded_when_backend_down()

    live: list[tuple[str, bool, str]] = []
    if os.environ.get("NANKLE_LIVE_SMOKE") in {"1", "true", "yes"}:
        print("\nLive adapter smoke (real reads where credentials are present):")
        live = await live_adapter_smoke()
    else:
        print("\nLive adapter smoke: skipped (set NANKLE_LIVE_SMOKE=1 + per-adapter creds)")

    all_results = _results + live
    passed = sum(1 for _, ok, _ in all_results if ok)
    total = len(all_results)
    print(f"\n{passed}/{total} steps passed")
    if passed == total:
        print("RESULT: PASS")
        return 0
    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
