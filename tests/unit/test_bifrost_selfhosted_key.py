"""A self-hosted provider's key carries its server URL, not just a placeholder.

THE BUG THIS PINS. Selecting Ollama in the model picker ended in "Bifrost
refused the provider key". Reproduced against a live Bifrost on 2026-08-17:

    POST /api/providers/ollama/keys -> 400
      {"error":{"message":"ollama_key_config.url is required for Ollama keys"}}

`ensure_provider_key` sent one generic payload for every provider. For a KEYED
provider that is right -- the key is the whole configuration. For a self-hosted
one it cannot be: the key is a placeholder for a server that authenticates
nothing, and the address is what actually identifies it. Bifrost asks for the
address in a provider-specific block, so the generic payload could never
succeed and Ollama was unusable however it was configured.

The URL was never missing. `AiKeyResolution.base_url` already carried it and the
spawner already used it for routing; the Bifrost admin was the one caller that
never received it.
"""

import pytest

from boltrig.identity.bifrost_user_admin import BifrostUserAdmin
from boltrig.identity.bifrost_user_binding import BifrostUserBindingUnavailable


class _Http:
    """Records what would have gone to Bifrost, and answers 404 for the check."""

    base = "http://bifrost:8080/"

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []

    async def request(self, method, url, payload=None):
        if method == "GET":
            return 404, {}
        self.posts.append((url, payload or {}))
        return 200, {}


def _admin(http: _Http) -> BifrostUserAdmin:
    admin = BifrostUserAdmin.__new__(BifrostUserAdmin)
    admin._http = http  # noqa: SLF001 - constructing the collaborator directly
    return admin


class TestSelfHostedProviders:
    @pytest.mark.asyncio
    async def test_ollama_sends_its_server_url_in_the_provider_block(self):
        http = _Http()
        await _admin(http).ensure_provider_key(
            "ollama", "k1", "qwen3vl", "keyless", base_url="http://mac-mini-m1:11434"
        )
        _url, payload = http.posts[0]
        # The exact field Bifrost names in its rejection message.
        assert payload["ollama_key_config"] == {"url": "http://mac-mini-m1:11434"}
        # And the placeholder key still rides along: the sealed-proposal path
        # needs non-empty secret material even for a server that ignores it.
        assert payload["value"]["value"] == "keyless"

    @pytest.mark.asyncio
    async def test_a_missing_url_is_refused_HERE_with_a_usable_message(self):
        """Rather than letting Bifrost answer 400 with an opaque wrapper.

        The old path surfaced "Bifrost refused the provider key", which names
        no field and cost a live reproduction to diagnose. A missing base URL is
        a configuration mistake the operator can fix, so the message says so.
        """
        http = _Http()
        with pytest.raises(BifrostUserBindingUnavailable, match="URL of its server"):
            await _admin(http).ensure_provider_key("ollama", "k1", "qwen3vl", "keyless")
        assert http.posts == [], "nothing should be sent when the URL is missing"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("blank", ["", "   ", None])
    async def test_a_blank_url_counts_as_missing(self, blank):
        with pytest.raises(BifrostUserBindingUnavailable):
            await _admin(_Http()).ensure_provider_key(
                "ollama", "k1", "qwen3vl", "keyless", base_url=blank
            )


class TestKeyedProvidersAreUnaffected:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider", ["openai", "anthropic", "groq"])
    async def test_no_provider_block_is_added(self, provider):
        """The change must be invisible to every provider that was working.

        A blanket URL requirement would have broken every keyed provider, which
        is the obvious wrong fix for this bug.
        """
        http = _Http()
        await _admin(http).ensure_provider_key(provider, "k1", "gpt-4", "sk-real")
        _url, payload = http.posts[0]
        assert "ollama_key_config" not in payload
        assert payload["value"]["value"] == "sk-real"

    @pytest.mark.asyncio
    async def test_a_keyed_provider_does_not_require_a_url(self):
        http = _Http()
        await _admin(http).ensure_provider_key("openai", "k1", "gpt-4", "sk-real")
        assert len(http.posts) == 1
