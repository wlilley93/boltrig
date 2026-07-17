"""Expose the shared durable execution-ledger fixtures to tests/store.

Re-exported through a conftest rather than imported per test module: pytest then
resolves ``ledger`` / ``ledger_pool`` by name, so a test declaring one as a
parameter is not shadowing an imported symbol. The fixtures themselves, the
migration-driven DDL, and the DSN skip guard live in ``execution_ledger_pg``.
"""

from __future__ import annotations

from tests.store.execution_ledger_pg import ledger, ledger_pool

__all__ = ["ledger", "ledger_pool"]
