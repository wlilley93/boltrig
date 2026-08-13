"""xAI voice adapter: TTS/STT behind governed verbs (mirrors test_runpod_adapter)."""

import base64
import socket

import httpx
import pytest

from boltrig.adapters.base import Credential
from boltrig.adapters.builtin.xai_voice import XaiVoiceAdapter
from boltrig.adapters.http_response import MAX_BINARY_RESPONSE_BYTES
from boltrig.models import GrantSet, InvocationContext

T = "acme"
_PUBLIC_IP = "93.184.216.34"


def _ctx():
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="tester")


def _cred():
    return Credential(id="XAI_API_KEY", kind="api_key", material={"value": "xai_secret"})


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    # The base's per-request egress guard resolves the host; keep the test
    # hermetic by resolving everything to a public IP.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port=None, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (_PUBLIC_IP, port or 0))
        ],
    )


def _adapter(handler) -> XaiVoiceAdapter:
    return XaiVoiceAdapter(transport=httpx.MockTransport(handler))


def test_xai_voice_declares_verbs_with_consequences():
    verbs = {spec.verb_id: spec for spec in XaiVoiceAdapter().describe()}
    assert verbs["voice.speak"].consequence == "high"  # spends money
    assert verbs["voice.listen"].consequence == "low"
    assert verbs["voice.voices.list"].consequence == "low"
    assert verbs["voice.speak"].input_schema["required"] == ["text"]
    assert verbs["voice.listen"].input_schema["required"] == ["audio_b64"]


@pytest.mark.invariant("SEC-05")
async def test_speak_uses_bearer_and_never_leaks_the_credential():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update({
            "method": request.method,
            "path": request.url.path,
            "authorization": request.headers.get("authorization"),
        })
        return httpx.Response(
            200, content=b"\xff\xfb\x90audio-bytes",
            headers={"Content-Type": "audio/mpeg"},
        )

    result = await _adapter(handler).execute(
        "voice.speak", {"text": "hello nabu", "voice": "eve"}, _cred(), _ctx()
    )

    assert result.ok
    assert seen["method"] == "POST"
    assert seen["path"] == "/v1/tts"
    assert seen["authorization"] == "Bearer xai_secret"
    assert base64.b64decode(result.output["audio_b64"]) == b"\xff\xfb\x90audio-bytes"
    assert result.output["content_type"] == "audio/mpeg"
    assert result.output["voice"] == "eve"
    assert result.output["chars"] == len("hello nabu")
    rendered = repr(result.output) + repr(result)
    assert "xai_secret" not in rendered
    assert "XAI_API_KEY" not in repr(result)


async def test_listen_posts_multipart_and_normalises_the_transcript():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update({
            "path": request.url.path,
            "content_type": request.headers.get("content-type"),
            "body": request.content,
        })
        return httpx.Response(200, json={
            "text": "turn the lights on",
            "words": [{"word": "turn", "start": 0.0, "end": 0.2}],
            "duration": 1.4,
        })

    audio = base64.b64encode(b"fake-pcm").decode("ascii")
    result = await _adapter(handler).execute(
        "voice.listen",
        {"audio_b64": audio, "filename": "clip.wav", "language": "en"},
        _cred(), _ctx(),
    )

    assert result.ok
    assert seen["path"] == "/v1/stt"
    assert seen["content_type"].startswith("multipart/form-data")
    assert b'filename="clip.wav"' in seen["body"]
    assert b"fake-pcm" in seen["body"]
    assert b"language" in seen["body"]
    assert result.output["text"] == "turn the lights on"
    assert result.output["words"][0]["word"] == "turn"
    assert result.output["duration_seconds"] == 1.4


async def test_voices_list_gets_the_catalogue():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/tts/voices"
        return httpx.Response(200, json={"voices": [{"id": "eve"}, {"id": "ara"}]})

    result = await _adapter(handler).execute("voice.voices.list", {}, _cred(), _ctx())

    assert result.ok
    assert [v["id"] for v in result.output["voices"]] == ["eve", "ara"]


@pytest.mark.invariant("SEC-05")
async def test_missing_credential_fails_closed():
    result = await XaiVoiceAdapter().execute("voice.speak", {"text": "hi"}, None, _ctx())
    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "unauthorised"


@pytest.mark.parametrize(
    ("status", "error_class"),
    [
        (401, "unauthorised"),
        (403, "unauthorised"),
        (429, "rate_limited"),
        (400, "invalid"),
        (413, "invalid"),
        (500, "unavailable"),
    ],
)
async def test_error_status_maps_to_typed_error(status, error_class):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "x"})

    result = await _adapter(handler).execute(
        "voice.speak", {"text": "hi"}, _cred(), _ctx()
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == error_class


async def test_speak_rejects_text_over_the_tts_bound():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the request must never leave the adapter")

    result = await _adapter(handler).execute(
        "voice.speak", {"text": "x" * 15001}, _cred(), _ctx()
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "invalid"
    assert not result.error.retryable


@pytest.mark.invariant("SEC-196")
async def test_speak_rejects_oversize_audio_without_buffering_it():
    class NeverReadStream(httpx.AsyncByteStream):
        reads = 0

        async def __aiter__(self):
            self.reads += 1
            yield b"must-not-be-read"

        async def aclose(self) -> None:
            return None

    stream = NeverReadStream()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Type": "audio/mpeg",
                "Content-Length": str(MAX_BINARY_RESPONSE_BYTES + 1),
            },
            stream=stream,
        )

    result = await _adapter(handler).execute(
        "voice.speak", {"text": "hello"}, _cred(), _ctx()
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "unavailable"
    assert result.error.retryable is False
    assert stream.reads == 0


async def test_listen_rejects_non_base64_audio():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the request must never leave the adapter")

    result = await _adapter(handler).execute(
        "voice.listen", {"audio_b64": "!!!not-base64!!!"}, _cred(), _ctx()
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "invalid"


async def test_unknown_verb_is_invalid():
    result = await _adapter(lambda r: httpx.Response(200)).execute(
        "voice.unknown", {}, _cred(), _ctx()
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "invalid"
