"""The one projection of a user row that leaves the process.

It was written twice, byte for byte: once in ``config/control_plane.py`` for the
``control.user.*`` verbs and once in ``kernel/access_routes.py`` for the HTTP
console. Two copies of a projection is one copy and a future disagreement, and
the disagreement here would be quiet: an operator reading a verb's output would
see a different user than the same operator reading the console, with neither
side wrong about anything it could check.

It lives in ``identity`` because that is the layer both callers already import
(``rbac``), and because what may be said about a user is an identity question
rather than a transport one.

NOTE WHAT IS ABSENT. No password hash, no session token, no TOTP secret: those
live in their own tables precisely so a projection like this cannot reach them
by accident. Adding a field here adds it to both surfaces at once, which is the
point.
"""

from __future__ import annotations

from typing import Any


def user_view(user: Any) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "scope": user.scope,
        "status": user.status,
        "source": user.source,
        "source_group": user.source_group,
        "last_seen_at": user.last_seen_at.isoformat() if user.last_seen_at else None,
    }
