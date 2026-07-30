"""Persistence layer. The kernel depends on the ``Store`` protocol only."""

from __future__ import annotations

from typing import Any

from .base import Store
from .memory import InMemoryStore

__all__ = [
    "Store",
    "InMemoryStore",
    "PostgresStore",
    "set_current_tenant",
]


def __getattr__(name: str) -> Any:
    # Lazy import so the asyncpg dependency is only needed when Postgres is used
    # (keeps the offline/in-memory path import-light, P9).
    if name == "PostgresStore":
        from .postgres import PostgresStore

        return PostgresStore
    if name == "set_current_tenant":
        from .postgres import set_current_tenant

        return set_current_tenant
    raise AttributeError(name)
