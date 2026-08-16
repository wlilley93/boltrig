"""The generated-adapter spec fetch is BOUNDED.

``/v1/adapters/generate`` accepts a URL (author-tier, pre-HITL). The fetch was
SSRF-guarded and pinned but read ``resp.text`` whole, so an author pointing the
generator at a multi-gigabyte body ballooned kernel memory per request before
YAML ever parsed. A spec is kilobytes."""

from __future__ import annotations

import pytest

from boltrig.adapters import generator

pytestmark = pytest.mark.unit


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self) -> None:
        pass

    def iter_bytes(self, _n: int):
        return iter(self._chunks)


class _FakeClient:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def stream(self, _method: str, _url: str) -> _FakeStream:
        return _FakeStream(self._chunks)


def _patch_fetch(monkeypatch, chunks):
    def _fake_pinned(url, **kwargs):
        return _FakeClient(chunks)

    monkeypatch.setattr("boltrig.adapters.egress.pinned_sync_client", _fake_pinned)


async def test_a_small_spec_fetches_whole(monkeypatch):
    _patch_fetch(monkeypatch, [b"openapi: 3.1.0\n", b"info: {}"])
    text = generator._fetch("https://spec.example/openapi.yaml")
    assert text.startswith("openapi:")


async def test_an_oversized_spec_body_is_refused_not_buffered(monkeypatch):
    # 5 MiB in 64 KiB chunks over the 4 MiB cap: the refusal must fire DURING
    # the stream, not after buffering the whole body.
    chunks = [b"x" * 65536] * 80  # 5 MiB
    _patch_fetch(monkeypatch, chunks)
    with pytest.raises(ValueError, match="byte cap"):
        generator._fetch("https://spec.example/huge.yaml")
