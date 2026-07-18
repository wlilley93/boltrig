"""Fail-closed validation of model-proxy grant store return values."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import NoReturn

from boltrig.fleet.domain.model_proxy_grant import (
    ModelProxyGrantConflict,
    ModelProxyGrantDraft,
    ModelProxyGrantReceipt,
    ModelProxyGrantStatus,
    StoredModelProxyGrant,
)
from boltrig.fleet.domain.model_proxy_scope import ModelProxyGrantBinding


def require_insert_projection(value: object, draft: ModelProxyGrantDraft) -> StoredModelProxyGrant:
    """Return an isolated exact copy only when every draft projection matches."""
    if type(draft) is not ModelProxyGrantDraft or type(value) is not StoredModelProxyGrant:
        _malformed()
    record = _validated_copy(value)
    exact_lifetime = timedelta(seconds=draft.ttl_seconds)
    if (
        record.grant_id != draft.grant_id
        or record.binding != draft.binding
        or not secrets.compare_digest(record.bearer_digest, draft.bearer_digest)
        or not secrets.compare_digest(record.startup_request_digest, draft.startup_request_digest)
        or record.generation != draft.generation
        or record.status is not ModelProxyGrantStatus.ACTIVE
        or record.expires_at - record.issued_at != exact_lifetime
    ):
        _malformed()
    return StoredModelProxyGrant(
        grant_id=draft.grant_id,
        binding=draft.binding,
        bearer_digest=draft.bearer_digest,
        startup_request_digest=draft.startup_request_digest,
        issued_at=record.issued_at,
        expires_at=record.expires_at,
        generation=draft.generation,
    )


def require_active_projection(
    value: object,
    *,
    receipt: ModelProxyGrantReceipt,
    binding: ModelProxyGrantBinding,
    bearer_digest: str,
    startup_request_digest: str,
) -> bool:
    """Accept None as inactive; reject every malformed non-None projection."""
    if value is None:
        return False
    if (
        type(receipt) is not ModelProxyGrantReceipt
        or type(binding) is not ModelProxyGrantBinding
        or type(value) is not StoredModelProxyGrant
    ):
        _malformed()
    record = _validated_copy(value)
    if (
        record.grant_id != receipt.grant_id
        or record.binding != binding
        or record.issued_at != receipt.issued_at
        or record.expires_at != receipt.expires_at
        or record.generation != receipt.generation
        or record.status is not ModelProxyGrantStatus.ACTIVE
        or not secrets.compare_digest(record.bearer_digest, bearer_digest)
        or not secrets.compare_digest(record.startup_request_digest, startup_request_digest)
    ):
        _malformed()
    return True


def _validated_copy(record: StoredModelProxyGrant) -> StoredModelProxyGrant:
    try:
        return StoredModelProxyGrant(
            grant_id=record.grant_id,
            binding=record.binding,
            bearer_digest=record.bearer_digest,
            startup_request_digest=record.startup_request_digest,
            issued_at=record.issued_at,
            expires_at=record.expires_at,
            generation=record.generation,
            status=record.status,
            revoked_at=record.revoked_at,
            revocation_reason=record.revocation_reason,
        )
    except Exception:
        _malformed()


def _malformed() -> NoReturn:
    raise ModelProxyGrantConflict("model-proxy store returned a malformed projection") from None


__all__ = ["require_active_projection", "require_insert_projection"]
