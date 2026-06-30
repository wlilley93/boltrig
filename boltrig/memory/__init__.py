"""Round Five memory subsystem (Epic MEM).

The knowledge-graph + vector engine is ADOPTED, not built (MEM-ENG-01): this
package defines an engine-agnostic ``MemoryEngine`` interface (the memory analogue
of the ``Adapter`` protocol), a minimal ``LocalMemoryEngine`` reference for
dev/offline, and a ``CogneeEngine`` adoption seam. The ``MemoryAdapter`` fronts
whichever engine is configured and IS the kernel-side isolation boundary: every
memory operation runs the dispatch chokepoint and the kernel - never the engine
alone - enforces owner-scope at ingestion and retrieval (SEC-40).

Severability (MEM-ENG-02): this package imports only ``boltrig.models`` and
``boltrig.adapters.base``; the kernel core (dispatch/grants/registry) imports
nothing from here, so the engine is a configuration choice, not a core dependency.
"""

from __future__ import annotations

from .engine import EngineFact, MemoryEngine, RecallHit
from .local import LocalMemoryEngine

__all__ = ["EngineFact", "MemoryEngine", "RecallHit", "LocalMemoryEngine"]
