"""Cloud audio providers share one governed voice contract without sharing secrets."""

import base64
import json
import socket

import httpx
import pytest

from boltrig.adapters.base import Credential
from boltrig.adapters.builtin.cloud_audio import (
    DeepgramAudioAdapter,
    ElevenLabsAudioAdapter,
    OpenAIAudioAdapter,
)
from boltrig.adapters.loader import AdapterLoader
from boltrig.models import GrantSet, InvocationContext


def _ctx() -> InvocationContext:
    return InvocationContext(tenant_id="acme", actor="owner", grants=GrantSet.of(["*"]))


def _credential(**material: str) -> Credential:
    return Credential(
        id="sealed-voice", kind="api_key", material=material or {"api_key": "voice-secret"}
    )


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port=None, *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))
        ],
    )


def test_cloud_audio_verbs_are_bounded_and_setup_ready_is_not_ok_health() -> None:
    for adapter in (
        DeepgramAudioAdapter(),
        ElevenLabsAudioAdapter(),
        OpenAIAudioAdapter(),
    ):
        verbs = {spec.verb_id: spec for spec in adapter.describe()}
        assert verbs["voice.speak"].consequence == "high"
        assert verbs["voice.speak"].input_schema["properties"]["text"]["maxLength"] == 15_000
        assert (
            verbs["voice.listen"].input_schema["properties"]["audio_b64"]["maxLength"] == 32_000_000
        )
        loader = AdapterLoader()
        loader.register("acme", adapter)
        assert loader.health_of("acme", adapter.id) == "degraded"


@pytest.mark.invariant("SEC-05")
async def test_deepgram_maps_tts_and_stt_without_projecting_the_key() -> None:
    seen: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path == "/v1/speak":
            assert request.url.params["model"] == "aura-custom"
            assert json.loads(request.content)["text"] == "Hello"
            return httpx.Response(
                200, content=b"deepgram-audio", headers={"Content-Type": "audio/mpeg"}
            )
        assert request.url.path == "/v1/listen"
        assert request.url.params["model"] == "nova-3"
        assert request.content == b"clip"
        return httpx.Response(
            200, json={"results": {"channels": [{"alternatives": [{"transcript": "hello"}]}]}}
        )

    adapter = DeepgramAudioAdapter(transport=httpx.MockTransport(handler))
    credential = _credential()
    spoken = await adapter.execute(
        "voice.speak", {"text": "Hello", "voice": "aura-custom"}, credential, _ctx()
    )
    listened = await adapter.execute(
        "voice.listen",
        {"audio_b64": base64.b64encode(b"clip").decode(), "filename": "clip.wav"},
        credential,
        _ctx(),
    )

    assert spoken.ok and base64.b64decode(spoken.output["audio_b64"]) == b"deepgram-audio"
    assert listened.ok and listened.output["text"] == "hello"
    assert all(auth == "Token voice-secret" for _, _, auth in seen)
    assert "voice-secret" not in repr(spoken) + repr(listened)


@pytest.mark.invariant("SEC-05")
async def test_elevenlabs_maps_voice_catalogue_tts_and_transcription() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.headers["xi-api-key"] == "voice-secret"
        if request.url.path == "/v1/text-to-speech/voice-7":
            assert json.loads(request.content)["model_id"] == "eleven_multilingual_v2"
            return httpx.Response(
                200, content=b"eleven-audio", headers={"Content-Type": "audio/mpeg"}
            )
        if request.url.path == "/v1/speech-to-text":
            assert b"scribe_v2" in request.content
            return httpx.Response(200, json={"text": "transcribed"})
        assert request.url.path == "/v2/voices"
        return httpx.Response(200, json={"voices": [{"voice_id": "voice-7"}]})

    adapter = ElevenLabsAudioAdapter(transport=httpx.MockTransport(handler))
    credential = _credential()
    spoken = await adapter.execute(
        "voice.speak", {"text": "Hello", "voice": "voice-7"}, credential, _ctx()
    )
    listened = await adapter.execute(
        "voice.listen", {"audio_b64": base64.b64encode(b"clip").decode()}, credential, _ctx()
    )
    voices = await adapter.execute("voice.voices.list", {}, credential, _ctx())

    assert spoken.ok
    assert listened.ok and listened.output["text"] == "transcribed"
    assert voices.ok and voices.output["voices"] == [{"voice_id": "voice-7"}]
    assert paths == ["/v1/text-to-speech/voice-7", "/v1/speech-to-text", "/v2/voices"]


@pytest.mark.invariant("SEC-05")
async def test_openai_audio_supports_official_and_keyless_server_reachable_endpoint() -> None:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get("authorization")))
        if request.url.path == "/v1/audio/speech":
            return httpx.Response(
                200, content=b"openai-audio", headers={"Content-Type": "audio/mpeg"}
            )
        return httpx.Response(200, json={"text": "heard"})

    official = OpenAIAudioAdapter(transport=httpx.MockTransport(handler))
    result = await official.execute("voice.speak", {"text": "Hello"}, _credential(), _ctx())
    assert result.ok
    assert seen[-1] == ("/v1/audio/speech", "Bearer voice-secret")

    custom = OpenAIAudioAdapter(
        adapter_id="openai-compatible-audio",
        base_url="",
        transport=httpx.MockTransport(handler),
    )
    keyless = _credential(base_url="https://speech.example.com")
    result = await custom.execute(
        "voice.listen", {"audio_b64": base64.b64encode(b"clip").decode()}, keyless, _ctx()
    )
    assert result.ok and result.output["text"] == "heard"
    assert seen[-1] == ("/v1/audio/transcriptions", None)


async def test_cloud_providers_fail_closed_without_required_credentials() -> None:
    for adapter in (
        DeepgramAudioAdapter(),
        ElevenLabsAudioAdapter(),
        OpenAIAudioAdapter(),
    ):
        result = await adapter.execute("voice.speak", {"text": "Hello"}, None, _ctx())
        assert not result.ok
        assert result.error is not None and result.error.error_class.value == "unauthorised"


async def test_invalid_audio_is_refused_before_provider_io() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid audio must not leave the adapter")

    result = await DeepgramAudioAdapter(transport=httpx.MockTransport(handler)).execute(
        "voice.listen", {"audio_b64": "not-base64"}, _credential(), _ctx()
    )
    assert not result.ok
    assert result.error is not None and result.error.error_class.value == "invalid"


async def test_elevenlabs_voice_id_cannot_reshape_the_provider_path() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("an invalid voice id must not leave the adapter")

    result = await ElevenLabsAudioAdapter(transport=httpx.MockTransport(handler)).execute(
        "voice.speak",
        {"text": "Hello", "voice": "../speech-to-text"},
        _credential(),
        _ctx(),
    )
    assert not result.ok
    assert result.error is not None and result.error.error_class.value == "invalid"
