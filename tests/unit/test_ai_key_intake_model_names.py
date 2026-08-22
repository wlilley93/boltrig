"""Model names are vetted at the intake door, in the provider's own spelling.

THE BUG THIS PINS. A name the intake accepted on 2026-08-20 crashed activation
three screens later (after sealing and approval), as an unexplained failure.
The rule now runs at submit time and answers with one plain sentence. A
self-hosted provider treats a bare name as ``:latest`` and lists it that way,
so the intake applies the same default instead of teaching it.
"""

from types import SimpleNamespace

from boltrig.kernel.ai_key_routes import _parse_ai_key_intake


def _principal() -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id="acme",
        subject="admin",
        on_behalf_of=None,
        active_workspace_id=None,
    )


def _parse(body: dict):
    return _parse_ai_key_intake(dict(body), _principal())


def test_selfhosted_bare_model_name_gets_the_providers_default_tag() -> None:
    parsed, invalid = _parse(
        {"level": "user", "provider": "ollama", "model": "ollama/qwen3vl-abliterated"}
    )
    assert invalid is None
    assert parsed[3] == "ollama/qwen3vl-abliterated:latest"


def test_selfhosted_tagged_model_name_is_untouched() -> None:
    parsed, invalid = _parse(
        {
            "level": "user",
            "provider": "ollama",
            "model": "ollama/qwen3vl-abliterated:34ba10f8b5e0",
        }
    )
    assert invalid is None
    assert parsed[3] == "ollama/qwen3vl-abliterated:34ba10f8b5e0"


def test_keyed_provider_model_names_are_never_rewritten() -> None:
    parsed, invalid = _parse(
        {
            "level": "user",
            "provider": "openai",
            "model": "openai/gpt-5.4",
            "api_key": "sk-x",
        }
    )
    assert invalid is None
    assert parsed[3] == "openai/gpt-5.4"


def test_a_malformed_model_name_is_one_plain_sentence_at_submit_time() -> None:
    parsed, invalid = _parse(
        {
            "level": "user",
            "provider": "openai",
            "model": "openai//gpt",
            "api_key": "sk-x",
        }
    )
    assert parsed is None
    assert invalid.status_code == 400
    assert b"exact name your provider lists" in invalid.body
