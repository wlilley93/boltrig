"""The ``distill`` adapter: sleep distillation as governed verbs (decision 0023).

Four verbs behind the one chokepoint, so every step of the nightly
consolidation is granted, gated, rate-limited and audited like any other
action:

    distill.corpus.build   derive + ship the tenant corpus (low)
    distill.train          train a candidate adapter from the pinned base (high)
    distill.gate           score candidate vs incumbent, mechanically (low)
    distill.promote        activate + price a gated candidate (high)

The trainer/server sidecar runs NATIVE on the Mac host (mlx needs Metal, which
does not exist inside the OrbStack VM - the whisper precedent), so this
adapter passes the egress guard's one documented ``allow_internal`` opt-in for
a fixed, operator-configured URL. Never an agent-influenced one
(``tests/invariants.yaml`` INJ-02 family).

Like the memory adapter, this one needs the store and audit writer, so it is
composed by ``boltrig.distill.bootstrap.register_distill`` from the manifest's
``distill:`` section rather than the ``adapters:`` module_ref list. The craft
gate additionally needs the composition-owned EvalRunner; platform bootstrap
injects it late via ``set_eval`` (the ``control.set_admin`` pattern) - a new
spawner is never constructed here (CODEX-COMPOSITION-1 source gate).
"""

from __future__ import annotations

from typing import Any

import httpx

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.adapters.egress import EgressBlocked, assert_egress_allowed
from boltrig.adapters.http_base import Handler, HttpAdapter
from boltrig.distill.adapter_gates import craft_gate, register_gate
from boltrig.distill.adapter_night import run_night
from boltrig.distill.adapter_specs import (
    corpus_schema,
    gate_schema,
    night_schema,
    promote_schema,
    train_schema,
)
from boltrig.distill.corpus import (
    CorpusDataClassRefused,
    CorpusTenantMismatch,
    build_corpus,
)
from boltrig.distill.corpus_io import corpus_jsonl_lines
from boltrig.models import ActionType, AuditEvent, InvocationContext, utcnow

_GATE_AUDIT_SCAN = 500  # how far back promote looks for its gate receipt


class DistillAdapter(HttpAdapter):
    id = "distill"
    version = "0.1.0"
    source = "builtin"
    user_agent = "boltrig-distill/1.0"
    requires_credential = False

    def __init__(
        self,
        store: Any,
        *,
        audit: Any,
        cost: Any,
        base_pin: str,
        base_url: str,
        serve_url: str | None = None,  # chat-serving endpoint for candidates
        timeout: float = 600.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(base_url=base_url, timeout=timeout)
        self._store = store
        self._audit = audit
        self._cost = cost
        self._base_pin = base_pin
        self._serve_url = serve_url
        self._transport = transport
        self._eval: Any | None = None

    # Late binding from platform bootstrap (the control.set_admin pattern):
    # the craft gate uses the composition-owned EvalRunner or degrades typed.
    def set_eval(self, eval_runner: Any) -> None:
        self._eval = eval_runner

    def describe(self) -> list[VerbSpec]:
        any_out = {"type": "object"}
        return [
            VerbSpec(
                "distill.corpus.build", "distill", corpus_schema(), any_out, "low",
                "Derive the tenant's training corpus from the governed record "
                "(erasure-filtered, PII-scrubbed, digest-pinned) and ship it to "
                "the local trainer sidecar.",
                idempotency_mode="disabled",  # re-derives; the digest is the identity
            ),
            VerbSpec(
                "distill.train", "distill", train_schema(), any_out, "high",
                "Train a candidate LoRA from the PINNED BASE over a shipped "
                "corpus. There is no field to name any other starting point.",
                idempotency_mode="disabled",
            ),
            VerbSpec(
                "distill.gate", "distill", gate_schema(), any_out, "low",
                "Score a candidate against the incumbent, mechanically: eval "
                "cases for craft, held-out likelihood for register. Writes an "
                "audit row whether it promotes or holds.",
                idempotency_mode="disabled",
            ),
            VerbSpec(
                "distill.promote", "distill", promote_schema(), any_out, "high",
                "Activate a candidate endpoint that holds a passing gate "
                "receipt, and price it in the same act.",
                idempotency_mode="disabled",
            ),
            VerbSpec(
                "distill.night", "distill", night_schema(), any_out, "high",
                "One night of sleep distillation: build the corpus, train from "
                "the pinned base, gate mechanically. Does NOT promote unless "
                "auto_promote is set; a passing gate leaves the receipt for a "
                "separate distill.promote.",
                idempotency_mode="disabled",
            ),
        ]

    def _handlers(self) -> dict[str, Handler]:
        return {
            "distill.corpus.build": self._corpus_build,
            "distill.train": self._train,
            "distill.gate": self._gate,
            "distill.promote": self._promote,
            "distill.night": self._night,
        }

    async def _night(
        self, params: dict[str, Any], client: httpx.AsyncClient,
        context: InvocationContext,
    ) -> Result:
        return await run_night(self, params, client, context)

    def _auth(self, credential: Credential) -> tuple[dict[str, str], httpx.Auth | None]:
        return {}, None  # local keyless sidecar, like local-whisper

    def _client(self, credential: Credential | None) -> httpx.AsyncClient:
        if self._transport is None:
            return super()._client(credential)
        return httpx.AsyncClient(
            base_url=self.base_url_for(credential),
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            timeout=self.timeout,
            transport=self._transport,
        )

    async def health(self) -> str:
        return "unknown"

    # --- sidecar carrier ------------------------------------------------------
    async def _call(
        self, client: httpx.AsyncClient, method: str, url: str, payload: Any
    ) -> dict[str, Any] | AdapterError:
        """JSON call to the fixed operator-configured sidecar. ``allow_internal``
        is the guard's one documented opt-in and is required here for the same
        reason as local-whisper: the target IS internal, by design, and is never
        an agent-supplied URL. Scheme/air-gap/list checks still apply."""
        try:
            assert_egress_allowed(
                str(client.base_url.join(url)), {"allow_internal": True}
            )
        except EgressBlocked as exc:
            return AdapterError(ErrorClass.INVALID, str(exc), retryable=False)
        await self._limiter.acquire()
        try:
            resp = await client.request(method, url, json=payload)
        except httpx.HTTPError as exc:
            return AdapterError(
                ErrorClass.UNAVAILABLE, f"distill sidecar unreachable: {exc}",
                retryable=True,
            )
        if not 200 <= resp.status_code < 300:
            return self._map_status(resp)
        return self._parse(resp)

    # --- handlers -------------------------------------------------------------
    async def _corpus_build(
        self, params: dict[str, Any], client: httpx.AsyncClient,
        context: InvocationContext,
    ) -> Result:
        endpoint_id = str(params["target_endpoint_id"])
        endpoint = await self._store.get_model_endpoint(context.tenant_id, endpoint_id)
        if endpoint is None:
            return Result.failure(
                AdapterError(ErrorClass.NOT_FOUND,
                             f"target endpoint '{endpoint_id}' not found",
                             retryable=False)
            )
        try:
            corpus = await build_corpus(
                self._store,
                context.tenant_id,
                base_pin=self._base_pin,
                target_tenant_id=endpoint.tenant_id,
                target_data_class=endpoint.data_class,
            )
        except (CorpusTenantMismatch, CorpusDataClassRefused) as exc:
            return Result.failure(
                AdapterError(ErrorClass.INVALID, str(exc), retryable=False)
            )
        body = {"jsonl": "\n".join(corpus_jsonl_lines(corpus))}
        shipped = await self._call(client, "PUT", f"/corpus/{corpus.digest}", body)
        if isinstance(shipped, AdapterError):
            return Result.failure(shipped)
        return Result.success({
            "digest": corpus.digest,
            "base_pin": corpus.base_pin,
            "records": len(corpus.records),
            "held_out": len(corpus.held_out),
            # "look at your data": composition + dedup at a glance, so a night
            # that trained mostly on merely-clean synthetic turns is visible
            # in its receipt, not discovered in its behaviour.
            "signals": corpus.signal_counts,
            "deduped": corpus.deduped,
            "erasure_watermark": (
                corpus.erasure_watermark.isoformat()
                if corpus.erasure_watermark else None
            ),
        })

    async def _train(
        self, params: dict[str, Any], client: httpx.AsyncClient,
        context: InvocationContext,
    ) -> Result:
        digest = str(params["corpus_digest"])
        kind = str(params["adapter_kind"])
        # DIS-4: the request names the base PIN this adapter is composed with;
        # the sidecar refuses a corpus whose header pin differs. Training can
        # never resume from a prior adapter because no request field exists to
        # express one - here, in the schema, or in the sidecar contract.
        body = {"corpus_digest": digest, "adapter_kind": kind,
                "base_pin": self._base_pin}
        trained = await self._call(client, "POST", "/train", body)
        if isinstance(trained, AdapterError):
            return Result.failure(trained)
        if str(trained.get("base_pin") or "") != self._base_pin:
            return Result.failure(
                AdapterError(
                    ErrorClass.INVALID,
                    "sidecar trained from a base other than the composed pin",
                    retryable=False,
                )
            )
        return Result.success({
            "adapter_id": str(trained.get("adapter_id") or ""),
            "base_pin": self._base_pin,
            "corpus_digest": digest,
            "adapter_kind": kind,
        })

    async def _gate(
        self, params: dict[str, Any], client: httpx.AsyncClient,
        context: InvocationContext,
    ) -> Result:
        digest = str(params["corpus_digest"])
        kind = str(params["adapter_kind"])
        candidate = str(params["candidate_model"])
        incumbent = str(params["incumbent_model"])
        if kind == "register":
            async def call(method: str, url: str, payload: Any) -> dict[str, Any] | AdapterError:
                return await self._call(client, method, url, payload)

            verdict_or_error = await register_gate(call, digest, incumbent, candidate)
        else:
            verdict_or_error = await craft_gate(
                self._eval, self._store, self._serve_url, context, incumbent, candidate
            )
        if isinstance(verdict_or_error, AdapterError):
            return Result.failure(verdict_or_error)
        verdict = verdict_or_error
        # DIS-7: promote AND hold both leave a hash-chained receipt. The
        # promote verb later requires exactly this row, so the receipt is the
        # only path to activation - derived state, no promotion table.
        await self._audit.write(
            AuditEvent(
                tenant_id=context.tenant_id,
                ts=utcnow(),
                actor=context.actor,
                action_type=ActionType.MODEL_CALL,
                status="distill_gate_promote" if verdict.promote else "distill_gate_hold",
                run_id=context.run_id,
                verb="distill.gate",
                target_adapter=self.id,
                detail={
                    "adapter_kind": kind,
                    "corpus_digest": digest,
                    "base_pin": self._base_pin,
                    "candidate": candidate,
                    "incumbent": incumbent,
                    "incumbent_score": verdict.incumbent_score,
                    "candidate_score": verdict.candidate_score,
                    "reason": verdict.reason,
                    "regressed_cases": list(verdict.regressed_cases),
                },
            )
        )
        return Result.success({
            "promote": verdict.promote,
            "reason": verdict.reason,
            "incumbent_score": verdict.incumbent_score,
            "candidate_score": verdict.candidate_score,
            "regressed_cases": list(verdict.regressed_cases),
        })

    async def _promote(
        self, params: dict[str, Any], client: httpx.AsyncClient,
        context: InvocationContext,
    ) -> Result:
        endpoint_id = str(params["endpoint_id"])
        digest = str(params["corpus_digest"])
        price = float(params["price_micros_per_token"])
        endpoint = await self._store.get_model_endpoint(context.tenant_id, endpoint_id)
        if endpoint is None:
            return Result.failure(
                AdapterError(ErrorClass.NOT_FOUND,
                             f"endpoint '{endpoint_id}' not found", retryable=False)
            )
        receipt = await self._gate_receipt(context.tenant_id, digest, endpoint.model)
        if receipt is None:
            # DIS-5: only a passing gate flips is_active - no receipt, no seat.
            return Result.failure(
                AdapterError(
                    ErrorClass.INVALID,
                    "no passing gate receipt for this corpus digest and model",
                    retryable=False,
                )
            )
        await self._store.set_model_endpoint_active(
            context.tenant_id, endpoint_id, True
        )
        # DIS-8: priced in the same act as the promotion, else cost accounting
        # bills the tier default ($5/M) and trips hard-stop budgets early.
        self._cost.set_price(endpoint.model, price)
        await self._audit.write(
            AuditEvent(
                tenant_id=context.tenant_id,
                ts=utcnow(),
                actor=context.actor,
                action_type=ActionType.MODEL_CALL,
                status="distill_promote",
                run_id=context.run_id,
                verb="distill.promote",
                target_adapter=self.id,
                detail={
                    "endpoint_id": endpoint_id,
                    "model": endpoint.model,
                    "corpus_digest": digest,
                    "base_pin": self._base_pin,
                    "price_micros_per_token": price,
                    "gate_reason": str(receipt.detail.get("reason", "")),
                },
            )
        )
        return Result.success({
            "endpoint_id": endpoint_id,
            "model": endpoint.model,
            "is_active": True,
            "price_micros_per_token": price,
        })

    async def _gate_receipt(
        self, tenant_id: str, digest: str, model: str
    ) -> AuditEvent | None:
        """Find the newest passing gate row for (digest, model). Promotion
        state is DERIVED from the audit chain - the WorkflowPromotion ruling:
        no table, no writer, no trigger."""
        events = await self._store.audit_query(tenant_id, limit=_GATE_AUDIT_SCAN)
        for event in reversed(events):
            if (
                event.status == "distill_gate_promote"
                and event.detail.get("corpus_digest") == digest
                and event.detail.get("candidate") == model
            ):
                return event
        return None
