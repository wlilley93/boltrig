"""Default-organisation backfill ([2026] VJS-COUNTY 8, D1).

The ORGANISATION is the tenant boundary: an org row's id IS the tenant_id. An
existing single-tenant deployment provisioned before COUNTY 8 has rows keyed on a
``tenant_id`` but no ``organisations`` row for it. This helper backfills an
IMPLICIT default org for such a tenant so that every existing tenant_id resolves
to an organisation.

ADDITIVE + IDEMPOTENT: ``ensure_default_org`` is a no-op when the org already
exists (``create_org`` inserts ON CONFLICT DO NOTHING), so it is safe to call on
every boot / on every provisioning path. It never mutates an existing org.
"""

from __future__ import annotations

import re

from boltrig.models import Organisation

# Slugs are url-safe: lowercase alphanumerics and single hyphens. A tenant_id is
# already an opaque handle, so we derive a best-effort slug from it and fall back
# to the raw tenant_id when nothing survives normalisation.
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def default_org_slug(tenant_id: str) -> str:
    """A deterministic url-safe slug for a tenant's implicit default org."""
    slug = _SLUG_STRIP.sub("-", tenant_id.strip().lower()).strip("-")
    return slug or tenant_id


def default_org_for(tenant_id: str, *, name: str | None = None) -> Organisation:
    """Build (without persisting) the implicit default org for a tenant_id. The
    org id IS the tenant_id (D1)."""
    return Organisation(
        id=tenant_id,
        name=name or tenant_id,
        slug=default_org_slug(tenant_id),
    )


async def ensure_default_org(
    store, tenant_id: str, *, name: str | None = None
) -> Organisation:
    """Ensure a default organisation row exists for ``tenant_id`` and return it.

    Idempotent: if the org already exists it is returned unchanged; otherwise an
    implicit default org (id == tenant_id) is created. ``create_org`` is itself
    ON CONFLICT DO NOTHING, so this is safe under a concurrent first-boot race -
    the loser simply re-reads the winner's row.
    """
    existing = await store.get_org(tenant_id)
    if existing is not None:
        return existing
    org = default_org_for(tenant_id, name=name)
    await store.create_org(org)
    # Re-read so a concurrent creator's row (not ours) is the one returned.
    return await store.get_org(tenant_id) or org
