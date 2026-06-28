"""Grant enforcement (P8, SEC-07, US-IAM-04, K-2).

A verb is authorised iff it is permitted by BOTH the caller's grants (the union
of its loaded skills' tool_grants, computed at spawn) AND the tenant's
permission ceiling. This is the intersection in US-IAM-04, evaluated per call.
Deny-dominance and fail-closed live in ``GrantSet.permits`` (K-5, K-13).
"""

from __future__ import annotations

from nankle.models import GrantMissing, InvocationContext, TenantPermissions, VerbId


class GrantChecker:
    def check(
        self, context: InvocationContext, verb_id: VerbId, tenant_perms: TenantPermissions
    ) -> None:
        """Raise ``GrantMissing`` unless the verb is authorised. Never returns a
        reason that identifies the backend (P4)."""
        if not tenant_perms.grants.permits(verb_id):
            raise GrantMissing(f"verb '{verb_id}' is outside the tenant permission ceiling")
        if not context.grants.permits(verb_id):
            raise GrantMissing(f"caller is not granted verb '{verb_id}'")
