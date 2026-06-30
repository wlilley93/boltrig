"""Persistence layer. The kernel depends on the ``Store`` protocol only."""

from __future__ import annotations

from .base import Store
from .memory import InMemoryStore

__all__ = ["Store", "InMemoryStore", "PostgresStore"]


def __getattr__(name: str):
    # Lazy import so the asyncpg dependency is only needed when Postgres is used
    # (keeps the offline/in-memory path import-light, P9).
    if name == "PostgresStore":
        from .postgres import PostgresStore

        return PostgresStore
    raise AttributeError(name)
