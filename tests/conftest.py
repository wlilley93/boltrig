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
    # Not an env var: the gitignored active manifest. These two legs are the
    # ORIGINAL member of the environment-dependent family - the retired-runtime
    # rule that passed on any box holding manifest.yaml and failed only in CI. The
    # rule was fixed; the SKIPS were not, and they matched none of the tokens
    # above, so in CI (where the file is never present) they have gone on
    # vanishing without a word. Named by their reason text because that is what
    # the skip actually carries.
    ("manifest", "the active-manifest legs (manifest.yaml is gitignored)"),
    # Root can write everything, so the cell-isolation boundary proves nothing and
    # correctly skips - but a plain `docker run` is root, and silently losing both
    # halves of a court-ordered security boundary is not something to discover by
    # reading -rs output.
    ("root can write everything", "the codex cell-isolation boundary (running as root)"),
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



# --- the operator's shell does not get a vote ---------------------------------
#
# 33 modules under boltrig/ read os.environ at CALL time, so a variable exported
# in the shell that launched pytest silently changes which branch a test takes. A
# test named "refuses under a production signal" can pass because the SHELL set
# the signal, and a test that asserts a fail-closed default can pass because the
# default was never in play. Neither failure is visible in the output; both make
# the suite a fact about a terminal.
#
# So product-behaviour variables are stripped for the duration of every test.
# monkeypatch restores them afterwards, and a test that wants one sets it itself -
# which is the point: the value under test becomes part of the test rather than
# part of the environment.
#
# KEPT, deliberately: the variables that select which tests RUN rather than how
# the product behaves. Stripping BOLTRIG_TEST_DATABASE_URL would skip the entire
# Postgres surface; stripping the live-service tokens would skip the live legs and
# report them as unverified, which is true but useless. HATCHET_CLIENT_TOKEN is
# the honest edge - it is read by readiness AND gates the live tests, and it is
# kept, so a shell that exports it can still colour a readiness test. That one is
# named rather than hidden.
_ENV_STRIP_PREFIXES = (
    "BOLTRIG_", "POSTGRES_", "HATCHET_", "LLM_", "BACKUP_", "EMBEDDING_", "PG",
)
_ENV_STRIP_EXACT = frozenset({"DATABASE_URL", "REDIS_URL", "ENV", "APP_ENV"})
_ENV_KEEP = frozenset({
    "BOLTRIG_TEST_DATABASE_URL",
    "BOLTRIG_ALLOW_UNVERIFIED_POSTGRES",
    "BOLTRIG_ALLOW_UNVERIFIED_RATELIMIT",
    "BOLTRIG_PER_CELL_IMAGE",
    "BOLTRIG_LIVE_SMOKE",
    "BOLTRIG_COGNEE_LIVE",
    "BOLTRIG_CODEX_01443_SMOKE_BINARY",
    "BOLTRIG_CODEX_BINARY",
    "BOLTRIG_MODEL_GATEWAY_URL",
    "HATCHET_CLIENT_TOKEN",
})


@pytest.fixture(autouse=True)
def _hermetic_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name in _ENV_KEEP:
            continue
        if name.startswith(_ENV_STRIP_PREFIXES) or name in _ENV_STRIP_EXACT:
            monkeypatch.delenv(name, raising=False)


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


@pytest.fixture
def opbox_addon(monkeypatch):
    """Activate the opbox addon for a test that asserts opbox-provisioned behaviour.

    Boltrig ships alone AND as the engine beneath a product, and integration
    knowledge lives in an addon rather than in the modules every boltrig ships
    (see docs/addons.md). Registration is not activation: reading opbox's
    ``riskClass`` vocabulary and sealing the on-behalf bearer for the ``opbox``
    adapter happen only where ``BOLTRIG_ADDONS`` names it. A test asserting either
    is asserting the PROVISIONED configuration and must say so.
    """
    monkeypatch.setenv("BOLTRIG_ADDONS", "opbox")
