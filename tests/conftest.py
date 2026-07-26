"""Shared fixtures. The kernel runs on the in-memory store - no external services."""

from __future__ import annotations

import os

import pytest

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.kernel import Kernel
from boltrig.models import GrantSet, InvocationContext, TenantPermissions
from boltrig.store import InMemoryStore

TENANT = "acme"

# --- The Postgres precondition is not allowed to be silent ------------------
#
# ~156 tests run only against a real Postgres: the RLS fence-drift guard, store
# parity, migration parity, tenancy. Without BOLTRIG_TEST_DATABASE_URL they SKIP,
# and pytest still ends "N passed" in green. For a long time CI was the only
# place that surface ran at all, which is how a Postgres-only foreign-key defect
# lived through green local suite after green local suite.
#
# A skip is a fine mechanism; a skip nobody is told about is the failure. So a
# run that skipped this family ends NON-ZERO with a banner naming what it did not
# check. Setting BOLTRIG_ALLOW_UNVERIFIED_POSTGRES=1 restores the old behaviour,
# because sometimes you genuinely want the offline subset - but then it is a
# choice on the record rather than an accident, which is the whole difference.
_PRECONDITION_ENV = "BOLTRIG_TEST_DATABASE_URL"
_OPT_OUT_ENV = "BOLTRIG_ALLOW_UNVERIFIED_POSTGRES"
_unverified: set[str] = set()


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.skipped and _PRECONDITION_ENV in str(report.longrepr):
        _unverified.add(report.nodeid)


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:  # noqa: ANN001
    if not _unverified:
        return
    count = len(_unverified)
    noun = "test" if count == 1 else "tests"
    if os.environ.get(_OPT_OUT_ENV):
        terminalreporter.write_line(
            f"NOT VERIFIED: {count} Postgres-backed {noun} skipped "
            f"({_OPT_OUT_ENV} is set, so this run is green anyway).",
            yellow=True,
        )
        return
    terminalreporter.write_line("")
    terminalreporter.write_line(
        f"UNVERIFIED: {count} {noun} never ran - {_PRECONDITION_ENV} is not set.",
        red=True,
        bold=True,
    )
    terminalreporter.write_line(
        "  This suite did NOT check the RLS fence, store parity, migration "
        "parity or tenancy.",
        red=True,
    )
    terminalreporter.write_line(
        "  Point it at a THROWAWAY database (these tests write), never one a "
        "running stack serves:",
        red=True,
    )
    terminalreporter.write_line(
        f"    {_PRECONDITION_ENV}=postgresql://boltrig:<pw>@<host>:5432/boltrig_test",
        red=True,
    )
    terminalreporter.write_line(
        f"  To accept an offline run deliberately: {_OPT_OUT_ENV}=1", red=True
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _unverified and not os.environ.get(_OPT_OUT_ENV) and exitstatus == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def make_ctx(grants: list[str], *, run_id: str = "run-1", depth: int = 0, **kw) -> InvocationContext:
    return InvocationContext(
        tenant_id=TENANT,
        grants=GrantSet.of(grants),
        actor=kw.get("actor", "ephemeral-1"),
        actor_tier=kw.get("actor_tier", "ephemeral"),
        run_id=run_id,
        parent_run_id=kw.get("parent_run_id"),
        depth=depth,
        on_behalf_of=kw.get("on_behalf_of"),
        skills_loaded=tuple(kw.get("skills_loaded", ())),
    )


async def _build_kernel(
    *,
    blocking_verbs: set[str] | None = None,
    approval_timeout_seconds: int | None = None,
) -> tuple[Kernel, object]:
    store = InMemoryStore()
    # tenant ceiling permits the whole ticket noun (role-derived in production)
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["ticket.*"])))
    kernel = Kernel(
        store,
        blocking_verbs=blocking_verbs or set(),
        approval_timeout_seconds=approval_timeout_seconds,
    )
    adapter = build_tickets()
    await kernel.register_adapter(TENANT, adapter)
    return kernel, adapter


@pytest.fixture
async def kernel():
    k, _ = await _build_kernel()
    return k


@pytest.fixture
async def kernel_and_adapter():
    return await _build_kernel()


@pytest.fixture
async def gated_kernel():
    """A kernel where ticket.create is a blocking (gated) verb."""
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    return k
