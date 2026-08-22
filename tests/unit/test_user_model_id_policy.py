"""A user-connected model may carry the provider's own alias; kernel pins may not.

THE BUG THIS PINS. On 2026-08-20 a member connecting their own self-hosted
model could not submit ANY spelling of its name: the bare name failed gateway
verification (the provider lists only tagged ids), and ``:latest`` - the name
the provider itself lists - was refused as a "mutable model alias", surfacing
as a bare 500 after the key was already sealed, approved and applied. On a
self-hosted server every tag is re-pointable, so the blocklist refused the
common spelling without making anything immutable. ``user_model_id`` accepts
the provider's naming for the user-BYO lane; ``exact_model_id`` keeps the full
policy for kernel-configured artifacts, whose ids an audit trail relies on.
"""

import pytest

from boltrig.models.model_id_policy import exact_model_id, user_model_id


def test_user_model_id_accepts_the_providers_own_alias_tags() -> None:
    assert user_model_id("ollama/qwen3vl-abliterated:latest") == (
        "ollama/qwen3vl-abliterated:latest"
    )
    assert user_model_id("qwen3vl-abliterated:latest") == "qwen3vl-abliterated:latest"
    assert user_model_id("openai/chatgpt-4o-latest") == "openai/chatgpt-4o-latest"


def test_exact_model_id_still_refuses_mutable_aliases() -> None:
    with pytest.raises(ValueError, match="mutable model alias"):
        exact_model_id("ollama/qwen3vl-abliterated:latest")
    with pytest.raises(ValueError, match="mutable model alias"):
        exact_model_id("gpt-5-preview")


@pytest.mark.parametrize(
    "bad",
    [None, 7, "", " gpt", "a/../b", "a//b", "/gpt", "x" * 200, "gpt 5"],
)
def test_user_model_id_keeps_shape_and_path_refusals(bad: object) -> None:
    with pytest.raises(ValueError):
        user_model_id(bad)


def test_the_two_policies_agree_on_everything_except_aliases() -> None:
    exact = exact_model_id("ollama/qwen3vl-abliterated:34ba10f8b5e0")
    assert user_model_id(exact) == exact
