"""Self-hosted Pocket TTS as a governed Boltrig verb.

The TTS counterpart to :mod:`boltrig.adapters.builtin.local_whisper`, and the
route type the self-hosted voice runtime had no way to be expressed as. It
exposes the SAME verb surface as :mod:`xai_voice` and :mod:`fish_audio`
(``voice.speak`` / ``voice.voices.list``), so choosing self-hosted over a
vendor is a manifest BINDING change rather than a code change.

Why this one exists even though fish-audio works. Fish is used to GENERATE a
character's eight register references; it is not the runtime. At runtime the
voice is Pocket TTS: it costs nothing per call, sends no text or audio off the
box, and needs no credential at all — which is why ``execute`` does not refuse
on a missing one the way the vendor adapters must.

  - The endpoint is OpenAI-shaped: ``POST /v1/audio/speech`` with
    ``{input, voice, response_format}``. The service also serves its own
    ``/speak``; the OpenAI shape is used here so one adapter body would serve
    any OpenAI-compatible local TTS, not just this one.
  - ``voice`` is a NAME, not a reference id. It resolves against the service's
    local clones (``voices/<name>.safetensors``) and its stock catalogue. A
    register is a separate voice name — ``<voice>-<tag>`` — because Pocket
    TTS's contract carries no emotion, style, speed or pitch field, so a tone
    written into the text would simply be read aloud.
  - The catalogue is ``GET /voices``, which answers ``{local, catalog}``.

Registration (P1/P7, the extension contract): this adapter is DATA, not core
code — the manifest names it with an explicit ``module_ref``:

  - id: pocket-voice
    runtime: http
    module_ref: boltrig.adapters.builtin.pocket_voice:build

No credential block: there is nothing to authenticate to.
"""

from __future__ import annotations

import base64
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
from boltrig.adapters.http_base import Handler, HttpAdapter
from boltrig.models import InvocationContext

# Loopback by default: the service binds 127.0.0.1 and must stay that way. A
# kernel in a container reaches the host copy through whatever hop the
# deployment provides (an SSH tunnel on the beelink, host.orb.internal on the
# Mac VM — the same problem local_whisper documents), so the base URL is
# overridable rather than assumed.
_BASE_URL = os.environ.get("POCKET_VOICE_URL", "http://127.0.0.1:8911")

# Bounds, fail-closed, matching the vendor siblings. Self-hosted means a long
# input costs CPU rather than money, which is still a cost worth bounding.
_MAX_TEXT_CHARS = 15000
_MAX_VOICE_CHARS = 64


def _speak_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": _MAX_TEXT_CHARS},
            "voice": {"type": "string", "maxLength": _MAX_VOICE_CHARS},
            "format": {"type": "string", "maxLength": 16},
        },
        "required": ["text"],
        "additionalProperties": False,
    }


def _empty_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "additionalProperties": False}


class PocketVoiceAdapter(HttpAdapter):
    id = "pocket-voice"
    version = "0.1.0"
    source = "builtin"
    user_agent = "boltrig-pocket-voice/1.0"

    def __init__(
        self,
        *,
        base_url: str = _BASE_URL,
        timeout: float = 60.0,
        default_voice: str | None = None,
        default_format: str = "wav",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(base_url=base_url, timeout=timeout)
        # Left None on purpose. "Absent voice means a silent character, never a
        # substituted one" — a default here would quietly lend one character's
        # voice to another that named none.
        self._default_voice = default_voice
        self._default_format = default_format
        self._transport = transport

    def describe(self) -> list[VerbSpec]:
        """Speak and list only.

        ``voice.listen`` is deliberately absent: STT belongs to local-whisper,
        and boot registration binds a verb to the LAST adapter that describes
        it, so claiming it here would silently take listening away from an
        adapter that does it well.
        """
        any_out = {"type": "object"}
        return [
            VerbSpec("voice.speak", "voice", _speak_schema(), any_out, "low",
                     "Synthesise speech with the self-hosted Pocket TTS. Returns "
                     "base64 audio. Rated LOW, unlike its vendor siblings: no "
                     "credential, no per-call cost, and nothing leaves the box."),
            VerbSpec("voice.voices.list", "voice", _empty_schema(), any_out, "low",
                     "List the locally cloned voices and the stock catalogue."),
        ]

    def _handlers(self) -> dict[str, Handler]:
        return {
            "voice.speak": self._speak,
            "voice.voices.list": self._voices_list,
        }

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
        payload: dict[str, Any] = {"input": text, "response_format": fmt}
        if voice:
            payload["voice"] = voice
        resp_or_error = await self._raw_request(
            client, "POST", "/v1/audio/speech",
            json=payload,
            headers={"Accept": "application/octet-stream"},
        )
        if isinstance(resp_or_error, AdapterError):
            return Result.failure(resp_or_error)
        resp = resp_or_error
        return Result.success({
            "audio_b64": base64.b64encode(resp.content).decode("ascii"),
            "content_type": resp.headers.get("Content-Type", "audio/wav"),
            "voice": voice,
            "chars": len(text),
        })

    async def _voices_list(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        resp_or_error = await self._raw_request(client, "GET", "/voices")
        if isinstance(resp_or_error, AdapterError):
            return Result.failure(resp_or_error)
        try:
            body = resp_or_error.json()
        except ValueError:
            return Result.failure(
                AdapterError(ErrorClass.UPSTREAM, "voice catalogue was not JSON")
            )
        return Result.success(body if isinstance(body, dict) else {"voices": body})


def build() -> PocketVoiceAdapter:
    return PocketVoiceAdapter()
