"""Row projections shared by the durable device store."""

from boltrig.models.devices import DeviceLease, DeviceRoot, EnrolledDevice


def device_row(row):
    if row is None:
        return None
    return EnrolledDevice(
        id=row["id"], tenant_id=row["tenant_id"], owner_id=row["owner_id"],
        label=row["label"], public_key=row["public_key"],
        public_key_fingerprint=row["public_key_fingerprint"],
        lease_verify_key_id=row["lease_verify_key_id"],
        availability_mode=row["availability_mode"], presence=row["presence"],
        session_token_hash=row["session_token_hash"],
        session_expires_at=row["session_expires_at"],
        last_seen_at=row["last_seen_at"], revoked_at=row["revoked_at"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def root_row(row):
    if row is None:
        return None
    return DeviceRoot(
        id=row["id"], tenant_id=row["tenant_id"], device_id=row["device_id"],
        label=row["label"], scope=row["scope"],
        command_enabled=row["command_enabled"], git_enabled=row["git_enabled"],
        created_at=row["created_at"], revoked_at=row["revoked_at"],
    )


def lease_row(row):
    if row is None:
        return None
    return DeviceLease(
        id=row["id"], tenant_id=row["tenant_id"], device_id=row["device_id"],
        root_id=row["root_id"], owner_id=row["owner_id"], verb=row["verb"],
        action=dict(row["action"]), action_digest=row["action_digest"],
        approval_id=row["approval_id"], issued_at=row["issued_at"],
        expires_at=row["expires_at"], signature=row["signature"],
        signing_key_id=row["signing_key_id"], status=row["status"],
        claim_token_hash=row["claim_token_hash"],
        claim_expires_at=row["claim_expires_at"], claimed_at=row["claimed_at"],
        settled_at=row["settled_at"],
        receipt=dict(row["receipt"]) if row["receipt"] is not None else None,
    )
