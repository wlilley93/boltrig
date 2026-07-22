"""Credential-at-rest sealing invariants (SEC-169).

The doctrine claims the application DB never holds plaintext credentials. The
store seam (``boltrig/store/sealing.py``) makes that TRUE: every dict written
through ``set_credential_ref`` rests in the store as a versioned Fernet
envelope (``{"sealed": "v1", "ct": ...}``), is unsealed transparently on
``get_credential_ref``, legacy plaintext rows keep reading, a rewrite re-seals,
and the kernel-held key is production-guarded (a missing/default key is FATAL
under a production signal; a dev default seals offline).

The at-rest pins below are white-box over ``InMemoryStore._creds`` - the raw
row exactly as it rests in the store - because the Store contract deliberately
never exposes the stored envelope through its reads.
"""

import json

import pytest

from boltrig.models import CredentialResolution
from boltrig.store import InMemoryStore
from boltrig.store.sealing import is_sealed, seal_ref, unseal_ref

T = "default"
SECRET = "JBSWY3DPEHPK3PXP"  # a TOTP-shaped base32 secret

_PRODUCTION_SIGNALS = ("BOLTRIG_PRODUCTION", "ENV", "BOLTRIG_ENV", "APP_ENV")


def _raw(store: InMemoryStore, cred_id: str) -> dict:
    """The at-rest row exactly as it sits in the store (white-box pin)."""
    return store._creds[(T, cred_id)]


def _dev_env(monkeypatch):
    """Pin a clean dev environment: no production signal, no operator key."""
    for var in _PRODUCTION_SIGNALS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("BOLTRIG_SEAL_KEY", raising=False)
    monkeypatch.delenv("BOLTRIG_SEAL_KEY_PREVIOUS", raising=False)


@pytest.mark.security
@pytest.mark.invariant("SEC-169")
async def test_inline_secret_is_sealed_at_rest_and_unsealed_on_read(monkeypatch):
    _dev_env(monkeypatch)
    store = InMemoryStore()
    await store.set_credential_ref(T, "cred-totp", {"secret": SECRET})
    # At rest: a versioned envelope, and the plaintext appears NOWHERE in it.
    raw = _raw(store, "cred-totp")
    assert is_sealed(raw)
    assert SECRET not in json.dumps(raw)
    # On read: the original dict, transparently.
    assert await store.get_credential_ref(T, "cred-totp") == {"secret": SECRET}


@pytest.mark.security
@pytest.mark.invariant("SEC-169")
async def test_reference_dicts_are_sealed_too(monkeypatch):
    _dev_env(monkeypatch)
    store = InMemoryStore()
    ref = {"store": "env", "ref": "BOLTRIG_TEST_KEY", "kind": "api_key"}
    await store.set_credential_ref(T, "cred-ref", ref)
    assert is_sealed(_raw(store, "cred-ref"))
    assert await store.get_credential_ref(T, "cred-ref") == ref


@pytest.mark.security
@pytest.mark.invariant("SEC-169")
async def test_legacy_plaintext_row_still_reads(monkeypatch):
    _dev_env(monkeypatch)
    store = InMemoryStore()
    # A row written before sealing existed (no envelope marker) ...
    store._creds[(T, "cred-legacy")] = {"secret": SECRET}
    assert await store.get_credential_ref(T, "cred-legacy") == {"secret": SECRET}


@pytest.mark.security
@pytest.mark.invariant("SEC-169")
async def test_rewrite_reseals_a_legacy_row(monkeypatch):
    _dev_env(monkeypatch)
    store = InMemoryStore()
    store._creds[(T, "cred-legacy")] = {"secret": SECRET}  # legacy plaintext row
    await store.set_credential_ref(T, "cred-legacy", {"secret": SECRET})
    raw = _raw(store, "cred-legacy")
    assert is_sealed(raw) and SECRET not in json.dumps(raw)


@pytest.mark.security
@pytest.mark.invariant("SEC-169")
async def test_a_wrong_key_fails_closed(monkeypatch):
    _dev_env(monkeypatch)
    monkeypatch.setenv("BOLTRIG_SEAL_KEY", "key-A-" + "x" * 40)
    store = InMemoryStore()
    await store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    monkeypatch.setenv("BOLTRIG_SEAL_KEY", "key-B-" + "y" * 40)
    with pytest.raises(CredentialResolution):
        await store.get_credential_ref(T, "cred-1")


@pytest.mark.security
@pytest.mark.invariant("SEC-169")
async def test_the_previous_key_decrypts_during_rotation(monkeypatch):
    _dev_env(monkeypatch)
    key_a, key_b = "key-A-" + "x" * 40, "key-B-" + "y" * 40
    monkeypatch.setenv("BOLTRIG_SEAL_KEY", key_a)
    store = InMemoryStore()
    await store.set_credential_ref(T, "cred-old", {"secret": SECRET})
    # Rotate: B active, A previous (decrypt-only). Old rows still read ...
    monkeypatch.setenv("BOLTRIG_SEAL_KEY", key_b)
    monkeypatch.setenv("BOLTRIG_SEAL_KEY_PREVIOUS", key_a)
    assert await store.get_credential_ref(T, "cred-old") == {"secret": SECRET}
    # ... and new writes seal under B alone (readable with the previous key gone).
    await store.set_credential_ref(T, "cred-new", {"secret": SECRET})
    monkeypatch.delenv("BOLTRIG_SEAL_KEY_PREVIOUS")
    assert await store.get_credential_ref(T, "cred-new") == {"secret": SECRET}
    with pytest.raises(CredentialResolution):
        await store.get_credential_ref(T, "cred-old")


@pytest.mark.security
@pytest.mark.invariant("SEC-169")
def test_a_missing_or_default_key_is_fatal_in_production(monkeypatch):
    _dev_env(monkeypatch)
    monkeypatch.setenv("BOLTRIG_PRODUCTION", "1")
    with pytest.raises(RuntimeError, match="BOLTRIG_SEAL_KEY"):
        seal_ref({"secret": SECRET})
    monkeypatch.setenv("BOLTRIG_SEAL_KEY", "dev-insecure-seal-key")
    with pytest.raises(RuntimeError, match="BOLTRIG_SEAL_KEY"):
        seal_ref({"secret": SECRET})
    # A real key under the same signal seals fine.
    monkeypatch.setenv("BOLTRIG_SEAL_KEY", "prod-key-" + "z" * 40)
    assert is_sealed(seal_ref({"secret": SECRET}))


@pytest.mark.security
@pytest.mark.invariant("SEC-169")
def test_the_dev_default_seals_offline_and_round_trips(monkeypatch):
    _dev_env(monkeypatch)
    envelope = seal_ref({"secret": SECRET})
    assert is_sealed(envelope) and SECRET not in json.dumps(envelope)
    assert unseal_ref(envelope) == {"secret": SECRET}
    # Sealing is idempotent - a re-persisted envelope is never double-sealed.
    assert seal_ref(envelope) is envelope
