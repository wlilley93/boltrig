"""Persistence layer. The kernel depends on the ``Store`` protocol only."""

from __future__ import annotations

from .base import Store
from .memory import InMemoryStore

__all__ = ["Store", "InMemoryStore"]
