"""Fish Audio voice (TTS / STT) as governed Boltrig verbs.

Sibling of :mod:`boltrig.adapters.builtin.xai_voice`. It deliberately exposes
the SAME verb surface (``voice.speak`` / ``voice.listen`` /
``voice.voices.list``) so switching provider is a manifest BINDING change, not
a code change: bind ``voice.speak`` to ``fish-audio`` or to ``xai-voice`` and
nothing downstream of the kernel has to know which one answered.

Docs basis + what was actually measured against the live API on 2026-08-05
(recorded because two of these disagree with the marketing copy):

  - TTS is ``POST /v1/tts``. JSON body ``{text, reference_id, format}`` with the
    model selected by a ``model:`` HEADER, not a body field. Returns raw audio
    bytes. Verified: 200, ~0.79s, 20KB of real MPEG layer III for ~20 chars.
  - The voice catalogue is ``GET /model`` and is NOT under ``/v1`` - ``/v1/model``
    is a 404. That is why base_url here is the bare host and every path carries
    its own prefix, unlike the xai adapter whose base already ends in ``/v1``.
  - STT is ``POST /v1/asr`` and is NOT free. With the ``s2.1-pro-free`` tier the
    endpoint answers 402 "Insufficient API credit" (the account's API credit was
    0.0000 when this was written). The verb is still implemented, because the
    account can be topped up and the 402 maps cleanly onto ErrorClass through the
    base's status mapping - but do not bind ``voice.listen`` here expecting the
    free tier to serve it. Local whisper or xai are the working STT paths.

The credential (FISH_API_KEY) stays kernel-side and is presented only as an
Authorization bearer for the duration of one call (SEC-04/05).

Registration (P1/P7, the extension contract): this adapter is DATA, not core
code - the manifest names it with an explicit ``module_ref`` so no
``_BUILTIN_MODULES`` core edit is needed:

  - id: fish-audio
    runtime: http
    module_ref: boltrig.adapters.builtin.fish_audio:build
    credential: { id: FISH_API_KEY, store: env, kind: api_key }

Like the xai adapter, the realtime speech-to-speech surface is NOT here: a
held-open WebSocket belongs to the channel gateway (decision 0003).
"""

from __future__ import annotations

import base64
import binascii
import os
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
from boltrig.models import InvocationContext

# Bare host: the TTS/STT surface lives under /v1 but the model catalogue does
# not, so no single prefix covers both (see module docstring).
_BASE_URL = "https://api.fish.audio"

# The free tier's model id. Sent as a header on every synthesis call; a paid
# plan selects a different string here and nothing else changes.
_DEFAULT_MODEL = "s2.1-pro-free"

# Bounds (DoS/cost bounding, fail-closed). Fish does not publish the same 15k
# input cap xAI does, so the same bound is applied here rather than leaving the
# verb unbounded - an agent must not be able to stream unbounded text or audio
# through a governed verb.
_MAX_TEXT_CHARS = 15000
_MAX_AUDIO_B64_CHARS = 32_000_000
_MAX_FILENAME_CHARS = 255
_MAX_REFERENCE_ID_CHARS = 64

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
            # Kept as "voice" rather than Fish's own "reference_id" so the schema
            # matches xai-voice's exactly; a caller switching provider does not
            # rewrite its params. Mapped onto reference_id on the way out.
            "voice": {"type": "string", "maxLength": _MAX_REFERENCE_ID_CHARS},
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


class FishAudioAdapter(HttpAdapter):
    id = "fish-audio"
    version = "0.1.0"
    source = "builtin"
    user_agent = "boltrig-fish-audio/1.0"

    def __init__(
        self,
        *,
        base_url: str = _BASE_URL,
        timeout: float = 60.0,
        default_voice: str | None = None,
        default_format: str = "mp3",
        model: str = _DEFAULT_MODEL,
        enable_asr: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(base_url=base_url, timeout=timeout)
        self._default_voice = default_voice
        self._default_format = default_format
        self._model = model
        # See describe(): claiming voice.listen without ASR credit would take the
        # verb off a provider that works and give it to one that 402s.
        self._enable_asr = enable_asr
        self._transport = transport

    def describe(self) -> list[VerbSpec]:
        """The verbs this adapter CLAIMS at boot.

        ``voice.listen`` is withheld unless FISH_ENABLE_ASR is set, and that is
        load-bearing rather than tidiness. Boot registration binds each verb to
        the LAST adapter that describes it, and it overwrites whatever the
        control plane last set - so a `control.binding.set` rebind does not
        survive a kernel restart. With this adapter listed after xai-voice in
        the manifest, claiming all three verbs would silently take voice.listen
        away from xai on every boot and hand it to a provider that answers 402
        (Fish ASR needs paid API credit the free TTS tier does not include).

        Withholding it is therefore what makes the intended split STABLE across
        restarts: speak + voices.list resolve here, listen stays with xai. Set
        FISH_ENABLE_ASR=1 once the account has ASR credit.
        """
        any_out = {"type": "object"}
        verbs = [
            VerbSpec("voice.speak", "voice", _speak_schema(), any_out, "high",
                     "Synthesise text to speech via Fish Audio TTS. Returns "
                     "base64 audio. Rated high like the xai sibling: the free "
                     "tier is time-bounded and a paid plan spends money."),
            VerbSpec("voice.voices.list", "voice", _empty_schema(), any_out, "low",
                     "List the Fish Audio voice model catalogue."),
        ]
        if self._enable_asr:
            verbs.append(
                VerbSpec("voice.listen", "voice", _listen_schema(), any_out, "low",
                         "Transcribe an audio clip via Fish Audio ASR. Requires "
                         "paid API credit - the free TTS tier does NOT cover it.")
            )
        return verbs

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
        # Fail closed before the request is built: when `bearer_token` yields None
        # there is nothing to authenticate with, and letting it through would post an
        # empty Authorization header to Fish rather than refuse.
        if bearer_token(credential) is None:
            return Result.failure(
                AdapterError(ErrorClass.UNAUTHORISED, "fish-audio credential missing")
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
            auth=auth,
            timeout=self.timeout,
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
            # Fish names the voice model "reference_id"; the verb keeps xai's
            # "voice" so the two adapters stay drop-in for one another.
            payload["reference_id"] = voice
        resp_or_error = await self._raw_request(
            client, "POST", "/v1/tts",
            json=payload,
            # The model is selected by header on this API, not in the body.
            headers={"Accept": "application/octet-stream", "model": self._model},
        )
        if isinstance(resp_or_error, AdapterError):
            return Result.failure(resp_or_error)
        resp = resp_or_error
        return Result.success({
            "audio_b64": base64.b64encode(resp.content).decode("ascii"),
            "content_type": resp.headers.get("Content-Type", "application/octet-stream"),
            "voice": voice,
            "model": self._model,
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
        # Fish's ASR takes the upload under "audio" (xAI's STT uses "file").
        resp_or_error = await self._raw_request(
            client, "POST", "/v1/asr",
            files={"audio": (filename, audio, _audio_content_type(filename))},
            data=data or None,
        )
        if isinstance(resp_or_error, AdapterError):
            return Result.failure(resp_or_error)
        body = self._parse(resp_or_error)
        output: dict[str, Any] = {"text": str(body.get("text") or "")}
        segments = body.get("segments")
        if isinstance(segments, list):
            output["segments"] = segments
        duration = body.get("duration", body.get("duration_seconds"))
        if isinstance(duration, (int, float)):
            output["duration_seconds"] = duration
        return Result.success(output)

    async def _voices_list(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        # NOT /v1/model - that path 404s on this API (see module docstring).
        data = await self.request(client, "GET", "/model")
        raw = data.get("items", data.get("data"))
        voices = [v for v in raw if isinstance(v, dict)] if isinstance(raw, list) else []
        return Result.success({"voices": voices})

    # --- binary/multipart carrier ---------------------------------------------
    async def _raw_request(
        self, client: httpx.AsyncClient, method: str, url: str, **kwargs: Any
    ) -> httpx.Response | AdapterError:
        """One POST whose body/response the base's JSON ``request()`` cannot
        carry (raw audio bytes back from TTS, multipart upload to ASR). Same
        guards as the xai sibling: egress pre-flight (INJ-02/SEC-61),
        cooperative rate limit and the one status -> ErrorClass mapping. POSTs
        are never auto-retried (a dropped connection must not double-spend a
        synthesis)."""
        try:
            assert_egress_allowed(str(client.base_url.join(url)))
        except EgressBlocked as exc:
            return AdapterError(ErrorClass.INVALID, str(exc), retryable=False)
        await self._limiter.acquire()
        resp = await client.request(method, url, **kwargs)
        if 200 <= resp.status_code < 300:
            return resp
        return self._map_status(resp)


def _audio_content_type(filename: str) -> str:
    lowered = filename.lower()
    for suffix, content_type in _AUDIO_CONTENT_TYPES.items():
        if lowered.endswith(suffix):
            return content_type
    return "application/octet-stream"


def build() -> FishAudioAdapter:
    # FISH_VOICE_ID is the deployment's default voice (Fish's reference_id); a
    # caller still overrides it per call with the verb's `voice` param. Read
    # from the environment rather than hardcoded so switching the house voice
    # does not need a code change. FISH_TTS_MODEL likewise, so moving off the
    # time-bounded free tier is a config edit.
    return FishAudioAdapter(
        default_voice=os.environ.get("FISH_VOICE_ID") or None,
        model=os.environ.get("FISH_TTS_MODEL") or _DEFAULT_MODEL,
        # Off by default: Fish ASR needs paid credit, and claiming the verb
        # without it would take voice.listen away from a working provider on
        # every boot (see describe()).
        enable_asr=(os.environ.get("FISH_ENABLE_ASR") or "").strip() in {"1", "true", "yes"},
    )
