"""Channel gateway: the ChannelPrincipalResolver (decision 0003).

An inbound channel event is resolved to a governed Principal ENTIRELY kernel-side.
The tenant comes from the verified channel (never the payload); the verified
external sender is mapped to an internal identity via a tenant-scoped
ChannelBinding row; an unmapped sender is denied fail-closed (the caller then
applies the channel's ``unpaired_behavior``). The resolved Principal flows into
the ONE chokepoint exactly like any other caller (K-3, authenticated-by-
construction), so a channel path never bypasses grants / HITL / audit.
"""

from __future__ import annotations

from boltrig.identity.provisioning import current_grants_for_user
from boltrig.identity.rbac import DEFAULT_ROLE, WORKSPACE_ROLE_CEILINGS
from boltrig.kernel.app import Principal
from boltrig.models import Channel

# A channel-bound sender operates at a console tier (parity with the Cloudflare
# Access resolver, so identity means the same thing on every ingress surface).
CHANNEL_TIERS: tuple[str, ...] = ("superadmin", "admin", "member")

# A channel sender's grant ceiling is derived from the binding's RECORDED tier,
# mapped onto the workspace-role grant ceilings (rbac.WORKSPACE_ROLE_CEILINGS -
# the one role -> grant-ceiling table the rest of the system uses); superadmin
# is the owner tier. The ceiling is never the bare wildcard for every tier: a
# member-bound sender operates but cannot configure/administer (``control.*``
# denied), and when the bound subject has a user record their CURRENT grants cap
# the ceiling further - exactly the way a PAT is capped (SEC-34).
_TIER_CEILING_ROLE = {"superadmin": "owner", "admin": "admin", "member": "member"}


async def resolve_channel_principal(
    store, channel: Channel, external_user_id: str
) -> Principal | None:
    """Resolve a VERIFIED channel sender to a Principal via its binding row, or
    ``None`` if the sender is unbound (the caller applies ``unpaired_behavior``).

    Identity is kernel-authoritative (decision 0003): the tenant comes from the
    already-verified channel, the role from the binding row - never the message
    body. An unbound sender, or a binding to an unknown tier, is denied
    fail-closed (K-13).

    The grant ceiling is never ``*``: it is the recorded tier's ceiling, and
    when the bound subject has a user record that record is authoritative for
    current role/scope/status (US-USR-03) - a deactivated user's channel
    identity dies with it, and an active user's current grants intersect the
    tier ceiling DOWN (SEC-34 parity with ``resolve_pat_principal``).
    """
    binding = await store.get_channel_binding(
        channel.tenant_id, channel.id, external_user_id
    )
    if binding is None:
        return None
    role = binding.role if binding.role in CHANNEL_TIERS else DEFAULT_ROLE
    if role in (DEFAULT_ROLE, "none", ""):
        return None
    ceiling = WORKSPACE_ROLE_CEILINGS[_TIER_CEILING_ROLE[role]]
    user = await store.get_user(channel.tenant_id, binding.subject)
    if user is not None:
        if user.status != "active":
            return None  # a deactivated user's channel identity stops working at once
        grants = current_grants_for_user(user).intersect(ceiling)
        scope = user.scope or {}
    else:
        # A bare subject (no user record) still gets no wildcard: the recorded
        # tier's ceiling alone (a member operates; ``control.*`` is denied).
        grants = ceiling
        scope = {}
    return Principal(
        tenant_id=channel.tenant_id,
        subject=binding.subject,
        grants=grants,
        role=role,
        actor_tier="human",
        scope=scope,
    )
