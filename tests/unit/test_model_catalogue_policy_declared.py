"""The declared-modality stand-in admits only gateway-listed, undescribed models."""

from __future__ import annotations

from boltrig.model_catalogue_policy import catalogue_model_reason


def _ok(models: list[dict]) -> dict:
    return {"status": "ok", "models": models, "reason": None}


_BARE = _ok([{"id": "ollama/local-model", "name": "Local"}])


def test_bare_row_with_declared_text_is_admitted() -> None:
    assert (
        catalogue_model_reason(
            _BARE, "ollama/local-model", ("text",), declared_modalities=("text",)
        )
        is None
    )


def test_bare_row_without_declaration_stays_refused() -> None:
    assert (
        catalogue_model_reason(_BARE, "ollama/local-model", ("text",))
        == "text_capability_not_advertised"
    )


def test_malformed_modalities_refuse_even_with_declaration() -> None:
    described_wrong = _ok(
        [{"id": "ollama/local-model", "name": "Local", "input_modalities": "nope"}]
    )
    assert (
        catalogue_model_reason(
            described_wrong,
            "ollama/local-model",
            ("text",),
            declared_modalities=("text",),
        )
        == "text_capability_not_advertised"
    )


def test_declaration_cannot_grant_a_modality_it_lacks() -> None:
    assert (
        catalogue_model_reason(
            _BARE, "ollama/local-model", ("text",), declared_modalities=("vision",)
        )
        == "text_not_supported"
    )


def test_declared_vision_maps_to_image_like_the_advertised_form() -> None:
    assert (
        catalogue_model_reason(
            _BARE,
            "ollama/local-model",
            ("text", "vision"),
            declared_modalities=("text", "vision"),
        )
        is None
    )


def test_blank_declared_entries_refuse() -> None:
    assert (
        catalogue_model_reason(
            _BARE, "ollama/local-model", ("text",), declared_modalities=("text", "")
        )
        == "text_capability_not_advertised"
    )


def test_absent_model_is_still_not_advertised_regardless_of_declaration() -> None:
    assert (
        catalogue_model_reason(
            _ok([]), "ollama/local-model", ("text",), declared_modalities=("text",)
        )
        == "model_not_advertised"
    )
