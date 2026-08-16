"""The ``distill.night`` orchestration: one governed verb for one night.

Step outputs cannot thread between workflow steps declaratively (the loop
contract is deliberate: bindings replace whole JSON values, never interpolate
- ``workflows/loop_contract.py``), and the corpus digest only exists once the
corpus is built. So the nightly chain runs inside ONE verb: build -> ship ->
train -> gate. Each leg still writes its own receipts through the adapter's
handlers; nothing here bypasses them.

Promotion is deliberately NOT part of the night. A passing gate leaves the
hash-chained receipt; ``distill.promote`` is its own high-consequence verb so
activation stays a separate, human-approvable act carrying the digest from
that receipt (DIS-5). ``auto_promote`` exists for a tenant that has earned
trust in the loop - it defaults off.
"""

from __future__ import annotations

from typing import Any, cast

from boltrig.adapters.base import Result


async def run_night(
    adapter: Any, params: dict[str, Any], client: Any, context: Any
) -> Result:
    endpoint_id = str(params["target_endpoint_id"])
    kind = str(params["adapter_kind"])
    incumbent = str(params["incumbent_model"])

    built = cast(
        Result,
        await adapter._corpus_build(
            {"target_endpoint_id": endpoint_id}, client, context
        ),
    )
    if not built.ok:
        return built
    if not int(built.output.get("records") or 0):
        # A day with nothing to learn from is a quiet night, not a training
        # run that fails three steps later with a confusing sidecar error.
        return Result.success({
            "corpus_digest": str(built.output["digest"]),
            "candidate": None,
            "gate": None,
            "promoted": False,
            "reason": "empty_corpus",
        })
    digest = str(built.output["digest"])

    trained = cast(
        Result,
        await adapter._train(
            {"corpus_digest": digest, "adapter_kind": kind}, client, context
        ),
    )
    if not trained.ok:
        return trained
    candidate = str(trained.output["adapter_id"])

    gated = cast(
        Result,
        await adapter._gate(
            {
                "corpus_digest": digest,
                "adapter_kind": kind,
                "candidate_model": candidate,
                "incumbent_model": incumbent,
            },
            client,
            context,
        ),
    )
    if not gated.ok:
        return gated

    promoted = False
    if bool(params.get("auto_promote")) and gated.output.get("promote"):
        promotion = cast(
            Result,
            await adapter._promote(
                {
                    "endpoint_id": endpoint_id,
                    "corpus_digest": digest,
                    "price_micros_per_token": float(
                        params.get("price_micros_per_token") or 0.0
                    ),
                },
                client,
                context,
            ),
        )
        if not promotion.ok:
            return promotion
        promoted = True

    return Result.success({
        "corpus_digest": digest,
        "candidate": candidate,
        "gate": gated.output,
        "promoted": promoted,
    })
