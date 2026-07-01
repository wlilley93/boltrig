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

from boltrig.identity.rbac import DEFAULT_ROLE, grants_for_scope
from boltrig.kernel.app import Principal
from boltrig.models import Channel

# A channel-bound sender operates at a console tier (parity with the Cloudflare
# Access resolver, so identity means the same thing on every ingress surface).
CHANNEL_TIERS: tuple[str, ...] = ("superadmin", "admin", "member")


async def resolve_channel_principal(
    store, channel: Channel, external_user_id: str
) -> Principal | None:
    """Resolve a VERIFIED channel sender to a Principal via its binding row, or
    ``None`` if the sender is unbound (the caller applies ``unpaired_behavior``).

    Identity is kernel-authoritative (decision 0003): the tenant comes from the
    already-verified channel, the role from the binding row - never the message
    body. An unbound sender, or a binding to an unknown tier, is denied
    fail-closed (K-13).
    """
    binding = await store.get_channel_binding(
        channel.tenant_id, channel.id, external_user_id
    )
    if binding is None:
        return None
    role = binding.role if binding.role in CHANNEL_TIERS else DEFAULT_ROLE
    if role in (DEFAULT_ROLE, "none", ""):
        return None
    scope = {"all": True}  # tenant-wide; can_author + the HITL gate differentiate tiers
    return Principal(
        tenant_id=channel.tenant_id,
        subject=binding.subject,
        grants=grants_for_scope(scope),
        role=role,
        actor_tier="human",
        scope=scope,
    )
