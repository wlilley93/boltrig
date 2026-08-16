"""Postgres projections for camera bindings and signed semantic leases."""

from boltrig.camera_leases import CameraBinding, CameraLease


def camera_binding_row(row):
    if row is None:
        return None
    return CameraBinding(
        tenant_id=row["tenant_id"],
        device_id=row["device_id"],
        camera_id=row["camera_id"],
        descriptor_fingerprint=row["descriptor_fingerprint"],
        owner_id=row["owner_id"],
        connection_state=row["connection_state"],
        ptz_get_state=row["ptz_get_state"],
        ptz_set_state=row["ptz_set_state"],
        label=row["label"],
        manufacturer=row["manufacturer"],
        product=row["product"],
        transport=row["transport"],
        capabilities=dict(row["capabilities"] or {}),
        evidence=list(row["evidence"] or []),
        updated_at=row["updated_at"],
    )


def camera_lease_row(row):
    if row is None:
        return None
    return CameraLease(
        id=row["id"],
        tenant_id=row["tenant_id"],
        device_id=row["device_id"],
        camera_id=row["camera_id"],
        owner_id=row["owner_id"],
        verb=row["verb"],
        action=dict(row["action"]),
        action_digest=row["action_digest"],
        approval_id=row["approval_id"],
        issued_at=row["issued_at"],
        expires_at=row["expires_at"],
        signature=row["signature"],
        signing_key_id=row["signing_key_id"],
        status=row["status"],
        claim_token_hash=row["claim_token_hash"],
        claim_expires_at=row["claim_expires_at"],
        claimed_at=row["claimed_at"],
        settled_at=row["settled_at"],
        receipt=dict(row["receipt"]) if row["receipt"] is not None else None,
    )
