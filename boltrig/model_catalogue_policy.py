"""Shared fail-closed policy for exact text-capable catalogue membership."""

from __future__ import annotations

from typing import Literal

CatalogueModelReason = Literal[
    "catalogue_unavailable",
    "model_not_advertised",
    "text_capability_not_advertised",
    "text_not_supported",
    "modality_not_supported",
]


def _declared_stand_in(
    row: dict, declared_modalities: tuple[str, ...] | None
) -> list[str] | None:
    """Return the operator-declared modalities for a row the gateway does not describe.

    Plain OpenAI-compatible gateways list provider-derived models as bare
    ``{id, name}`` rows with no ``architecture`` block at all, so absence of
    ``input_modalities`` means "not described", not "describes nothing". Only
    that absence may be answered by the store's own endpoint declaration - the
    same declaration the kernel already trusts to route to the model in the
    first place. A row that CARRIES the key but malformed stays refused: a
    gateway that mis-describes is not one to stand in for.
    """

    if "input_modalities" in row:
        return None
    if not declared_modalities:
        return None
    if not all(type(modality) is str and modality for modality in declared_modalities):
        return None
    return [
        "image" if modality == "vision" else modality
        for modality in declared_modalities
    ]


def catalogue_model_reason(
    result: object,
    model_id: str,
    required_modalities: tuple[str, ...],
    declared_modalities: tuple[str, ...] | None = None,
) -> CatalogueModelReason | None:
    """Return why an exact model is unavailable, or ``None`` when admitted.

    The catalogue is a server-owned snapshot. Malformed, partial, duplicate, or
    unavailable snapshots all fail closed; display names and aliases never match.
    ``declared_modalities`` is the store's own endpoint declaration for this
    exact model: it stands in ONLY when the gateway lists the model without any
    ``input_modalities`` key (see ``_declared_stand_in``); every other refusal
    is unchanged.
    """

    if not isinstance(result, dict) or result.get("status") != "ok":
        return "catalogue_unavailable"
    rows = result.get("models")
    if type(rows) is not list:
        return "catalogue_unavailable"
    matches = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("id") == model_id
    ]
    if len(matches) > 1:
        return "catalogue_unavailable"
    if not matches:
        return "model_not_advertised"
    modalities = matches[0].get("input_modalities")
    if type(modalities) is not list or not all(
        type(modality) is str for modality in modalities
    ):
        stand_in = _declared_stand_in(matches[0], declared_modalities)
        if stand_in is None:
            return "text_capability_not_advertised"
        modalities = stand_in
    required = {"image" if modality == "vision" else modality for modality in required_modalities}
    if not required.issubset(modalities):
        return "text_not_supported" if "text" in required else "modality_not_supported"
    return None


def catalogue_text_model_reason(result: object, model_id: str) -> CatalogueModelReason | None:
    return catalogue_model_reason(result, model_id, ("text",))


__all__ = [
    "CatalogueModelReason",
    "catalogue_model_reason",
    "catalogue_text_model_reason",
]
