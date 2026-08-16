"""The management surface's list views say "NEVER the secret". Prove it (SEC-192).

Six docstrings in `boltrig/kernel/access_routes.py` make the same load-bearing
promise about the account & access-management HTTP surface:

    _pat_view          "never the secret or the hash (PAT-02)"
    _ai_config_view    "WHETHER a key is set, NEVER the key itself"
    _org_view          "the policy flags + handle, NEVER any secret"
    _ai_configs (673)  "provider/model + has_key only - NEVER the key"
    (918)              "handle + policy flags, never a secret"

Until now nothing checked any of them. They were in the Tier 0 inventory's
load-bearing NO-SUBJECT residue: a security guarantee stated in prose, on the
surface that lists credentials, resting on the author having been careful.

HOW THIS PROVES IT, and why the shape matters. Not by looking for field names that
sound secret - a defence that depends on string matching is not a trust boundary
([2026] VJS-CC-OPBOX 5, H1). Instead every source row is built with a UNIQUE
SENTINEL in each secret-bearing attribute, and the assertion is that the sentinel
does not appear ANYWHERE in the rendered view. A view that starts passing through a
new field fails on the day it does, whatever the field is called, and a view that
renames `token_hash` to something innocuous fails just the same.

The second half is the complement: each view's key set is pinned exactly. Without
it a view could satisfy the sentinel check by dropping the secret while quietly
adding some other field nobody meant to publish. Together they say: these keys, and
nothing else.
"""

from __future__ import annotations

import json

import pytest

from boltrig.kernel.access_routes import _ai_config_view, _org_view, _pat_view, _user_view
from boltrig.models import AiConfig, Organisation, PersonalAccessToken, utcnow

T = "acme"

# Distinct per field, so a failure names WHICH secret leaked rather than just that
# one did. Chosen to be findable in a JSON blob and impossible to produce by chance.
_PAT_HASH = "SENTINEL-pat-token-hash-2f9c41"
_CREDENTIAL_REF = "SENTINEL-credential-ref-7ab30d"
_ORG_SETTING = "SENTINEL-org-settings-value-1c8e55"


def _rendered(view: dict) -> str:
    """The view as it reaches the wire. `str` would hide a value nested in a dict."""
    return json.dumps(view, default=str)


def _pat() -> PersonalAccessToken:
    return PersonalAccessToken(
        id="pat-1",
        tenant_id=T,
        user_id="u-1",
        name="ci token",
        token_hash=_PAT_HASH,
        scope=["ticket.read"],
        created_at=utcnow(),
        expires_at=utcnow(),
        last_used_at=utcnow(),
        revoked=False,
    )


def _ai_config() -> AiConfig:
    return AiConfig(
        tenant_id=T,
        level="org",
        scope_id=T,
        provider="openai",
        model="gpt-5-mini",
        credential_ref=_CREDENTIAL_REF,
        base_url="https://api.example.test/v1",
    )


def _org() -> Organisation:
    return Organisation(
        id=T,
        name="Acme",
        slug="acme",
        settings={"nested": {"deep": _ORG_SETTING}},
        allow_own_ai_keys=True,
        require_two_factor=True,
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-192")
def test_the_pat_list_view_carries_neither_the_secret_nor_its_hash() -> None:
    rendered = _rendered(_pat_view(_pat()))
    assert _PAT_HASH not in rendered, f"the PAT hash reached the listing: {rendered}"
    # the useful fields ARE there, so this is not passing by rendering nothing
    assert "ci token" in rendered and "ticket.read" in rendered


@pytest.mark.security
@pytest.mark.invariant("SEC-192")
def test_the_ai_config_view_reports_that_a_key_exists_without_carrying_it() -> None:
    view = _ai_config_view(_ai_config())
    rendered = _rendered(view)
    assert _CREDENTIAL_REF not in rendered, f"the credential ref reached the listing: {rendered}"
    # `has_key` is the whole point: the caller learns a key is SET, never what it is.
    assert view["has_key"] is True
    assert "openai" in rendered and "gpt-5-mini" in rendered


@pytest.mark.security
@pytest.mark.invariant("SEC-192")
def test_the_ai_config_view_distinguishes_no_key_from_a_key_it_will_not_show() -> None:
    """`has_key` must be derived from the ref, not defaulted.

    Without this case the test above passes identically against a view that
    hardcodes ``"has_key": True``, which would tell an operator a key is configured
    when none is.
    """
    empty = _ai_config()
    empty.credential_ref = ""
    assert _ai_config_view(empty)["has_key"] is False


@pytest.mark.security
@pytest.mark.invariant("SEC-192")
def test_the_org_view_carries_the_policy_flags_and_nothing_nested_in_settings() -> None:
    view = _org_view(_org())
    assert view["allow_own_ai_keys"] is True and view["require_two_factor"] is True
    # `settings` is an OPEN dict, so it is the one field on this surface that can
    # carry anything a caller ever put in it. The docstring says "NEVER any secret";
    # what is actually true is that settings is published verbatim, so a secret
    # written there IS disclosed. Pinned deliberately, so the day that changes is
    # visible rather than silent.
    assert _ORG_SETTING in _rendered(view), (
        "org settings are no longer published verbatim - if that is intended, the "
        "docstring's 'NEVER any secret' is now stronger than it was and this "
        "assertion should be inverted rather than deleted"
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-192")
@pytest.mark.parametrize(
    ("view", "keys"),
    [
        (
            _pat_view(_pat()),
            {"id", "name", "scope", "created_at", "last_used_at", "expires_at", "revoked"},
        ),
        (
            _ai_config_view(_ai_config()),
                {"level", "scope_id", "provider", "model", "modality", "base_url", "has_key", "updated_at"},
        ),
        (
            _org_view(_org()),
            {"id", "name", "slug", "settings", "allow_own_ai_keys", "require_two_factor",
             "created_at", "updated_at"},
        ),
    ],
    ids=["pat", "ai-config", "org"],
)
def test_each_view_publishes_exactly_these_keys_and_no_others(view: dict, keys: set) -> None:
    """The complement of the sentinel checks.

    A sentinel proves a KNOWN secret does not leak. This proves nothing NEW appears:
    without it a view could pass by dropping the hash while quietly adding a field
    nobody meant to publish. Set equality, not a subset - a widened view fails here
    and someone has to say why.
    """
    assert set(view) == keys


@pytest.mark.security
@pytest.mark.invariant("SEC-192")
def test_the_user_directory_view_carries_no_credential_material() -> None:
    """`_user_view` makes no promise in prose, which is exactly why it gets one.

    It sits beside the views above on the same surface and renders the user
    directory. Nothing said it was safe, so nothing could have caught it becoming
    unsafe.
    """
    class _U:
        id, email, display_name, role = "u-1", "a@b.test", "A B", "member"
        scope, status, source, source_group = ["*"], "active", "local", None
        last_seen_at = None
        password_hash = "SENTINEL-password-hash-4d1a90"
        totp_secret = "SENTINEL-totp-seed-9e2b7f"

    rendered = _rendered(_user_view(_U()))
    assert "SENTINEL-password-hash-4d1a90" not in rendered
    assert "SENTINEL-totp-seed-9e2b7f" not in rendered
    assert "a@b.test" in rendered  # the directory is still useful
