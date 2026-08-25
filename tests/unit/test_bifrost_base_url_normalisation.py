"""Bifrost appends `/v1`, and the catalogue publishes bases that already end in it.

The catalogue's published base is submitted silently (the screen shows no address
field when it has one), so a doubled path is invisible to whoever is onboarding:
Bifrost marks the key `list_models_failed` and the UI reports "your provider did
not answer at that address" about an address the user cannot see or edit.

Probed all 161 catalogue providers publishing a base, from the kernel container,
2026-08-24, counting 200/401/403 as "the path is really there":

    Bifrost's path reachable BEFORE stripping:   62/161
    Bifrost's path reachable AFTER  stripping:  147/161
    newly working: 85          regressed: 0
"""

from __future__ import annotations

from boltrig.identity.bifrost_user_transport import (
    bifrost_base_url,
    custom_provider_body,
    custom_provider_dialect,
)


def test_one_trailing_v1_is_stripped_because_bifrost_re_adds_it() -> None:
    assert bifrost_base_url("abliteration-ai", "https://api.abliteration.ai/v1") == (
        "https://api.abliteration.ai"
    )
    # measured: .../compatible-mode/v1/models is 401, so the stripped base plus
    # Bifrost's /v1 lands exactly back on the working path.
    assert bifrost_base_url("alibaba", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1") == (
        "https://dashscope-intl.aliyuncs.com/compatible-mode"
    )


def test_only_one_v1_is_stripped() -> None:
    """Two would be a different bug, and a base genuinely ending /v1/v1 is not
    something to guess at."""
    assert bifrost_base_url("x", "https://h/v1/v1") == "https://h/v1"


def test_a_base_without_a_version_suffix_is_untouched() -> None:
    assert bifrost_base_url("github-copilot", "https://api.githubcopilot.com") == (
        "https://api.githubcopilot.com"
    )
    # A trailing slash is not a version segment.
    assert bifrost_base_url("x", "https://h/") == "https://h"
    # `/v2` is not `/v1`: stripping it would invent a path.
    assert bifrost_base_url("x", "https://h/api/v2") == "https://h/api/v2"


def test_zai_rides_its_anthropic_base_where_the_appended_v1_is_real() -> None:
    """Measured: .../api/anthropic/v1/models -> 200, while the OpenAI-shaped
    .../coding/paas/v4/v1/models -> 404 and .../coding/paas/v4/models -> 401."""
    for pid in ("zai", "zai-coding-plan"):
        assert bifrost_base_url(pid, "https://api.z.ai/api/coding/paas/v4") == (
            "https://api.z.ai/api/anthropic"
        )
        assert custom_provider_dialect(pid) == "anthropic"


def test_everything_else_stays_on_the_openai_dialect() -> None:
    """The anthropic set is an exception list, so it must not widen silently."""
    for pid in ("alibaba", "abliteration-ai", "openrouter", "ZAI-LOOKALIKE"):
        assert custom_provider_dialect(pid) == "openai"


def test_the_body_carries_the_address_in_both_places() -> None:
    """Bifrost drops base_url from custom_provider_config and reads
    network_config, so sending only the former loses the address with no error."""
    body = custom_provider_body("zai-coding-plan", "https://api.z.ai/api/anthropic")
    assert body["network_config"]["base_url"] == "https://api.z.ai/api/anthropic"
    assert body["custom_provider_config"]["base_url"] == "https://api.z.ai/api/anthropic"
    assert body["custom_provider_config"]["base_provider_type"] == "anthropic"
