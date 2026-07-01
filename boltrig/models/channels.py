"""Channel gateway domain (Channels feature; decision 0003, VJS First Instance).

A channel is a GOVERNED connection to an external messaging platform (Slack,
Discord, WhatsApp, Telegram, Signal, MS Teams, email, generic signed webhook).
Connecting/configuring a channel is an authored, audited, per-tenant act; every
inbound message re-enters the ONE dispatch chokepoint as a governed
``kernel.invoke``. Credentials are kernel-only (SEC-04/05): a Channel holds a
``credential_ref``, never plaintext.

Transport classes (the court's hybrid split, decision 0003):
  - ``webhook`` - request/response, terminated by a thin in-kernel route (Phase 1).
  - ``socket``  - a persistent connection, terminated by the severed sidecar (Phase 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .base import TenantId, UserId

# The webhook (request/response) class is in-kernel (Phase 1); the socket
# (persistent-connection) class is the severed sidecar (Phase 2). A platform's
# transport is fixed here so the ingress path is chosen deterministically.
WEBHOOK_PLATFORMS: tuple[str, ...] = ("webhook", "msteams")
SOCKET_PLATFORMS: tuple[str, ...] = (
    "slack",
    "discord",
    "telegram",
    "whatsapp",
    "signal",
)
CHANNEL_PLATFORMS: tuple[str, ...] = WEBHOOK_PLATFORMS + SOCKET_PLATFORMS

# What to do with a verified sender that has no channel binding yet.
UNPAIRED_BEHAVIORS: tuple[str, ...] = ("reject", "ignore", "pair")


def transport_for(platform: str) -> str:
    """The transport class ('webhook' | 'socket') for a platform (decision 0003)."""
    return "webhook" if platform in WEBHOOK_PLATFORMS else "socket"


@dataclass
class Channel:
    """A connected channel instance for one tenant. Authored via ``channel.connect``."""

    id: str
    tenant_id: TenantId
    platform: str  # slack | discord | whatsapp | telegram | signal | webhook | msteams
    name: str
    transport: str  # "webhook" | "socket" (derived from platform via transport_for)
    # SEC-04: a reference into the secret store (webhook signing secret, bot token,
    # app credentials) - never plaintext, never returned to an agent.
    credential_ref: str | None = None
    # policy-as-data: allowed_chats, home_channel, dm behaviour overrides, etc.
    config: dict = field(default_factory=dict)
    unpaired_behavior: str = "reject"  # reject | ignore | pair
    enabled: bool = True
    created_at: datetime | None = None


@dataclass
class ChannelBinding:
    """A verified external sender mapped to an internal identity, within a channel's
    tenant. The resolver reads these RLS rows to build a Principal - identity is
    kernel-authoritative, never taken from the message body (decision 0003)."""

    id: str
    tenant_id: TenantId
    channel_id: str
    platform: str
    external_user_id: str  # the verified platform sender (Slack id / snowflake / phone)
    subject: UserId  # the internal Boltrig subject this sender acts as
    role: str  # the console tier the sender operates at (member | admin | superadmin)
    created_at: datetime | None = None


@dataclass
class ChannelPairing:
    """A one-time code to bind an unknown sender to an internal identity. Hashed at
    rest (SEC-05), TTL-bounded, rate-limited, lockout-guarded (decision 0003). The
    target (subject + role) travels on the pairing so consume can mint the binding
    without re-trusting the message body."""

    id: str
    tenant_id: TenantId
    channel_id: str
    code_hash: str  # SEC-05: sha256 of the one-time code, never the plaintext
    external_user_id: str
    subject: UserId  # the internal identity a successful pairing binds the sender to
    role: str  # the console tier the bound sender operates at (member | admin | superadmin)
    status: str = "pending"  # pending | consumed | expired
    attempts: int = 0
    expires_at: datetime | None = None
    created_at: datetime | None = None
