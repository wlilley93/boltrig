"""Production store bootstrap follows the ordered migration boundary."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from boltrig.api.bootstrap import build_store
from boltrig.store import PostgresStore


@pytest.mark.invariant("FR-OPS-01")
@pytest.mark.parametrize("rls", [False, True])
async def test_runtime_store_never_replays_mutable_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    rls: bool,
) -> None:
    dsn = "postgresql://operator:secret@db/boltrig"
    sentinel = object()
    connect = AsyncMock(return_value=sentinel)
    monkeypatch.setenv("DATABASE_URL", dsn)
    if rls:
        monkeypatch.setenv("BOLTRIG_RLS", "1")
    else:
        monkeypatch.delenv("BOLTRIG_RLS", raising=False)
    monkeypatch.setattr(PostgresStore, "connect", connect)

    assert await build_store() is sentinel
    connect.assert_awaited_once_with(dsn, apply_schema=False, rls=rls)
