"""Credential resolution (P3, US-KER-03, SEC-04/05, K-20).

Credentials are resolved only inside the kernel, at call time, from an external
secret store. The application DB never holds plaintext: a credential_refs row is
either a pure *reference* (``{store, ref}`` into a SecretStore) or a reference
dict carrying inline material that the store seam envelope-SEALS at rest
(``boltrig/store/sealing.py``) and unseals transparently on read. A resolved
``Credential`` is handed to one adapter call and never returned to,
embedded in, or logged by an agent.

SEC-181 run-scoped secure input: a secure ``chat.ask_user`` answer is sealed by
the answer route through this seam as a PURPOSE- AND RUN-SCOPED credential
(stored under the id ``run:<run_id>:<purpose>``, sealed at rest like any inline
material). The run and its events/audit/context only ever carry the REFERENCE
string ``credential:run/<run_id>/<purpose>``; a verb param holding that shape is
resolved to the material inside the kernel at the dispatch credential stage
(``resolve_run_scoped_params``), and ONLY for the same run id and the declared
purpose - a reference from another run or purpose fails closed
(``CredentialResolution``).
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from boltrig.adapters.base import Credential
from boltrig.models import CredentialResolution
from boltrig.store import Store

# The reference shape a run carries in place of a secure answer's value, and
# the credential_refs id prefix the value is sealed under (SEC-181).
RUN_SCOPED_REF_PREFIX = "credential:run/"
RUN_SCOPED_CRED_PREFIX = "run:"
# Marker on the sealed row so an unrelated credential that happens to sit under
# a ``run:`` id is never resolvable as a secure-input reference.
_SECURE_ANSWER_KIND = "secure_answer"
# Marker on the sealed row for a per-turn, per-run ADAPTER BEARER (the parity
# passthrough: a caller's clamped external bearer sealed for one adapter for the
# life of one run). DELIBERATELY DISTINCT from _SECURE_ANSWER_KIND so this value
# is NEVER resolvable through ``resolve_run_scoped_params`` - it is only ever
# resolved into the adapter ``credential`` arg at dispatch, never substituted
# into a verb param (an agent could otherwise coax the bearer into an output).
_ADAPTER_BEARER_KIND = "adapter_bearer"


def run_scoped_cred_id(run_id: str, purpose: str) -> str:
    """The credential_refs id a secure answer is sealed under."""
    return f"{RUN_SCOPED_CRED_PREFIX}{run_id}:{purpose}"


def adapter_bearer_cred_id(run_id: str, adapter_id: str) -> str:
    """The credential_refs id a per-run adapter bearer is sealed under. Distinct
    ``adapter_bearer:`` segment keeps it out of the secure-answer keyspace."""
    return f"{RUN_SCOPED_CRED_PREFIX}{run_id}:adapter_bearer:{adapter_id}"


def _owner_matches(ref: dict, context_owner: str | None) -> bool:
    """Whether this sealed row belongs to the identity now asking for it.

    The run id was once the whole fence here, on the reasoning that a run id is
    server-minted and therefore trustworthy. It is not: the write doors let the
    request body name the run (``POST /v1/invoke``, ``POST /v1/spawn``), so a
    same-tenant caller could quote a stranger's run id and be handed that
    stranger's sealed material - the reference's run id and the "context" run id
    it was compared against both came from the same attacker-controlled request,
    so they always agreed. The doors now refuse a foreign run id
    (``kernel/run_access.py``), and this is the second, independent fence at the
    resolver itself: whatever any future door decides to trust, the material only
    resolves for the identity it was sealed for.

    Fail closed on both sides. A row sealed before this fence existed carries no
    ``owner`` and resolves for nobody; run-scoped rows are swept at run terminal
    and live only for the length of a run, so that costs at most the in-flight
    runs at deploy time - a secure answer must be re-asked, and a passthrough
    bearer falls back to the adapter's static credential, which is the documented
    behaviour when no bearer is sealed."""
    owner = ref.get("owner")
    return bool(owner) and bool(context_owner) and owner == context_owner


def parse_run_scoped_ref(value: Any) -> tuple[str, str] | None:
    """Parse a ``credential:run/<run_id>/<purpose>`` reference, else ``None``.

    Strict shape (exactly one run id and one purpose segment): anything else -
    including a reference with extra path segments - is not a run-scoped ref at
    all, so it is never silently reinterpreted."""
    if not isinstance(value, str) or not value.startswith(RUN_SCOPED_REF_PREFIX):
        return None
    parts = value[len(RUN_SCOPED_REF_PREFIX):].split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


class SecretStore(Protocol):
    """Fetches secret material by reference. Implementations: Vault, cloud KMS,
    Docker secrets, env. None ever persist material in the app DB."""

    async def fetch(self, store: str, ref: str) -> dict: ...


class EnvSecretStore:
    """Reads secret material from environment variables.

    The credential reference is an env var name; its value is JSON (a dict of
    material) or, failing that, the raw string under key ``value``.
    """

    async def fetch(self, store: str, ref: str) -> dict:
        raw = os.environ.get(ref)
        if raw is None:
            raise CredentialResolution(f"env secret '{ref}' not set")
        try:
            import json

            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except ValueError:
            return {"value": raw}


class CredentialResolver:
    def __init__(self, store: Store, secret_store: SecretStore | None = None) -> None:
        self._store = store
        self._secret = secret_store or EnvSecretStore()
        # adapter id -> credential id, populated from the manifest at boot.
        self._adapter_cred: dict[tuple[str, str], str] = {}

    def bind_adapter_credential(self, tenant_id: str, adapter_id: str, cred_id: str) -> None:
        self._adapter_cred[(tenant_id, adapter_id)] = cred_id

    async def resolve_for_adapter(
        self, tenant_id: str, adapter_id: str
    ) -> Credential | None:
        """Resolve the credential an adapter needs, or ``None`` if it needs none."""
        cred_id = self._adapter_cred.get((tenant_id, adapter_id))
        if cred_id is None:
            return None  # adapter requires no credential (e.g. a local script)
        ref = await self._store.get_credential_ref(tenant_id, cred_id)
        if ref is None:
            raise CredentialResolution(
                f"no credential reference '{cred_id}' for tenant '{tenant_id}'"
            )
        material = await self.fetch_material(ref)
        return Credential(id=cred_id, kind=ref.get("kind", "api_key"), material=material)

    async def fetch_material(self, ref: dict) -> dict:
        """Fetch the material behind a stored credential REFERENCE ({store, ref})
        through the SecretStore seam. Kernel-side only (SEC-04/05): the material
        is never logged, audited, or handed to an agent."""
        return await self._secret.fetch(ref.get("store", "env"), ref["ref"])

    # --- SEC-181: run-scoped secure input ------------------------------------

    async def seal_run_scoped_value(
        self, tenant_id: str, run_id: str, purpose: str, value: str, owner: str
    ) -> str:
        """Seal a secure question's answer as a run+purpose-scoped credential
        and return the REFERENCE string the run carries in its place.

        The value goes straight through the sealed credential seam
        (``set_credential_ref`` envelope-seals it at rest, SEC-04); it is never
        returned, logged, or audited by this path. The caller records the
        returned reference (enveloped) as the answer, so the resume wiring
        replays the reference, never the value.

        ``owner`` is the user this material belongs to (the answering principal),
        and it is REQUIRED. See ``_owner_matches`` for why the run id alone is
        not a sufficient fence."""
        if not run_id or not purpose:
            raise CredentialResolution(
                "a secure answer requires both a run id and a purpose"
            )
        if not owner:
            raise CredentialResolution("a secure answer requires an owning identity")
        await self._store.set_credential_ref(
            tenant_id,
            run_scoped_cred_id(run_id, purpose),
            {
                "kind": _SECURE_ANSWER_KIND,
                "run_id": run_id,
                "purpose": purpose,
                "owner": owner,
                "value": value,
            },
        )
        return f"{RUN_SCOPED_REF_PREFIX}{run_id}/{purpose}"

    async def _resolve_run_scoped(
        self,
        tenant_id: str,
        run_id: str,
        purpose: str,
        context_run_id: str | None,
        context_owner: str | None,
    ) -> Any:
        """Resolve one parsed reference to its material, FAIL CLOSED: only the
        SAME run AND the SAME owner may resolve it, only a genuine secure-answer
        row whose embedded run/purpose match the reference exactly qualifies (a
        tampered id or a foreign credential under a ``run:`` id never resolves),
        and a missing row resolves to nothing."""
        if not context_run_id or run_id != context_run_id:
            raise CredentialResolution(
                "run-scoped credential reference does not belong to this run"
            )
        ref = await self._store.get_credential_ref(
            tenant_id, run_scoped_cred_id(run_id, purpose)
        )
        if (
            not isinstance(ref, dict)
            or ref.get("kind") != _SECURE_ANSWER_KIND
            or ref.get("run_id") != run_id
            or ref.get("purpose") != purpose
        ):
            raise CredentialResolution(
                "run-scoped credential reference is unknown or scope-mismatched"
            )
        if not _owner_matches(ref, context_owner):
            raise CredentialResolution(
                "run-scoped credential reference does not belong to this caller"
            )
        return ref["value"]

    async def resolve_run_scoped_params(
        self, tenant_id: str, params: Any, *, run_id: str | None, owner: str | None
    ) -> Any:
        """Return a copy of ``params`` with every run-scoped credential
        REFERENCE string replaced by its material (SEC-181).

        Called at the dispatch resolve-credential stage, immediately before the
        adapter executes: the agent, the run context, the events and the audit
        only ever carried the reference. Resolution is scoped - a reference from
        another run, purpose or owner fails closed (``CredentialResolution``).
        Values that are not references pass through unchanged."""
        if isinstance(params, dict):
            return {
                key: await self.resolve_run_scoped_params(
                    tenant_id, item, run_id=run_id, owner=owner
                )
                for key, item in params.items()
            }
        if isinstance(params, (list, tuple)):
            return [
                await self.resolve_run_scoped_params(
                    tenant_id, item, run_id=run_id, owner=owner
                )
                for item in params
            ]
        parsed = parse_run_scoped_ref(params)
        if parsed is None:
            return params
        return await self._resolve_run_scoped(
            tenant_id, parsed[0], parsed[1], run_id, owner
        )

    # --- Per-run adapter bearer (parity passthrough) -------------------------

    async def seal_run_scoped_adapter_bearer(
        self, tenant_id: str, run_id: str, adapter_id: str, token: str, owner: str
    ) -> None:
        """Seal a caller-supplied external bearer for ONE adapter for the life of
        ONE run (the permission-parity passthrough).

        The chat turn threads the caller's clamped external bearer (e.g. the
        opbox-kernel session bearer, already clamped to min(agent,user)) here at
        turn start; ``resolve_run_scoped_credential`` re-mints it into the
        adapter ``credential`` arg at dispatch (``_execute_adapter``), so the
        downstream service enforces the CALLER's grants, not the adapter's static
        service token. The value goes straight through the sealed credential seam
        (envelope-sealed at rest, SEC-04); it is never returned, logged, or
        audited, and - unlike a secure answer - it is never resolvable into a verb
        param (distinct kind). Swept with the run's other refs on terminal
        (``sweep_run_scoped``), fail-closed to the same run until then.

        ``owner`` is the user whose downstream authority this bearer carries, and
        it is REQUIRED. See ``_owner_matches``."""
        if not run_id or not adapter_id or not token:
            raise CredentialResolution(
                "a run-scoped adapter bearer requires a run id, an adapter id and a token"
            )
        if not owner:
            raise CredentialResolution(
                "a run-scoped adapter bearer requires an owning identity"
            )
        await self._store.set_credential_ref(
            tenant_id,
            adapter_bearer_cred_id(run_id, adapter_id),
            {
                "kind": _ADAPTER_BEARER_KIND,
                "run_id": run_id,
                "adapter_id": adapter_id,
                "owner": owner,
                "value": token,
            },
        )

    async def resolve_run_scoped_credential(
        self, tenant_id: str, run_id: str | None, adapter_id: str, owner: str | None
    ) -> Credential | None:
        """Resolve a per-run adapter bearer to a ``Credential`` for this adapter,
        or ``None`` when none is sealed (so dispatch falls back to the adapter's
        static credential - the fail-safe that keeps dev/non-passthrough tenants
        unchanged).

        FAIL CLOSED like the secure-answer path: only a genuine adapter-bearer row
        whose embedded run/adapter match exactly qualifies AND whose owner is this
        caller; a foreign row under a ``run:`` id, a scope mismatch, an owner
        mismatch, or a missing run id resolves to ``None``."""
        if not run_id or not adapter_id:
            return None
        ref = await self._store.get_credential_ref(
            tenant_id, adapter_bearer_cred_id(run_id, adapter_id)
        )
        if (
            not isinstance(ref, dict)
            or ref.get("kind") != _ADAPTER_BEARER_KIND
            or ref.get("run_id") != run_id
            or ref.get("adapter_id") != adapter_id
            or not _owner_matches(ref, owner)
        ):
            return None
        return Credential(
            id=adapter_bearer_cred_id(run_id, adapter_id),
            kind="api_key",
            material={"token": ref["value"]},
        )

    async def sweep_run_scoped(self, tenant_id: str, run_id: str) -> int:
        """Delete every run-scoped secure-input credential of a finished run.

        Lifecycle honesty: the kernel owns no run-terminal hook - run settle /
        cancel is written by the fleet pump (outside the kernel's reach by the
        layering rule), so this sweep is the lifecycle seam the fleet calls when
        a run reaches a terminal state. Until it is wired there the blast radius
        of a lingering ref is bounded by the fail-closed scoping above: it can
        never be resolved by any other run."""
        return await self._store.delete_credential_refs_for_run(tenant_id, run_id)
