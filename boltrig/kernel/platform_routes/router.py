"""Router authoring (RTR): nouns, verbs, bindings."""

from __future__ import annotations

from fastapi.responses import JSONResponse
from boltrig.config.control_plane import upsert_noun_record, upsert_verb_record, set_binding_record
from ._shared import audit_authoring, require_author


def register(app, P, K) -> None:
    @app.post("/v1/nouns")
    async def upsert_noun(body: dict, k=K, p=P) -> JSONResponse:
        require_author(p)
        noun = await upsert_noun_record(k.store, p.tenant_id, body)
        await audit_authoring(k, p, "noun.upsert", {"id": noun.id})
        return JSONResponse({"status": "ok", "id": noun.id})

    @app.post("/v1/verbs")
    async def upsert_verb(body: dict, k=K, p=P) -> JSONResponse:
        require_author(p)
        verb = await upsert_verb_record(k.store, p.tenant_id, body)
        conseq = verb.consequence.value
        await audit_authoring(k, p, "verb.upsert", {"id": verb.id, "consequence": conseq})
        return JSONResponse({"status": "ok", "id": verb.id, "consequence": conseq})

    @app.post("/v1/verbs/{verb_id}/binding")
    async def set_binding(verb_id: str, body: dict, k=K, p=P) -> JSONResponse:
        require_author(p)
        await set_binding_record(k.store, p.tenant_id, verb_id, body)
        await audit_authoring(k, p, "binding.set", {"verb": verb_id, "target": body["target_ref"]})
        return JSONResponse({"status": "ok", "verb": verb_id})
