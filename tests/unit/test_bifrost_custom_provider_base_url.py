"""A custom provider's endpoint must land where Bifrost actually keeps it.

THE BUG THIS PINS. Binding z.ai ended in:

    zai-coding-plan is already bound to a different endpoint;
    remove that binding first or use its address

There was no rival endpoint. Measured against the deployed gateway on
2026-08-23, Bifrost accepts ``custom_provider_config.base_url`` with a **200**
and then DISCARDS it: a freshly created provider reads back carrying only
``{"is_key_less": false, "base_provider_type": "openai"}`` and
``provider_status: "error"``. The same URL sent under ``network_config``
persists. Bifrost's own native rows agree - the cerebras row on the Opbox
gateway stores ``network_config.base_url: https://api.cerebras.ai``.

So the address was never recorded, and two things followed. The provider could
never work, because it had no address to call. And ``ensure_provider`` read the
address back from the field Bifrost had dropped, got ``None``, compared it to
the URL being requested, and refused - meaning **every retry after the first
failed, and the first silently created a broken row.** Every zai row on the
estate was in that state.

The message was wrong too: "bound to a different endpoint" describes a
conflict, when the truth was no endpoint at all, and it sent an operator
hunting for a rival binding that did not exist.
"""

import pytest

from boltrig.identity.bifrost_user_admin import BifrostUserAdmin
from boltrig.identity.bifrost_user_binding import BifrostUserBindingUnavailable

URL = "https://api.z.ai/api/coding/paas/v4"


class _Http:
    """Answers the provider listing, and records what would have been POSTed."""

    base = "http://bifrost:8080/"

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.posts: list[tuple[str, dict]] = []

    async def request_json(self, method, url):
        return {"providers": self.rows}

    async def request(self, method, url, payload=None):
        self.posts.append((url, payload or {}))
        return 200, {}


def _admin(http: _Http) -> BifrostUserAdmin:
    admin = BifrostUserAdmin.__new__(BifrostUserAdmin)
    admin._http = http  # noqa: SLF001 - constructing the collaborator directly
    return admin


class TestTheAddressIsSentWhereBifrostKeepsIt:
    @pytest.mark.asyncio
    async def test_a_new_custom_provider_carries_its_url_in_network_config(self):
        http = _Http()
        await _admin(http).ensure_provider("zai-coding-plan", base_url=URL)
        _url, body = http.posts[0]
        assert body["network_config"]["base_url"] == URL

    @pytest.mark.asyncio
    async def test_the_custom_provider_config_spelling_is_kept_too(self):
        """Harmless on the gateway that drops it, correct on one that does not."""
        http = _Http()
        await _admin(http).ensure_provider("zai-coding-plan", base_url=URL)
        _url, body = http.posts[0]
        assert body["custom_provider_config"]["base_url"] == URL

    @pytest.mark.asyncio
    async def test_a_native_provider_still_sends_no_address(self):
        http = _Http()
        await _admin(http).ensure_provider("cerebras")
        _url, body = http.posts[0]
        assert "network_config" not in body
        assert "custom_provider_config" not in body


class TestReadingBackWhatBifrostRecorded:
    @pytest.mark.asyncio
    async def test_a_matching_row_stored_under_network_config_is_accepted(self):
        """The regression: this used to raise, refusing its own earlier write."""
        http = _Http(
            [{"name": "zai-coding-plan", "network_config": {"base_url": URL}}]
        )
        await _admin(http).ensure_provider("zai-coding-plan", base_url=URL)
        assert http.posts == []  # already correct: nothing re-created

    @pytest.mark.asyncio
    async def test_a_matching_row_stored_the_old_way_is_still_accepted(self):
        http = _Http(
            [
                {
                    "name": "zai-coding-plan",
                    "custom_provider_config": {"base_url": URL},
                }
            ]
        )
        await _admin(http).ensure_provider("zai-coding-plan", base_url=URL)
        assert http.posts == []

    @pytest.mark.asyncio
    async def test_a_genuinely_different_address_is_still_refused(self):
        http = _Http(
            [
                {
                    "name": "zai-coding-plan",
                    "network_config": {"base_url": "https://elsewhere.example/v1"},
                }
            ]
        )
        with pytest.raises(BifrostUserBindingUnavailable) as err:
            await _admin(http).ensure_provider("zai-coding-plan", base_url=URL)
        assert "already bound to a different endpoint" in str(err.value)

    @pytest.mark.asyncio
    async def test_an_addressless_row_says_so_instead_of_claiming_a_conflict(self):
        """The message that sent an operator looking for a rival binding."""
        http = _Http(
            [
                {
                    "name": "zai-coding-plan",
                    "custom_provider_config": {"base_provider_type": "openai"},
                }
            ]
        )
        with pytest.raises(BifrostUserBindingUnavailable) as err:
            await _admin(http).ensure_provider("zai-coding-plan", base_url=URL)
        message = str(err.value)
        assert "no endpoint recorded" in message
        assert "already bound to a different endpoint" not in message
