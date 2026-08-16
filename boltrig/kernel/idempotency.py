"""Identity-bound, single-owner idempotency coordination for dispatch."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from boltrig.models import (
    IdempotencyConflict,
    IdempotencyMode,
    InvocationContext,
    SchemaValidationError,
)
from boltrig.store import Store
from boltrig.store.idempotency_contract import IdempotencyClaimStatus

_LEASE_SECONDS = 300
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "invite_token",
        "password",
        "refresh_token",
        "secret",
        "set_cookie",
        "token",
    }
)
_SECRET_VALUE_PREFIXES = (
    "bearer ",
    "basic ",
    "boltrig_invite_",
    "ghp_",
    "github_pat_",
    "sk-",
    "xoxb-",
    "xoxp-",
)


@dataclass(frozen=True)
class IdempotencyRun:
    tenant_id: str
    key: str
    owner_token: str


@dataclass(frozen=True)
class IdempotencyReplay:
    result: dict[str, Any]


def _normalize_sensitive_key(key: str) -> str:
    # Camel-case to snake_case with ACRONYM handling: the previous
    # split-before-every-capital turned "APIKey" into "a_p_i_key", which
    # matched neither the exact set nor any _token/_api_key suffix, so an
    # adapter output like {"APIKey": ...} skipped the uncacheable/redaction
    # check entirely. "APIKey" -> "api_key", "apiKey" -> "api_key".
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", key)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower().replace("-", "_")


def sensitive_key(key: Any) -> bool:
    normalized = _normalize_sensitive_key(str(key))
    return (
        normalized in _SENSITIVE_KEYS
        or normalized.endswith("_password")
        or normalized.endswith("_secret")
        or normalized.endswith("_token")
        or normalized.endswith("_api_key")
        or normalized.endswith("_authorization")
        or normalized.endswith("_cookie")
    )


def secret_shaped(value: Any) -> bool:
    if isinstance(value, dict):
        return any(sensitive_key(key) or secret_shaped(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(secret_shaped(item) for item in value)
    if not isinstance(value, str):
        return False
    lowered = value.strip().lower()
    if lowered.startswith(_SECRET_VALUE_PREFIXES):
        return True
    parts = value.split(".")
    return len(parts) == 3 and all(
        len(part) >= 8 and re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in parts
    )


def canonical_request_hash(params: dict[str, Any]) -> str:
    try:
        body = json.dumps(
            params,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError("idempotent params must be canonical JSON") from exc
    return hashlib.sha256(body).hexdigest()


class IdempotencyCoordinator:
    def __init__(self, store: Store) -> None:
        self._store = store

    async def claim(
        self,
        key: str | None,
        noun: str,
        verb: str,
        params: dict[str, Any],
        context: InvocationContext,
        mode: IdempotencyMode,
    ) -> IdempotencyRun | IdempotencyReplay | None:
        if key is None:
            return None
        if mode == IdempotencyMode.DISABLED:
            raise IdempotencyConflict(f"verb '{verb}' does not support replay caching")
        owner_token = uuid.uuid4().hex
        claim = await self._store.idempotency_claim(
            context.tenant_id,
            key,
            actor=context.actor,
            on_behalf_of=context.on_behalf_of,
            workspace_id=context.workspace_id,
            noun=noun,
            verb=verb,
            request_hash=canonical_request_hash(params),
            owner_token=owner_token,
            lease_seconds=_LEASE_SECONDS,
        )
        if claim.status == IdempotencyClaimStatus.ACQUIRED:
            return IdempotencyRun(context.tenant_id, key, owner_token)
        if claim.status == IdempotencyClaimStatus.COMPLETED:
            return IdempotencyReplay(dict(claim.result or {}))
        messages = {
            IdempotencyClaimStatus.MISMATCH: "idempotency key is bound to a different identity or request",
            IdempotencyClaimStatus.IN_PROGRESS: "idempotency request is already in progress",
            IdempotencyClaimStatus.UNCERTAIN: "idempotency outcome is uncertain; reconciliation is required",
            IdempotencyClaimStatus.UNCACHEABLE: "idempotency result contained secret material and cannot be replayed",
        }
        raise IdempotencyConflict(messages[claim.status])

    async def start(self, run: IdempotencyRun | None) -> None:
        if run is None:
            return
        started = await self._store.idempotency_start(
            run.tenant_id, run.key, run.owner_token, _LEASE_SECONDS
        )
        if not started:
            raise IdempotencyConflict("idempotency claim ownership was lost")

    async def release(self, run: IdempotencyRun | None) -> None:
        if run is not None:
            await self._store.idempotency_release(run.tenant_id, run.key, run.owner_token)

    async def complete(self, run: IdempotencyRun | None, output: dict[str, Any]) -> None:
        if run is None:
            return
        if secret_shaped(output):
            saved = await self._store.idempotency_uncacheable(
                run.tenant_id, run.key, run.owner_token
            )
        else:
            saved = await self._store.idempotency_complete(
                run.tenant_id, run.key, run.owner_token, output
            )
        if not saved:
            raise IdempotencyConflict("idempotency completion ownership was lost")
