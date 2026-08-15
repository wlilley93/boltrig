"""Shared bounded transport for provider-neutral speech adapters."""

from __future__ import annotations

import base64
import binascii
from typing import Any

import httpx

from boltrig.adapters.base import (
    AdapterError,
    Credential,
    ErrorClass,
    Result,
    VerbSpec,
    bearer_token,
)
from boltrig.adapters.egress import EgressBlocked, assert_egress_allowed
from boltrig.adapters.http_base import Handler, HttpAdapter
from boltrig.adapters.http_response import (
    MAX_BINARY_RESPONSE_BYTES,
    ResponseBoundaryError,
    bounded_http_response,
    bounded_response_error,
)
from boltrig.models import InvocationContext

MAX_TEXT_CHARS = 15_000
MAX_AUDIO_B64_CHARS = 32_000_000
MAX_FILENAME_CHARS = 255
MAX_MODEL_CHARS = 160
MAX_VOICE_CHARS = 160

_AUDIO_CONTENT_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".pcm": "audio/pcm",
}


def _speak_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT_CHARS},
            "voice": {"type": "string", "maxLength": MAX_VOICE_CHARS},
            "model": {"type": "string", "maxLength": MAX_MODEL_CHARS},
            "format": {"type": "string", "maxLength": 24},
        },
        "required": ["text"],
        "additionalProperties": False,
    }


def _listen_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "audio_b64": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_AUDIO_B64_CHARS,
            },
            "filename": {"type": "string", "maxLength": MAX_FILENAME_CHARS},
            "language": {"type": "string", "maxLength": 32},
            "model": {"type": "string", "maxLength": MAX_MODEL_CHARS},
        },
        "required": ["audio_b64"],
        "additionalProperties": False,
    }


def _empty_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "additionalProperties": False}


class CloudAudioAdapter(HttpAdapter):
    """Common execution, limits, and result projection for speech providers."""

    source = "builtin"
    setup_without_probe = True
    default_tts_model = ""
    default_stt_model = ""
    default_voice = ""
    default_format = "mp3"
    exposes_voices = False
    allow_keyless = False

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(base_url=base_url, timeout=timeout)
        self._transport = transport

    def describe(self) -> list[VerbSpec]:
        output = {"type": "object"}
        verbs = [
            VerbSpec(
                "voice.speak",
                "voice",
                _speak_schema(),
                output,
                "high",
                f"Synthesise bounded speech with {self.id}; may spend provider credit.",
                rate_limit={"per": "minute", "max": 30, "scope": "tenant"},
            ),
            VerbSpec(
                "voice.listen",
                "voice",
                _listen_schema(),
                output,
                "low",
                f"Transcribe one bounded audio clip with {self.id}.",
                rate_limit={"per": "minute", "max": 60, "scope": "tenant"},
            ),
        ]
        if self.exposes_voices:
            verbs.append(
                VerbSpec(
                    "voice.voices.list",
                    "voice",
                    _empty_schema(),
                    output,
                    "low",
                    f"List the bounded {self.id} voice catalogue.",
                    rate_limit={"per": "minute", "max": 30, "scope": "tenant"},
                )
            )
        return verbs

    def _handlers(self) -> dict[str, Handler]:
        handlers: dict[str, Handler] = {
            "voice.speak": self._speak,
            "voice.listen": self._listen,
        }
        if self.exposes_voices:
            handlers["voice.voices.list"] = self._voices_list
        return handlers

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        if not self.allow_keyless and bearer_token(credential) is None:
            return Result.failure(
                AdapterError(ErrorClass.UNAUTHORISED, f"{self.id} credential missing")
            )
        if not self.base_url_for(credential):
            return Result.failure(AdapterError(ErrorClass.INVALID, f"{self.id} base URL missing"))
        return await super().execute(verb, params, credential, context)

    def _client(self, credential: Credential | None) -> httpx.AsyncClient:
        if self._transport is None:
            return super()._client(credential)
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        auth: httpx.Auth | None = None
        if credential is not None:
            extra, auth = self._auth(credential)
            headers.update(extra)
        return httpx.AsyncClient(
            base_url=self.base_url_for(credential),
            headers=headers,
            timeout=self.timeout,
            auth=auth,
            follow_redirects=False,
            transport=self._transport,
        )

    async def health(self) -> str:
        # Setup can be shown before an authenticated call, but must never be
        # projected as healthy merely because the adapter was constructed.
        return "degraded"

    async def _raw_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        max_bytes: int = MAX_BINARY_RESPONSE_BYTES,
        **kwargs: Any,
    ) -> httpx.Response | AdapterError:
        try:
            assert_egress_allowed(str(client.base_url.join(url)))
        except EgressBlocked as exc:
            return AdapterError(ErrorClass.INVALID, str(exc), retryable=False)
        await self._limiter.acquire()
        try:
            response, _ = await bounded_http_response(
                client,
                method,
                url,
                max_bytes=max_bytes,
                **kwargs,
            )
        except ResponseBoundaryError:
            return bounded_response_error()
        if 200 <= response.status_code < 300:
            return response
        return self._map_status(response)

    async def _speak(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        raise NotImplementedError

    async def _listen(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        raise NotImplementedError

    async def _voices_list(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        return Result.failure(AdapterError(ErrorClass.INVALID, "voice catalogue unavailable"))

    @staticmethod
    def _text(params: dict[str, Any]) -> str | AdapterError:
        text = str(params.get("text") or "")
        if not text or len(text) > MAX_TEXT_CHARS:
            return AdapterError(ErrorClass.INVALID, "text exceeds the tts bound")
        return text

    @staticmethod
    def _audio(params: dict[str, Any]) -> tuple[bytes, str] | AdapterError:
        encoded = str(params.get("audio_b64") or "")
        if not encoded or len(encoded) > MAX_AUDIO_B64_CHARS:
            return AdapterError(ErrorClass.INVALID, "audio_b64 exceeds the stt bound")
        try:
            audio = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return AdapterError(ErrorClass.INVALID, "audio_b64 is not valid base64")
        return audio, str(params.get("filename") or "audio.wav")

    @staticmethod
    def _audio_result(response: httpx.Response, *, voice: str, model: str, chars: int) -> Result:
        return Result.success(
            {
                "audio_b64": base64.b64encode(response.content).decode("ascii"),
                "content_type": response.headers.get("Content-Type", "application/octet-stream"),
                "voice": voice,
                "model": model,
                "chars": chars,
            }
        )


def audio_content_type(filename: str) -> str:
    lowered = filename.lower()
    for suffix, content_type in _AUDIO_CONTENT_TYPES.items():
        if lowered.endswith(suffix):
            return content_type
    return "application/octet-stream"
