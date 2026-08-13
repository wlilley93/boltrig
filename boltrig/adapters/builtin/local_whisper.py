"""Local whisper.cpp STT as a governed Boltrig verb.

Third voice provider alongside :mod:`xai_voice` and :mod:`fish_audio`, and the
only one that costs nothing and sends no audio off the box. It claims
``voice.listen`` ONLY - it does no synthesis - which is what lets it take STT
while fish-audio keeps TTS (see the ordering note in manifest.yaml).

Why this one is not in a container. whisper.cpp is fast here because of Metal,
and Metal does not exist inside the OrbStack Linux VM that runs the rest of the
stack. So whisper-server runs as a NATIVE macOS process and the kernel reaches
out to the Mac host. Measured on the M4 Pro with ggml-small.en, 2026-08-05:

    ~0.13s per short utterance, repeatably (0.129 / 0.128 / 0.130)

against ~0.8s for a remote TTS round trip - comfortably inside turn-taking
budget, and with no per-call cost or egress of the user's voice.

Two things about this were established by measurement rather than assumption,
because both contradict the obvious guess:

  - The endpoint is ``POST /inference`` (multipart ``file``), NOT the
    OpenAI-compatible ``/v1/audio/transcriptions``. This build of whisper-server
    404s the latter.
  - The container reaches the Mac at ``host.orb.internal``. The VM's default
    gateway (192.168.139.1), the docker bridge gateway (172.17.0.1) and the VM's
    own address (192.168.139.14) were ALL refused; only the orb hostname works.

``host.orb.internal`` resolves to a ULA IPv6 address, which the shared egress
guard refuses as internal - correctly, since that guard is the SSRF defence.
This adapter therefore passes the guard's ONE documented opt-in,
``allow_internal``, which the module docstring reserves for "operator-vetted
INTERNAL services". That is what this is: a fixed, operator-configured loopback
endpoint, never an agent-influenced URL. The rest of the guard (scheme,
air-gap, block/allow lists) still applies.
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
)
from boltrig.adapters.egress import EgressBlocked, assert_egress_allowed
from boltrig.adapters.http_base import Handler, HttpAdapter
from boltrig.adapters.http_response import (
    MAX_JSON_RESPONSE_BYTES,
    ResponseBoundaryError,
    bounded_http_response,
    bounded_response_error,
)
from boltrig.models import InvocationContext

# The Mac host from inside the VM / its containers. Overridable so the same
# adapter works if whisper is moved (e.g. onto the beelink for a built deploy).
_BASE_URL = os.environ.get("BOLTRIG_WHISPER_URL") or "http://host.orb.internal:8910"

# Same bounds as the remote STT adapters so switching provider cannot change how
# much an agent may push through the verb.
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


class LocalWhisperAdapter(HttpAdapter):
    id = "local-whisper"
    version = "0.1.0"
    source = "builtin"
    user_agent = "boltrig-local-whisper/1.0"

    def __init__(
        self,
        *,
        base_url: str = _BASE_URL,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(base_url=base_url, timeout=timeout)
        self._transport = transport

    def describe(self) -> list[VerbSpec]:
        any_out = {"type": "object"}
        return [
            VerbSpec("voice.listen", "voice", _listen_schema(), any_out, "low",
                     "Transcribe an audio clip with a local whisper.cpp server. "
                     "On-device: no key, no cost, and the audio never leaves the "
                     "host."),
        ]

    def _handlers(self) -> dict[str, Handler]:
        return {"voice.listen": self._listen}

    async def execute(
        self, verb: str, params: dict[str, Any], credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        # Deliberately NO credential precondition, unlike the xai/fish siblings: a local
        # whisper server has no bearer at all, so `_auth` returns an empty header map.
        # Requiring `bearer_token` here would fail closed on the one provider that is
        # meant to be the always-available fallback.
        return await super().execute(verb, params, credential, context)

    def _auth(self, credential: Credential) -> tuple[dict[str, str], httpx.Auth | None]:
        return {}, None

    def _client(self, credential: Credential | None) -> httpx.AsyncClient:
        if self._transport is None:
            return super()._client(credential)
        return httpx.AsyncClient(
            base_url=self.base_url_for(credential),
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            timeout=self.timeout,
            transport=self._transport,
        )

    async def health(self) -> str:
        return "unknown"

    # --- handlers ------------------------------------------------------------
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
        data: dict[str, str] = {"response_format": "json"}
        if params.get("language"):
            data["language"] = str(params["language"])
        resp_or_error = await self._raw_request(
            client, "POST", "/inference",
            files={"file": (filename, audio, _audio_content_type(filename))},
            data=data,
        )
        if isinstance(resp_or_error, AdapterError):
            return Result.failure(resp_or_error)
        body = self._parse(resp_or_error)
        # whisper-server returns a leading space and a trailing newline on the
        # transcript; strip so callers get the same shape the remote providers
        # give and a switch of provider is not visible downstream.
        return Result.success({"text": str(body.get("text") or "").strip()})

    # --- multipart carrier ----------------------------------------------------
    async def _raw_request(
        self, client: httpx.AsyncClient, method: str, url: str, **kwargs: Any
    ) -> httpx.Response | AdapterError:
        """Multipart upload the base's JSON ``request()`` cannot carry.

        ``allow_internal`` is the guard's one documented opt-in and is required
        here: the target is a fixed operator-configured host on the local
        machine, which the SSRF guard otherwise refuses precisely because it is
        internal. It is never an agent-supplied URL.
        """
        try:
            assert_egress_allowed(
                str(client.base_url.join(url)), {"allow_internal": True}
            )
        except EgressBlocked as exc:
            return AdapterError(ErrorClass.INVALID, str(exc), retryable=False)
        await self._limiter.acquire()
        try:
            resp, _ = await bounded_http_response(
                client,
                method,
                url,
                max_bytes=MAX_JSON_RESPONSE_BYTES,
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


def build() -> LocalWhisperAdapter:
    return LocalWhisperAdapter()
