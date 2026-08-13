"""Author-only safe projection of the stack-owned Bifrost model catalogue."""

from __future__ import annotations

from fastapi import Request

from ._shared import platform_state, require_author

_CATALOGUE_REASONS = frozenset(
    {
        "not_configured",
        "invalid_gateway_configuration",
        "gateway_timeout",
        "gateway_unavailable",
        "gateway_redirect_rejected",
        "gateway_response_rejected",
        "response_too_large",
        "schema_invalid",
        "catalogue_too_large",
        "pagination_limit",
    }
)


def _unavailable(reason: str = "not_configured") -> dict[str, object]:
    return {"status": "unavailable", "models": [], "reason": reason}


def _safe_text(value: object, maximum: int) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and len(value) <= maximum
        and all(
            ord(character) >= 0x20 and character not in {"\u2028", "\u2029"} for character in value
        )
    )


def _public_result(result: object) -> dict[str, object]:
    """Re-project even an injected provider so extra upstream fields cannot escape."""

    if not isinstance(result, dict):
        return _unavailable("gateway_response_rejected")
    status, models, reason = result.get("status"), result.get("models"), result.get("reason")
    if status == "unavailable":
        if (
            type(models) is list
            and not models
            and type(reason) is str
            and reason in _CATALOGUE_REASONS
        ):
            return _unavailable(reason)
        return _unavailable("gateway_response_rejected")
    if status != "ok" or type(models) is not list or reason is not None or len(models) > 500:
        return _unavailable("gateway_response_rejected")
    projected = []
    seen: set[str] = set()
    for row in models:
        if (
            not isinstance(row, dict)
            or not _safe_text(row.get("id"), 160)
            or not _safe_text(row.get("name"), 160)
            or row["id"] in seen
        ):
            return _unavailable("gateway_response_rejected")
        public = {"id": row["id"], "name": row["name"]}
        seen.add(row["id"])
        if "input_modalities" in row:
            modalities = row["input_modalities"]
            if (
                type(modalities) is not list
                or len(modalities) > 8
                or any(not _safe_text(value, 32) for value in modalities)
                or len(modalities) != len(set(modalities))
            ):
                return _unavailable("gateway_response_rejected")
            public["input_modalities"] = list(modalities)
        projected.append(public)
    return {"status": "ok", "models": projected, "reason": None}


def register(app, P, K) -> None:
    @app.get("/v1/bifrost/models")
    async def list_bifrost_models(request: Request, p=P) -> dict[str, object]:
        require_author(p)
        catalogue = platform_state(request).get("bifrost_models")
        if catalogue is None:
            return _unavailable()
        try:
            return _public_result(await catalogue.list_models())
        except Exception:
            # A platform provider is injected code. Keep an accidental provider
            # failure on the same content-free, typed unavailable surface.
            return _unavailable("gateway_unavailable")


__all__ = ["register"]
