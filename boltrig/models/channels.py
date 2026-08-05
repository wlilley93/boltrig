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
from typing import Any

from .base import TenantId, UserId
from .channel_providers import (
    CHANNEL_PLATFORMS as CHANNEL_PLATFORMS,
    SOCKET_PLATFORMS as SOCKET_PLATFORMS,
    WEBHOOK_PLATFORMS as WEBHOOK_PLATFORMS,
    transport_for as transport_for,
)

# What to do with a verified sender that has no channel binding yet.
UNPAIRED_BEHAVIORS: tuple[str, ...] = ("reject", "ignore", "pair")


@dataclass
class Channel:
    """A connected channel instance for one tenant. Authored via ``channel.connect``."""

    id: str
    tenant_id: TenantId
    platform: str  # slack | discord | whatsapp | telegram | signal | voice | webhook | msteams
    name: str
    transport: str  # "webhook" | "socket" (derived from platform via transport_for)
    # SEC-04: a reference into the secret store (webhook signing secret, bot token,
    # app credentials) - never plaintext, never returned to an agent.
    credential_ref: str | None = None
    # policy-as-data: allowed_chats, thread_ceilings, home_channel, dm behaviour
    # overrides, etc. ``allowed_chats`` is opt-in allowlist mode: its absence
    # preserves historical intake behaviour, while its presence fails closed on
    # an unknown/missing chat. ``thread_ceilings`` maps a chat/thread id to a
    # GrantSet-shaped allow/deny snapshot that can only narrow the sender.
    # Addressing (Phase 2, routing data - never authority):
    #   config["addressing"] = {
    #     "default_target": "cos",              # tier-1 chief of staff (default)
    #     "routes": {"<chat/thread id>": "<target>"},  # permanent department
    #                                           # or "workflow:<wf_id>" (SEC-178)
    #     "thread_field": "chat",               # body field holding the chat id
    #   }
    # Self-serve onboarding (SEC-180, OFF by default - absent key means the
    # unpaired_behavior below applies exactly as before):
    #   config["self_onboard"] = {
    #     "role": "member",        # constrained tier only (SELF_ONBOARD_ROLES);
    #                              # anything higher disables onboarding fail-closed
    #     "scope": {...},          # visibility scope for the synthetic subject
    #     "welcome": "Hi ...",     # optional static reply, enqueued to the outbox
    #   }
    config: dict[str, Any] = field(default_factory=dict)
    unpaired_behavior: str = "reject"  # reject | ignore | pair
    enabled: bool = True
    created_at: datetime | None = None


@dataclass
class ChannelGatewayStatus:
    """Last durable, secret-free observation reported by a severed gateway."""

    tenant_id: TenantId
    channel_id: str
    gateway_id: str
    desired_revision: str
    observed_revision: str
    status: str
    reason_code: str | None = None
    observed_at: datetime | None = None


@dataclass
class ChannelGatewayLease:
    """Kernel-private ownership fence for one socket channel.

    ``owner_lease_id`` is the opaque id of the short-lived MCP run token. It is
    persisted for compare-and-swap ownership but never projected to a browser,
    audit detail, provider adapter, or gateway status response.
    """

    tenant_id: TenantId
    channel_id: str
    gateway_id: str
    owner_lease_id: str
    lease_expires_at: datetime
    updated_at: datetime | None = None


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
class ChannelOutboxMessage:
    """A durable outbound delivery for a socket-class channel (decision 0003,
    Phase 2). The kernel enqueues; the severed sidecar claims (leased, one
    winner), delivers to the platform over its held connection, then acks
    (terminal) or fails (retry with backoff, terminal after the attempt cap).
    Tenant-scoped (RLS); the payload carries no credential - platform secrets
    are injected into the sidecar at connect time, never stored here."""

    id: str
    tenant_id: TenantId
    channel_id: str
    # the send: {"text", "target", ...} - ``target`` is the thread/route key the
    # platform adapter delivers to (a chat/thread id); it is what round-trip
    # integrity hangs on: a notification enqueued for an intake-originated run
    # carries the originating thread here (SEC-179).
    payload: dict[str, Any]
    status: str = "pending"  # pending | in_flight | delivered | failed
    attempts: int = 0
    lease_owner: str | None = None  # the claiming sidecar's token lease id
    lease_expires_at: datetime | None = None
    next_attempt_at: datetime | None = None  # retry backoff gate (None = due now)
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class ChannelDeliveryReceipt:
    """Secret- and payload-free caller projection of one outbound delivery."""

    id: str
    tenant_id: TenantId
    channel_id: str
    status: str  # queued | in_flight | retryable | delivered | terminal_failed
    attempts: int
    safe_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    next_attempt_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            "queued",
            "in_flight",
            "retryable",
            "delivered",
            "terminal_failed",
        }:
            raise ValueError("channel delivery receipt status is invalid")
        if self.attempts < 0:
            raise ValueError("channel delivery attempts cannot be negative")
        if self.safe_reason not in {None, "delivery_failed"}:
            raise ValueError("channel delivery reason is not public")
        if self.status not in {"retryable", "terminal_failed"} and self.safe_reason:
            raise ValueError("successful or active delivery cannot have a failure reason")


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
