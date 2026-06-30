"""Round Five memory subsystem (Epic MEM).

The knowledge-graph + vector engine is a CONFIGURATION CHOICE behind one interface
(MEM-ENG-02). This package defines the engine-agnostic ``MemoryEngine`` interface
(the memory analogue of the ``Adapter`` protocol) and ships four implementations:

  * ``LocalMemoryEngine``  - dev/offline, naive keyword overlap (the simplest ref);
  * ``VectorMemoryEngine`` - native vector recall (cosine over embeddings), still
    in-process + dependency-free via ``HashingEmbedder``, so binding tests exercise
    real vector recall offline;
  * ``PgVectorMemoryEngine`` - the SAME vector semantics persisted to this Postgres
    + pgvector, the production native engine (no separate vector DB);
  * ``CogneeEngine``       - the flag-on graph upgrade, ADOPTED not built.

The ``MemoryAdapter`` fronts whichever engine is configured and IS the kernel-side
isolation boundary: every memory operation runs the dispatch chokepoint and the
kernel - never the engine alone - enforces owner-scope at ingestion and retrieval
(SEC-40).

Severability (MEM-ENG-02): this package imports only ``boltrig.models``,
``boltrig.adapters.base`` and (for the pgvector DSN helper) ``boltrig.store.postgres``;
the kernel core imports nothing from here, so the engine never becomes a core
dependency. Heavy backends (pgvector's asyncpg pool, cognee) are lazy-imported, so
``import boltrig.memory`` stays offline-safe.
"""

from __future__ import annotations

from .embeddings import DEFAULT_DIM, Embedder, HashingEmbedder, cosine
from .engine import EngineFact, MemoryEngine, RecallHit
from .local import LocalMemoryEngine
from .vector import VectorMemoryEngine

__all__ = [
    "EngineFact",
    "MemoryEngine",
    "RecallHit",
    "LocalMemoryEngine",
    "VectorMemoryEngine",
    "Embedder",
    "HashingEmbedder",
    "cosine",
    "DEFAULT_DIM",
]
