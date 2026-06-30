"""Domain type aliases and small shared value types.

Domain ids are aliased strings (Agent-libOS practice) so signatures read as
intent rather than ``str`` soup. Domain state is modelled with frozen
dataclasses; API request/response bodies use Pydantic (see ``boltrig.kernel.app``).
"""

from __future__ import annotations

from datetime import datetime, timezone

# --- Domain id aliases --------------------------------------------------------
TenantId = str
NounId = str
VerbId = str
AdapterId = str
SkillId = str
WorkflowId = str
CapabilityName = str  # an agent-capability / runtime profile name
RunId = str
WorkItemId = str
UserId = str
HITLId = str


def utcnow() -> datetime:
    """Timezone-aware UTC now. All timestamps are stored in UTC (P, NFR-I18N-02)."""
    return datetime.now(timezone.utc)
