"""One provider's Bifrost key must not claim the id another provider needs.

Bifrost provider-key ids are GLOBAL, not scoped per provider, while the GET that
checks for an existing key IS scoped. Deriving the id from scope alone therefore
produced a trap with no exit:

    GET  /api/providers/cerebras/keys/bt-7dc143...  -> 404  (not under cerebras)
    POST /api/providers/cerebras/keys               -> 409  (id exists, under zai)

and the 409 was reported as "the key could not be saved; check it and try
again", blaming the key for a collision it had no part in. Measured on dev
2026-08-24: `zai-coding-plan` held `bt-7dc143bd478d60d59b2dadd7bd80d874` while
`/api/providers/cerebras/keys` reported `total: 0`, so there was no cerebras key
to conflict with -- only the id.

The consequence is the one the screen was reported for: the FIRST provider a
tenant binds locks out every other one until someone deletes the row by hand.
"""

from __future__ import annotations

from dataclasses import dataclass

from boltrig.identity.bifrost_user_binding import (
    _binding_ids,
    binding_credential_ref,
)


@dataclass(frozen=True)
class _Resolution:
    level: str = "workspace"
    scope_id: str = "ws-1"
    modality: str = "text"


TENANT = "tenant-a"


def test_two_providers_at_one_scope_get_different_bifrost_ids() -> None:
    res = _Resolution()
    _, zai_key, zai_vk = _binding_ids(TENANT, res, "zai-coding-plan")
    _, cerebras_key, cerebras_vk = _binding_ids(TENANT, res, "cerebras")

    assert zai_key != cerebras_key, (
        "both providers want the same global Bifrost key id, so binding the "
        "second returns 409 Conflict"
    )
    assert zai_vk != cerebras_vk


def test_the_credential_ref_does_not_move_with_the_provider() -> None:
    """The ref addresses OUR row for this scope, one per scope regardless of who
    serves it. Folding the provider in would orphan every stored binding, so the
    fix must be visible in the Bifrost ids and invisible here."""
    res = _Resolution()
    plain = binding_credential_ref(TENANT, res)
    for provider in ("zai-coding-plan", "cerebras", "openai"):
        ref, _, _ = _binding_ids(TENANT, res, provider)
        assert ref == plain, f"{provider} moved the credential ref"


def test_ids_still_separate_scope_and_modality() -> None:
    """The provider is ADDED to what the id distinguishes, not substituted for
    it: a fix that made every scope share one id would trade this bug for a
    cross-scope one."""
    text = _binding_ids(TENANT, _Resolution(modality="text"), "openai")
    vision = _binding_ids(TENANT, _Resolution(modality="vision"), "openai")
    other_scope = _binding_ids(TENANT, _Resolution(scope_id="ws-2"), "openai")
    other_tenant = _binding_ids("tenant-b", _Resolution(), "openai")
    base = _binding_ids(TENANT, _Resolution(), "openai")

    ids = {base[1], text[1], vision[1], other_scope[1], other_tenant[1]}
    # base and text are the same resolution, so four distinct ids from five.
    assert base[1] == text[1]
    assert len(ids) == 4, ids


def test_the_id_shape_bifrost_accepts_is_preserved() -> None:
    """`bt-` + 32 hex, and the virtual key `boltrig-` + 24. Both are validated
    by safe_identifier downstream, so a longer digest would fail at the gateway
    rather than here."""
    _, key_id, vk_name = _binding_ids(TENANT, _Resolution(), "cerebras")
    assert key_id.startswith("bt-") and len(key_id) == 35
    assert vk_name.startswith("boltrig-") and len(vk_name) == 32
    assert all(c in "0123456789abcdef" for c in key_id[3:])
