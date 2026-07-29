"""The four-eyes ratchet is ONE-WAY
([2026] VJS-CC-BOLTRIG-OPERATOR-SEAT-001, D2).

No control verb may take a tenant's count of active author-tier users from two
or more down to exactly one, because at exactly one the sole-author bootstrap
exemption (``hitl_response_auth._sole_active_author``) revives and
self-approval becomes lawful again. Such a verb would therefore not merely
change a role: it would silently convert a MANDATORY independent approval into
an optional one, for every future high-consequence verb on the tenant, with
nothing on the record saying so.

On Classical Visas this was pleaded as the CONSERVATIVE cure for a four-eyes
deadlock - demote the client, who had only been made ``admin`` so she would
have authority over her own data. It is the opposite of conservative. It
reaches the same "one human has root" endpoint the application's own AGAINST
section feared, and it needs no host access to get there. Worse, because
``control.user.update`` is itself high-consequence, executing it needs the very
approval it removes: the only person who could authorise stripping the client's
author tier is the client, signing away her own protection. The court refused
that limb on that ground independently of every other.

Its own module, not a helper beside the mutations it guards, because it is a
policy about the tenant's approval REGIME rather than a step in editing a user
row - and because the next verb that can move this count should have to import
something named for what it is.
"""

from __future__ import annotations

from typing import Any


def is_active_author(user: Any) -> bool:
    """Active AND author-tier: the exact predicate the exemption counts."""
    from boltrig.identity.rbac import AUTHOR_ROLES

    return getattr(user, "status", None) == "active" and getattr(user, "role", None) in AUTHOR_ROLES


async def assert_author_ratchet(
    store: Any, tenant_id: str, *, user_id: str, stays_author: bool
) -> None:
    """Refuse a crossing DOWN to exactly one active author.

    Refused BEFORE the write, not detected after: an audit row recording that
    four-eyes was switched off is not a control, it is a note.

    Deliberately silent on 3->2 and 2->2. The exemption keys on exactly one, so
    only the crossing down to one changes what an approval means. Silent too on
    1->1, or a single-author tenant could never demote or deactivate anybody -
    which would brick the very bootstrap posture the exemption exists to serve.

    ``stays_author`` is the caller's AFTER-state for ``user_id``. Callers should
    build the resulting record and read this off THAT, rather than deriving a
    separate "what this would do": a guard that models the mutation a second
    time is a guard that drifts from it. Building a copy rather than mutating in
    place also keeps the pre-change count readable from the store, which is what
    ``before`` below depends on.
    """
    users = await store.list_users(tenant_id)
    before = sum(1 for u in users if is_active_author(u))
    others = sum(1 for u in users if getattr(u, "id", None) != user_id and is_active_author(u))
    after = others + (1 if stays_author else 0)
    if before >= 2 and after == 1:
        raise PermissionError(
            "refused: this would leave the tenant with a single active author-tier "
            "user, reviving the sole-author exemption and turning the mandatory "
            "independent approval into an optional one "
            "([2026] VJS-CC-BOLTRIG-OPERATOR-SEAT-001, D2)"
        )
