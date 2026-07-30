"""Author inventory and exact-detail routes for nouns and verbs."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from ._shared import require_author
from .authored_registry_views import noun_view, verb_view


def register_authored_registry_read_routes(app, P, K) -> None:
    @app.get("/v1/nouns")
    async def list_nouns(k=K, p=P) -> dict:
        require_author(p)
        nouns = sorted(
            await k.store.list_all_nouns(p.tenant_id),
            key=lambda noun: noun.id,
        )
        return {"nouns": [noun_view(noun) for noun in nouns]}

    @app.get("/v1/verbs")
    async def list_verbs(k=K, p=P) -> dict:
        require_author(p)
        verbs = sorted(
            await k.store.list_all_verbs(p.tenant_id),
            key=lambda verb: verb.id,
        )
        return {
            "verbs": [
                await verb_view(k.store, p.tenant_id, verb)
                for verb in verbs
            ]
        }

    @app.get("/v1/nouns/{noun_id}")
    async def get_noun(noun_id: str, k=K, p=P) -> JSONResponse:
        require_author(p)
        noun = await k.store.get_noun_any(p.tenant_id, noun_id)
        if noun is None:
            return JSONResponse(
                {"status": "error", "reason": "not_found"},
                status_code=404,
            )
        return JSONResponse({"noun": noun_view(noun)})

    @app.get("/v1/verbs/{verb_id}")
    async def get_verb(verb_id: str, k=K, p=P) -> JSONResponse:
        require_author(p)
        verb = await k.store.get_verb_any(p.tenant_id, verb_id)
        if verb is None:
            return JSONResponse(
                {"status": "error", "reason": "not_found"},
                status_code=404,
            )
        payload = await verb_view(k.store, p.tenant_id, verb)
        binding = payload.pop("binding")
        return JSONResponse({"verb": payload, "binding": binding})
