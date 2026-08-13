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
from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta

from boltrig.config.environment import is_truthy

from boltrig.models import ModelEndpoint, utcnow


class ModelGateway:
    """An in-memory, TTL-bounded ``conversation_id -> model`` binding.

    The binding is cache affinity, not state of record: it keeps a conversation
    pinned to one model for the gateway's cache window. The TTL is synchronised to
    the gateway's own cache TTL so a binding never outlives (pinning a cold cache)
    or under-lives (re-routing a warm one) the cache it exists to track.

    The table is additionally size-bounded: conversation ids arrive per request,
    and TTL eviction on read alone would let a churn of one-turn conversations
    grow the dict without limit. At the bound, expired entries are swept first,
    then the earliest-expiring live ones (a live binding evicted early simply
    re-pins on the next turn - affinity, never correctness).
    """

    _MAX_BINDINGS = 4_096

    def __init__(self, *, ttl_seconds: int = 900) -> None:
        self._ttl = timedelta(seconds=max(1, ttl_seconds))
        self._bindings: dict[tuple[str, str], tuple[str, object]] = {}

    def resolve(self, tenant_id: str, conversation_id: str) -> str | None:
        """The live bound model for a conversation, or ``None`` if unbound/expired."""
        key = (tenant_id, conversation_id)
        entry = self._bindings.get(key)
        if entry is None:
            return None
        model, expires_at = entry
        if utcnow() >= expires_at:
            self._bindings.pop(key, None)
            return None
        return model

    def bind(self, tenant_id: str, conversation_id: str, model: str) -> str:
        """Pin (or refresh the TTL of) a conversation's model; returns the model
        now in force for the conversation. An existing live binding wins so the
        conversation stays on its cached model even if capability selection would
        otherwise pick a different one this turn."""
        key = (tenant_id, conversation_id)
        existing = self.resolve(tenant_id, conversation_id)
        chosen = existing or model
        if key not in self._bindings and len(self._bindings) >= self._MAX_BINDINGS:
            self._sweep()
        self._bindings[key] = (chosen, utcnow() + self._ttl)
        return chosen

    def rebind(self, tenant_id: str, conversation_id: str, model: str) -> str:
        """Replace one conversation's affinity after an explicit user choice.

        Ordinary policy/default resolution still calls :meth:`bind`, where the
        first live model wins.  An explicit, server-validated switch is a new
        cache decision and must replace that affinity; otherwise the UI would
        report model B while the gateway and trusted admission kept model A.
        """

        key = (tenant_id, conversation_id)
        if key not in self._bindings and len(self._bindings) >= self._MAX_BINDINGS:
            self._sweep()
        self._bindings[key] = (model, utcnow() + self._ttl)
        return model

    def _sweep(self) -> None:
        """Evict expired bindings, then earliest-expiring live ones under the bound."""
        now = utcnow()
        for key in [k for k, (_model, exp) in self._bindings.items() if now >= exp]:
            del self._bindings[key]
        while len(self._bindings) >= self._MAX_BINDINGS:
            oldest = min(self._bindings, key=lambda k: self._bindings[k][1])
            del self._bindings[oldest]


def gateway_config() -> dict[str, object]:
    """Gateway wiring from the environment (manifest ``gateway`` section maps to
    these vars, like ``runtimes.pi``). ``base_url`` unset => seam inert."""
    return {
        "base_url": os.environ.get("BOLTRIG_MODEL_GATEWAY_URL") or None,
        "ttl_seconds": int(os.environ.get("BOLTRIG_MODEL_GATEWAY_TTL", "900")),
    }


def apply_gateway(
    endpoint: ModelEndpoint | None,
    *,
    gateway_url: str | None,
    binding: ModelGateway | None,
    tenant_id: str,
    conversation_id: str | None,
    sensitive: bool,
    explicit_rebind: bool = False,
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
    pinned_model = (
        binding.rebind(tenant_id, conversation_id, endpoint.model)
        if explicit_rebind
        else binding.bind(tenant_id, conversation_id, endpoint.model)
    )
    return replace(endpoint, base_url=gateway_url, model=pinned_model)


# ── readiness posture ────────────────────────────────────────────────────────────────────────────
# Lives here rather than in api/readiness.py because the question is "what IS the gateway's state",
# which belongs to the gateway module, not to the thing that reports it - and because readiness.py
# was at the structure ratchet's 400-line limit, so a branch could not be added there without
# booking new debt to avoid a refactor.

#: The env var that puts the gateway in the REQUEST PATH. Distinct from the two health opt-ins.
GATEWAY_URL_ENV = "BOLTRIG_MODEL_GATEWAY_URL"
#: The opt-ins that arm an actual health PROBE of the gateway.  The flag is a
#: boolean; the URL is configured by presence.  They cannot share a generic
#: "non-empty" predicate because manifest export deliberately writes ``"0"``
#: for an explicit disabled posture.
GATEWAY_HEALTH_FLAG_ENV = "BOLTRIG_MODEL_GATEWAY_HEALTH"
GATEWAY_HEALTH_URL_ENV = "BOLTRIG_MODEL_GATEWAY_HEALTH_URL"


def gateway_posture(env: Mapping[str, str]) -> tuple[str, str | None]:
    """The gateway's readiness `(status, reason)` when no probe is armed.

    THE DEFECT THIS EXISTS TO FIX (found on Classical Visas, 2026-07-26). Readiness keyed the
    gateway check on the health OPT-INS alone, so a stack with
    ``BOLTRIG_MODEL_GATEWAY_URL=http://bifrost:8080/v1`` - every agent turn routing through it -
    reported ``model_gateway: "disabled"`` and read **ready** with bifrost face-down.

    ``disabled`` is indistinguishable from "this stack uses no model gateway", so an operator
    reading it concludes there is nothing to check. The true state is "there IS one, and nothing is
    watching it" - a different fact, and the one that would explain the outage.

    ``required`` is deliberately NOT changed here. Promoting a configured gateway to required is a
    deployment-contract change (it would flip live stacks to not_ready on a bifrost blip and change
    what orchestration does with them), and belongs to whoever owns that contract. This changes what
    the record SAYS, never what it decides.
    """
    if is_truthy(env.get(GATEWAY_HEALTH_FLAG_ENV)) or (
        env.get(GATEWAY_HEALTH_URL_ENV) or ""
    ).strip():
        return ("enabled", None)
    if (env.get(GATEWAY_URL_ENV) or "").strip():
        return ("unchecked", "configured_but_health_check_disabled")
    return ("disabled", "health_check_disabled")
