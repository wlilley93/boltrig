"""Shared fixtures. The kernel runs on the in-memory store - no external services."""

from __future__ import annotations

import os

import pytest

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.kernel import Kernel
from boltrig.models import GrantSet, InvocationContext, TenantPermissions
from boltrig.store import InMemoryStore

TENANT = "acme"

# --- No precondition is allowed to be silent --------------------------------
#
# A skip is a fine mechanism. A skip nobody is told about is the failure, and this
# suite has now been bitten twice by the same shape:
#
#   * ~156 Postgres tests - the RLS fence-drift guard, store parity, migration
#     parity, tenancy - skipped without BOLTRIG_TEST_DATABASE_URL while pytest
#     still ended "N passed" in green. A Postgres-only foreign-key defect lived
#     through green local suite after green local suite.
#   * tests/security/test_rate_limit_backend.py skipped in CI because `fakeredis`
#     was reachable only as a transitive of the optional cognee extra and was
#     absent from requirements-dev-lock.txt, which is what CI installs. The test
#     that therefore never ran in CI is the direct regression for the defect this
#     project's goal document opens with: a kernel restart resetting the 2FA
#     brute-force bound because RedisCounter was constructed nowhere. A regression
#     test for the headline defect, green on the author's box and skipped in CI,
#     is that defect wearing the costume of its own fix.
#
# So every skip whose precondition a developer or CI COULD satisfy is either
# fatal or, at minimum, said out loud at the end of the run.
#
# BLOCKING - the run ends non-zero. These are satisfiable anywhere: a database
# URL, or a package the dev lock now pins, so absence means a broken environment
# rather than a missing service. Each has its own opt-out so declining is a
# decision on the record instead of an accident.
_BLOCKING: tuple[tuple[str, str, str], ...] = (
    (
        "BOLTRIG_TEST_DATABASE_URL",
        "BOLTRIG_ALLOW_UNVERIFIED_POSTGRES",
        "the RLS fence, store parity, migration parity and tenancy",
    ),
    (
        "fakeredis",
        "BOLTRIG_ALLOW_UNVERIFIED_RATELIMIT",
        "the SHARED rate-limit counter, including that it survives a restart",
    ),
)

# LOUD - reported, never silent, but not fatal: these need a live external service
# or a built image, and no environment variable conjures one. What is forbidden is
# the run ENDING without saying they did not happen.
_LOUD: tuple[tuple[str, str], ...] = (
    ("BOLTRIG_PER_CELL_IMAGE", "the per-cell UID escalation gates (J7/J9)"),
    ("HATCHET_CLIENT_TOKEN", "the live durable-engine legs"),
    ("BOLTRIG_COGNEE_LIVE", "the live knowledge-graph legs"),
    ("BOLTRIG_LIVE_SMOKE", "the live adapter reads"),
    ("BOLTRIG_CODEX_01443_SMOKE_BINARY", "the codex cell smoke and tool-ceiling legs"),
)

_skipped: dict[str, set[str]] = {}


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if not report.skipped:
        return
    reason = str(report.longrepr)
    for token, _, _ in _BLOCKING:
        if token in reason:
            _skipped.setdefault(token, set()).add(report.nodeid)
    for token, _ in _LOUD:
        if token in reason:
            _skipped.setdefault(token, set()).add(report.nodeid)


def _blocking_unverified() -> list[tuple[str, str, str, int]]:
    out = []
    for token, opt_out, what in _BLOCKING:
        nodes = _skipped.get(token)
        if nodes and not os.environ.get(opt_out):
            out.append((token, opt_out, what, len(nodes)))
    return out


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:  # noqa: ANN001
    if not _skipped:
        return
    write = terminalreporter.write_line
    blocking = _blocking_unverified()

    if blocking:
        write("")
        for token, opt_out, what, count in blocking:
            write(
                f"UNVERIFIED: {count} test(s) never ran - {token} is unavailable.",
                red=True, bold=True,
            )
            write(f"  This suite did NOT check {what}.", red=True)
            write(f"  To accept that deliberately: {opt_out}=1", red=True)

    loud = [
        (token, what, len(_skipped[token]))
        for token, what in _LOUD
        if token in _skipped
    ]
    accepted = [
        (token, what, len(_skipped[token]))
        for token, opt_out, what in _BLOCKING
        if token in _skipped and os.environ.get(opt_out)
    ]
    if loud or accepted:
        write("")
        write("NOT VERIFIED by this run (needs a live service or a built image):",
              yellow=True)
        for token, what, count in loud + accepted:
            write(f"  {count:>3} test(s)  {what}  [{token}]", yellow=True)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if exitstatus == 0 and _blocking_unverified():
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
