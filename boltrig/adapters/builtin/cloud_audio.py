"""Governed cloud and OpenAI-compatible speech adapters.

The public ``voice.*`` contract is intentionally provider-neutral: TTS accepts
text plus an optional voice/model, STT accepts one bounded base64 clip, and a
provider may expose a voice catalogue when it has one.  Provider credentials
are resolved by the kernel for one invocation and never enter the result.

Deepgram, ElevenLabs and OpenAI use different HTTP shapes, so the carrier code
is shared here while each adapter keeps its own paths, authentication and
payload mapping.  ``openai-compatible-audio`` is the server-reachable local or
private-service seam.  Its URL is supplied through the sealed connection and
still passes the ordinary egress/SSRF guard; it is not a browser-to-LAN escape.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, bearer_token
from boltrig.adapters.builtin.cloud_audio_base import CloudAudioAdapter, audio_content_type
from boltrig.adapters.http_response import MAX_JSON_RESPONSE_BYTES
from boltrig.models import InvocationContext

_ELEVENLABS_VOICE_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")


class DeepgramAudioAdapter(CloudAudioAdapter):
    id = "deepgram-audio"
    version = "0.1.0"
    user_agent = "boltrig-deepgram-audio/1.0"
    default_tts_model = "aura-2-thalia-en"
    default_stt_model = "nova-3"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(base_url="https://api.deepgram.com", **kwargs)

    def _auth(self, credential: Credential) -> tuple[dict[str, str], httpx.Auth | None]:
        token = bearer_token(credential)
        return ({"Authorization": f"Token {token}"} if token else {}), None

    async def _speak(
        self,
        params: dict[str, Any],
        client: httpx.AsyncClient,
        context: InvocationContext,
    ) -> Result:
        text = self._text(params)
        if isinstance(text, AdapterError):
            return Result.failure(text)
        model = str(params.get("model") or params.get("voice") or self.default_tts_model)
        fmt = str(params.get("format") or self.default_format)
        response = await self._raw_request(
            client,
            "POST",
            "/v1/speak",
            params={"model": model, "encoding": fmt},
            json={"text": text},
            headers={"Accept": "application/octet-stream"},
        )
        if isinstance(response, AdapterError):
            return Result.failure(response)
        return self._audio_result(response, voice=model, model=model, chars=len(text))

    async def _listen(
        self,
        params: dict[str, Any],
        client: httpx.AsyncClient,
        context: InvocationContext,
    ) -> Result:
        decoded = self._audio(params)
        if isinstance(decoded, AdapterError):
            return Result.failure(decoded)
        audio, filename = decoded
        model = str(params.get("model") or self.default_stt_model)
        query = {"model": model, "smart_format": "true"}
        if params.get("language"):
            query["language"] = str(params["language"])
        response = await self._raw_request(
            client,
            "POST",
            "/v1/listen",
            params=query,
            content=audio,
            headers={"Content-Type": audio_content_type(filename)},
            max_bytes=MAX_JSON_RESPONSE_BYTES,
        )
        if isinstance(response, AdapterError):
            return Result.failure(response)
        try:
            body = response.json()
        except ValueError:
            return Result.failure(AdapterError(ErrorClass.UNAVAILABLE, "transcript was not JSON"))
        channels = (
            ((body.get("results") or {}).get("channels") or []) if isinstance(body, dict) else []
        )
        alternatives = (
            channels[0].get("alternatives", [])
            if channels and isinstance(channels[0], dict)
            else []
        )
        first = alternatives[0] if alternatives and isinstance(alternatives[0], dict) else {}
        return Result.success({"text": str(first.get("transcript") or ""), "model": model})


class ElevenLabsAudioAdapter(CloudAudioAdapter):
    id = "elevenlabs-audio"
    version = "0.1.0"
    user_agent = "boltrig-elevenlabs-audio/1.0"
    default_tts_model = "eleven_multilingual_v2"
    default_stt_model = "scribe_v2"
    exposes_voices = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(base_url="https://api.elevenlabs.io", **kwargs)

    def _auth(self, credential: Credential) -> tuple[dict[str, str], httpx.Auth | None]:
        token = bearer_token(credential)
        return ({"xi-api-key": token} if token else {}), None

    async def _speak(
        self,
        params: dict[str, Any],
        client: httpx.AsyncClient,
        context: InvocationContext,
    ) -> Result:
        text = self._text(params)
        if isinstance(text, AdapterError):
            return Result.failure(text)
        voice = str(params.get("voice") or "")
        if not _ELEVENLABS_VOICE_ID.fullmatch(voice):
            return Result.failure(AdapterError(ErrorClass.INVALID, "invalid voice id"))
        model = str(params.get("model") or self.default_tts_model)
        fmt = str(params.get("format") or "mp3_44100_128")
        response = await self._raw_request(
            client,
            "POST",
            f"/v1/text-to-speech/{voice}",
            params={"output_format": fmt},
            json={"text": text, "model_id": model},
            headers={"Accept": "audio/mpeg"},
        )
        if isinstance(response, AdapterError):
            return Result.failure(response)
        return self._audio_result(response, voice=voice, model=model, chars=len(text))

    async def _listen(
        self,
        params: dict[str, Any],
        client: httpx.AsyncClient,
        context: InvocationContext,
    ) -> Result:
        decoded = self._audio(params)
        if isinstance(decoded, AdapterError):
            return Result.failure(decoded)
        audio, filename = decoded
        model = str(params.get("model") or self.default_stt_model)
        data = {"model_id": model}
        if params.get("language"):
            data["language_code"] = str(params["language"])
        response = await self._raw_request(
            client,
            "POST",
            "/v1/speech-to-text",
            files={"file": (filename, audio, audio_content_type(filename))},
            data=data,
            max_bytes=MAX_JSON_RESPONSE_BYTES,
        )
        if isinstance(response, AdapterError):
            return Result.failure(response)
        try:
            body = response.json()
        except ValueError:
            return Result.failure(AdapterError(ErrorClass.UNAVAILABLE, "transcript was not JSON"))
        return Result.success({"text": str(body.get("text") or ""), "model": model})

    async def _voices_list(
        self,
        params: dict[str, Any],
        client: httpx.AsyncClient,
        context: InvocationContext,
    ) -> Result:
        response = await self._raw_request(
            client,
            "GET",
            "/v2/voices",
            params={"page_size": "100"},
            max_bytes=MAX_JSON_RESPONSE_BYTES,
        )
        if isinstance(response, AdapterError):
            return Result.failure(response)
        try:
            body = response.json()
        except ValueError:
            return Result.failure(
                AdapterError(ErrorClass.UNAVAILABLE, "voice catalogue was not JSON")
            )
        voices = body.get("voices", []) if isinstance(body, dict) else []
        return Result.success({"voices": voices[:100] if isinstance(voices, list) else []})


class OpenAIAudioAdapter(CloudAudioAdapter):
    id = "openai-audio"
    version = "0.1.0"
    user_agent = "boltrig-openai-audio/1.0"
    default_tts_model = "gpt-4o-mini-tts"
    default_stt_model = "gpt-4o-mini-transcribe"
    default_voice = "alloy"

    def __init__(
        self,
        *,
        adapter_id: str = "openai-audio",
        base_url: str = "https://api.openai.com",
        **kwargs: Any,
    ) -> None:
        self.id = adapter_id
        self.allow_keyless = adapter_id == "openai-compatible-audio"
        super().__init__(base_url=base_url, **kwargs)

    def _auth(self, credential: Credential) -> tuple[dict[str, str], httpx.Auth | None]:
        token = bearer_token(credential)
        return ({"Authorization": f"Bearer {token}"} if token else {}), None

    async def _speak(
        self,
        params: dict[str, Any],
        client: httpx.AsyncClient,
        context: InvocationContext,
    ) -> Result:
        text = self._text(params)
        if isinstance(text, AdapterError):
            return Result.failure(text)
        voice = str(params.get("voice") or self.default_voice)
        model = str(params.get("model") or self.default_tts_model)
        fmt = str(params.get("format") or self.default_format)
        response = await self._raw_request(
            client,
            "POST",
            "/v1/audio/speech",
            json={"input": text, "model": model, "voice": voice, "response_format": fmt},
            headers={"Accept": "application/octet-stream"},
        )
        if isinstance(response, AdapterError):
            return Result.failure(response)
        return self._audio_result(response, voice=voice, model=model, chars=len(text))

    async def _listen(
        self,
        params: dict[str, Any],
        client: httpx.AsyncClient,
        context: InvocationContext,
    ) -> Result:
        decoded = self._audio(params)
        if isinstance(decoded, AdapterError):
            return Result.failure(decoded)
        audio, filename = decoded
        model = str(params.get("model") or self.default_stt_model)
        data = {"model": model}
        if params.get("language"):
            data["language"] = str(params["language"])
        response = await self._raw_request(
            client,
            "POST",
            "/v1/audio/transcriptions",
            files={"file": (filename, audio, audio_content_type(filename))},
            data=data,
            max_bytes=MAX_JSON_RESPONSE_BYTES,
        )
        if isinstance(response, AdapterError):
            return Result.failure(response)
        try:
            body = response.json()
        except ValueError:
            return Result.failure(AdapterError(ErrorClass.UNAVAILABLE, "transcript was not JSON"))
        return Result.success({"text": str(body.get("text") or ""), "model": model})


def build_deepgram() -> DeepgramAudioAdapter:
    return DeepgramAudioAdapter()


def build_elevenlabs() -> ElevenLabsAudioAdapter:
    return ElevenLabsAudioAdapter()


def build_openai() -> OpenAIAudioAdapter:
    return OpenAIAudioAdapter()


def build_openai_compatible() -> OpenAIAudioAdapter:
    return OpenAIAudioAdapter(adapter_id="openai-compatible-audio", base_url="")


__all__ = [
    "DeepgramAudioAdapter",
    "ElevenLabsAudioAdapter",
    "OpenAIAudioAdapter",
    "build_deepgram",
    "build_elevenlabs",
    "build_openai",
    "build_openai_compatible",
]
