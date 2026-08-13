"""xAI voice (TTS / STT) as governed Boltrig verbs.

Docs basis: xAI's REST voice surface (https://api.x.ai, console.x.ai) exposes
text-to-speech at ``POST /v1/tts`` (raw audio bytes back, input bounded at
15k chars), a voice catalogue at ``GET /v1/tts/voices`` and speech-to-text at
``POST /v1/stt`` (multipart upload; text + word timings + duration back). The
credential (XAI_API_KEY) stays kernel-side and is presented only as an
Authorization bearer for the duration of one call (SEC-04/05).

Built on :class:`HttpAdapter` (S7.3): HTTP status -> ErrorClass mapping,
cooperative rate limiting and egress pinning come from the base; this module
carries only the verb surface, the bearer convention, the binary/multipart
payload handling (the base's JSON ``request()`` cannot carry them) and the
param bounds.

Registration (P1/P7, the extension contract): this adapter is DATA, not core
code - the manifest names it with an explicit ``module_ref`` so no
``_BUILTIN_MODULES`` core edit is needed:

  - id: xai-voice
    runtime: http
    module_ref: boltrig.adapters.builtin.xai_voice:build
    credential: { id: XAI_API_KEY, store: env, kind: api_key }

The realtime speech-to-speech surface is deliberately NOT here: a held-open
WebSocket belongs to the channel gateway (decision 0003), see
``services/channel_gateway/xai_voice_adapter.py``.
"""

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

_BASE_URL = "https://api.x.ai/v1"

# Bounds (DoS/cost bounding, fail-closed): the xAI TTS endpoint caps input at
# 15k characters; STT uploads are capped here at ~24 MiB of audio (32M base64
# chars) so an agent cannot stream unbounded payloads through the verb.
_MAX_TEXT_CHARS = 15000
_MAX_AUDIO_B64_CHARS = 32_000_000
_MAX_FILENAME_CHARS = 255

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
            "text": {"type": "string", "minLength": 1, "maxLength": _MAX_TEXT_CHARS},
            "voice": {"type": "string", "maxLength": 64},
            "format": {"type": "string", "maxLength": 16},
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
                "maxLength": _MAX_AUDIO_B64_CHARS,
            },
            "filename": {"type": "string", "maxLength": _MAX_FILENAME_CHARS},
            "language": {"type": "string", "maxLength": 16},
        },
        "required": ["audio_b64"],
        "additionalProperties": False,
    }


def _empty_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "additionalProperties": False}


class XaiVoiceAdapter(HttpAdapter):
    id = "xai-voice"
    version = "0.1.0"
    source = "builtin"
    user_agent = "boltrig-xai-voice/1.0"

    def __init__(
        self,
        *,
        base_url: str = _BASE_URL,
        timeout: float = 60.0,
        default_voice: str | None = None,
        default_format: str = "mp3",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(base_url=base_url, timeout=timeout)
        self._default_voice = default_voice
        self._default_format = default_format
        self._transport = transport

    def describe(self) -> list[VerbSpec]:
        any_out = {"type": "object"}
        return [
            VerbSpec("voice.speak", "voice", _speak_schema(), any_out, "high",
                     "Synthesise text to speech via xAI TTS (spends money: high "
                     "consequence). Returns base64 audio."),
            VerbSpec("voice.listen", "voice", _listen_schema(), any_out, "low",
                     "Transcribe an audio clip via xAI STT."),
            VerbSpec("voice.voices.list", "voice", _empty_schema(), any_out, "low",
                     "List the xAI TTS voice catalogue."),
        ]

    def _handlers(self) -> dict[str, Handler]:
        return {
            "voice.speak": self._speak,
            "voice.listen": self._listen,
            "voice.voices.list": self._voices_list,
        }

    async def execute(
        self, verb: str, params: dict[str, Any], credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        # Fail closed: never post an empty bearer (SEC-04/05).
        if bearer_token(credential) is None:
            return Result.failure(
                AdapterError(ErrorClass.UNAUTHORISED, "xai-voice credential missing")
            )
        return await super().execute(verb, params, credential, context)

    def _auth(self, credential: Credential) -> tuple[dict[str, str], httpx.Auth | None]:
        token = bearer_token(credential)
        if token:
            return {"Authorization": f"Bearer {token}"}, None
        return {}, None

    def _client(self, credential: Credential | None) -> httpx.AsyncClient:
        if self._transport is None:
            return super()._client(credential)
        # Injected transport (tests): same headers/auth, no egress pinning.
        base = self.base_url_for(credential)
        headers: dict[str, str] = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        auth: httpx.Auth | None = None
        if credential is not None:
            extra, auth = self._auth(credential)
            headers.update(extra)
        return httpx.AsyncClient(
            base_url=base,
            headers=headers,
            timeout=self.timeout,
            auth=auth,
            follow_redirects=False,
            transport=self._transport,
        )

    async def health(self) -> str:
        return "unknown"

    # --- handlers ------------------------------------------------------------
    async def _speak(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        text = str(params["text"])
        if not text or len(text) > _MAX_TEXT_CHARS:
            return Result.failure(
                AdapterError(ErrorClass.INVALID, "text exceeds the tts bound",
                             retryable=False)
            )
        voice = str(params.get("voice") or self._default_voice or "")
        fmt = str(params.get("format") or self._default_format)
        payload: dict[str, Any] = {"text": text, "format": fmt}
        if voice:
            payload["voice"] = voice
        resp_or_error = await self._raw_request(
            client, "POST", "/tts",
            json=payload, headers={"Accept": "application/octet-stream"},
        )
        if isinstance(resp_or_error, AdapterError):
            return Result.failure(resp_or_error)
        resp = resp_or_error
        return Result.success({
            "audio_b64": base64.b64encode(resp.content).decode("ascii"),
            "content_type": resp.headers.get("Content-Type", "application/octet-stream"),
            "voice": voice,
            "chars": len(text),
        })

    async def _listen(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        audio_b64 = str(params["audio_b64"])
        if len(audio_b64) > _MAX_AUDIO_B64_CHARS:
            return Result.failure(
                AdapterError(ErrorClass.INVALID, "audio_b64 exceeds the stt bound",
                             retryable=False)
            )
        try:
            audio = base64.b64decode(audio_b64, validate=True)
        except (binascii.Error, ValueError):
            return Result.failure(
                AdapterError(ErrorClass.INVALID, "audio_b64 is not valid base64",
                             retryable=False)
            )
        filename = str(params.get("filename") or "audio.wav")
        data: dict[str, str] = {}
        if params.get("language"):
            data["language"] = str(params["language"])
        resp_or_error = await self._raw_request(
            client, "POST", "/stt",
            files={"file": (filename, audio, _audio_content_type(filename))},
            data=data or None,
        )
        if isinstance(resp_or_error, AdapterError):
            return Result.failure(resp_or_error)
        body = self._parse(resp_or_error)
        output: dict[str, Any] = {"text": str(body.get("text") or "")}
        words = body.get("words")
        if isinstance(words, list):
            output["words"] = words
        duration = body.get("duration", body.get("duration_seconds"))
        if isinstance(duration, (int, float)):
            output["duration_seconds"] = duration
        return Result.success(output)

    async def _voices_list(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        data = await self.request(client, "GET", "/tts/voices")
        raw = data.get("voices", data.get("items"))
        voices = [v for v in raw if isinstance(v, dict)] if isinstance(raw, list) else []
        return Result.success({"voices": voices})

    # --- binary/multipart carrier ---------------------------------------------
    async def _raw_request(
        self, client: httpx.AsyncClient, method: str, url: str, **kwargs: Any
    ) -> httpx.Response | AdapterError:
        """One POST whose body/response the base's JSON ``request()`` cannot
        carry (raw audio bytes back from TTS, multipart upload to STT). Same
        guards: egress pre-flight (INJ-02/SEC-61), cooperative rate limit and
        the one status -> ErrorClass mapping. POSTs are never auto-retried (a
        dropped connection must not double-spend a synthesis)."""
        try:
            assert_egress_allowed(str(client.base_url.join(url)))
        except EgressBlocked as exc:
            return AdapterError(ErrorClass.INVALID, str(exc), retryable=False)
        await self._limiter.acquire()
        try:
            resp, _ = await bounded_http_response(
                client,
                method,
                url,
                max_bytes=MAX_BINARY_RESPONSE_BYTES,
                **kwargs,
            )
        except ResponseBoundaryError:
            return bounded_response_error()
        if 200 <= resp.status_code < 300:
            return resp
        return self._map_status(resp)


def _audio_content_type(filename: str) -> str:
    lowered = filename.lower()
    for suffix, content_type in _AUDIO_CONTENT_TYPES.items():
        if lowered.endswith(suffix):
            return content_type
    return "application/octet-stream"


def build() -> XaiVoiceAdapter:
    return XaiVoiceAdapter()
