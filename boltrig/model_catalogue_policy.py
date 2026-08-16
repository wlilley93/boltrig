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


def catalogue_model_reason(
    result: object,
    model_id: str,
    required_modalities: tuple[str, ...],
) -> CatalogueModelReason | None:
    """Return why an exact model is unavailable, or ``None`` when admitted.

    The catalogue is a server-owned snapshot. Malformed, partial, duplicate, or
    unavailable snapshots all fail closed; display names and aliases never match.
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
        return "text_capability_not_advertised"
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
