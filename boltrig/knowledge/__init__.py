"""First-party, Codex-facing Knowledge extension.

PostgreSQL owns catalogue and provenance, ObjectVault owns immutable bytes, and
all compiler/search products are rebuildable projections.  The kernel imports
none of this package; bootstrap registers it as an ordinary governed adapter.
"""

from .bootstrap import register_knowledge
from .models import MAX_UPLOAD_BYTES

__all__ = ["MAX_UPLOAD_BYTES", "register_knowledge"]
