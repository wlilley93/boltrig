"""The SQL adapter's read/write scope, which had never been exercised.

`sql_base.py`'s first paragraph advertises two invariants "enforced here so they
cannot be forgotten per adapter", and the second is:

    Read / write scope per binding. A binding marked read-only
    (write_allowed=False) cannot run a write: the attempt is refused with
    ErrorClass.UNAUTHORISED before any statement reaches the driver.

Nothing in tests/ mentioned `write_allowed` or `execute_write`. The only in-repo
subclass (`builtin/crm_sql.py`) is deliberately read-scoped, so the refusal had
never fired in EITHER direction - not proven to refuse, and not proven to permit.
A boundary in that state is a paragraph.

The claim has three parts and each is attacked separately: the refusal happens,
it happens BEFORE the driver is reached, and it does not fire on a binding that
is allowed to write. The middle one is the part that matters - a refusal raised
after the statement was already sent would satisfy a naive test and none of the
promise.
"""

from __future__ import annotations

from typing import Any

import pytest

from boltrig.adapters.base import Credential, ErrorClass, Result, VerbSpec
from boltrig.adapters.sql_base import SqlAdapter, _Db
from boltrig.models import GrantSet, InvocationContext

pytestmark = pytest.mark.security

T = "acme"


def _ctx() -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="tester")


class _ProbeAdapter(SqlAdapter):
    """A subclass whose handlers call the two seams, and which records every
    statement that actually reached the driver."""

    id = "probe-sql"
    version = "1.0.0"

    def __init__(self, *, write_allowed: bool) -> None:
        super().__init__(dsn="postgresql://u:p@db/x", write_allowed=write_allowed)
        self.reached_driver: list[tuple[str, bool]] = []

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id="probe.read",
                noun_id="probe",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                consequence="low",
            ),
            VerbSpec(
                verb_id="probe.write",
                noun_id="probe",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                consequence="high",
            ),
        ]

    def _handlers(self) -> dict[str, Any]:
        async def read(params: dict, db: _Db, ctx: InvocationContext) -> Result:
            return Result.success(await db.query("SELECT 1", {}))

        async def write(params: dict, db: _Db, ctx: InvocationContext) -> Result:
            return Result.success(await db.execute_write("UPDATE t SET a=:a", {"a": 1}))

        return {"probe.read": read, "probe.write": write}

    def _run_sync(self, dsn: str, sql: str, params: dict, write: bool) -> dict:
        # Stands in for the driver. Anything recorded here got PAST the scope
        # check, which is the whole question.
        self.reached_driver.append((sql, write))
        return {"rows": [], "count": 0}


@pytest.mark.invariant("SEC-189")
async def test_a_read_scoped_binding_refuses_a_write() -> None:
    adapter = _ProbeAdapter(write_allowed=False)

    result = await adapter.execute("probe.write", {}, Credential(
        id="c", kind="dsn", material={"dsn": "postgresql://u:p@db/x"}
    ), _ctx())

    assert not result.ok
    assert result.error is not None
    assert result.error.error_class is ErrorClass.UNAUTHORISED, result.error


@pytest.mark.invariant("SEC-189")
async def test_the_refusal_happens_BEFORE_anything_reaches_the_driver() -> None:
    """The load-bearing half of the sentence.

    "refused ... before any statement reaches the driver" is the part a naive
    test would miss: a refusal raised after the UPDATE had already been sent
    would still return UNAUTHORISED and would still be a write.
    """
    adapter = _ProbeAdapter(write_allowed=False)

    await adapter.execute("probe.write", {}, Credential(
        id="c", kind="dsn", material={"dsn": "postgresql://u:p@db/x"}
    ), _ctx())

    assert adapter.reached_driver == [], (
        f"a read-scoped binding sent {adapter.reached_driver} to the driver"
    )


@pytest.mark.invariant("SEC-189")
async def test_a_read_scoped_binding_still_reads() -> None:
    """The scope is a ceiling, not a mute: refusing everything would also pass
    the two tests above."""
    adapter = _ProbeAdapter(write_allowed=False)

    result = await adapter.execute("probe.read", {}, Credential(
        id="c", kind="dsn", material={"dsn": "postgresql://u:p@db/x"}
    ), _ctx())

    assert result.ok, result.error
    assert adapter.reached_driver == [("SELECT 1", False)]


@pytest.mark.invariant("SEC-189")
async def test_a_write_enabled_binding_is_permitted() -> None:
    """The other direction, never proven either: the refusal must not be
    unconditional. No in-repo subclass sets write_allowed=True, so without this
    the flag could have been ignored entirely and every test still passed."""
    adapter = _ProbeAdapter(write_allowed=True)

    result = await adapter.execute("probe.write", {}, Credential(
        id="c", kind="dsn", material={"dsn": "postgresql://u:p@db/x"}
    ), _ctx())

    assert result.ok, result.error
    assert adapter.reached_driver == [("UPDATE t SET a=:a", True)]
