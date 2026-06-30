"""Conversation-scoped model binding for an upstream gateway (Round Six, gap 3.2).

``model_router`` answers a compliance question (may this data reach this endpoint
- SEC-12), not a cost/cache question. A cost-aware AI gateway (Bifrost or
equivalent) sits in front of the providers and caches on the *prompt prefix*; for
that cache to stay warm across the turns of one conversation, every turn of that
conversation must (a) hit the gateway and (b) resolve to the same model. The
binding unit is therefore the **conversation**, not the run: ``run_id`` is minted
fresh every turn and is the wrong key.

This module is the read-side seam only. It has no authorization role and holds no
capability/credential logic (P1): it decides *which provider endpoint a standard
call is routed through and which model it pins to*, nothing more. It is bypassed
entirely for sensitive-classified data so the sensitive->local residency guard
(``model_router``) is never weakened (SEC-43/SEC-47).

When no gateway URL is configured the seam is inert and endpoint resolution
behaves exactly as before.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import timedelta

from nankle.models import ModelEndpoint, utcnow


class ModelGateway:
    """An in-memory, TTL-bounded ``conversation_id -> model`` binding.

    The binding is cache affinity, not state of record: it keeps a conversation
    pinned to one model for the gateway's cache window. The TTL is synchronised to
    the gateway's own cache TTL so a binding never outlives (pinning a cold cache)
    or under-lives (re-routing a warm one) the cache it exists to track.
    """

    def __init__(self, *, ttl_seconds: int = 900) -> None:
        self._ttl = timedelta(seconds=max(1, ttl_seconds))
        self._bindings: dict[str, tuple[str, object]] = {}

    def resolve(self, conversation_id: str) -> str | None:
        """The live bound model for a conversation, or ``None`` if unbound/expired."""
        entry = self._bindings.get(conversation_id)
        if entry is None:
            return None
        model, expires_at = entry
        if utcnow() >= expires_at:
            self._bindings.pop(conversation_id, None)
            return None
        return model

    def bind(self, conversation_id: str, model: str) -> str:
        """Pin (or refresh the TTL of) a conversation's model; returns the model
        now in force for the conversation. An existing live binding wins so the
        conversation stays on its cached model even if capability selection would
        otherwise pick a different one this turn."""
        existing = self.resolve(conversation_id)
        chosen = existing or model
        self._bindings[conversation_id] = (chosen, utcnow() + self._ttl)
        return chosen


def gateway_config() -> dict[str, object]:
    """Gateway wiring from the environment (manifest ``gateway`` section maps to
    these vars, like ``runtimes.pi``). ``base_url`` unset => seam inert."""
    return {
        "base_url": os.environ.get("NANKLE_MODEL_GATEWAY_URL") or None,
        "ttl_seconds": int(os.environ.get("NANKLE_MODEL_GATEWAY_TTL", "900")),
    }


def apply_gateway(
    endpoint: ModelEndpoint | None,
    *,
    gateway_url: str | None,
    binding: ModelGateway | None,
    conversation_id: str | None,
    sensitive: bool,
) -> ModelEndpoint | None:
    """Route a resolved endpoint through the gateway for a conversation.

    Returns a copy of ``endpoint`` with ``base_url`` pointed at the gateway and
    ``model`` pinned to the conversation's bound model. The original endpoint is
    returned unchanged when any precondition is not met:

    * no gateway configured (``gateway_url``/``binding`` unset), or
    * the call is not part of a conversation (no ``conversation_id``), or
    * the data is **sensitive** - sensitive traffic must reach its local
      endpoint directly and is never re-routed through a shared gateway
      (residency, SEC-43/SEC-47), or
    * there is no endpoint to route.
    """
    if endpoint is None or sensitive or not gateway_url or binding is None or not conversation_id:
        return endpoint
    pinned_model = binding.bind(conversation_id, endpoint.model)
    return replace(endpoint, base_url=gateway_url, model=pinned_model)
