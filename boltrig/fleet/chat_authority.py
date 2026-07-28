"""Say when a chat turn has no usable authority. Fail-closed is right; SILENT is the bug.

Its own module because ``fleet/chat.py`` sits at its structural ratchet, and because
this is one rule rather than a phrase re-derived at a call site.

Found on a live tenant, 2026-07-28: the client's own account was in neither
``org_members`` nor ``workspace_members``, so role resolution produced the empty
grant set (SEC-78), and its role was absent from ``chat.skills_by_role`` while
``default_skills`` was ``[]``, so it loaded no skills either. Every turn that user
took had zero tools - and nothing in the log or the ledger said so. The turn
completed, the agent apologised, and the record showed nothing wrong, which is the
worst way for a client to meet a defect.

``scripts/check_user_authority.py`` is the same rule applied ahead of time, per
tenant; this is the one that fires on a real turn.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def warn_if_no_usable_authority(role: str, ceiling: Any, skills: list[str]) -> None:
    """Role name and counts only: no grant patterns, no user content (K-20)."""
    if ceiling.allow and skills:
        return
    logger.warning(
        "chat turn has no usable authority: role=%s grants=%d skills=%d "
        "(a caller in no org/workspace resolves to the empty set, and a role absent "
        "from chat.skills_by_role falls back to default_skills)",
        role,
        len(ceiling.allow),
        len(skills),
    )
