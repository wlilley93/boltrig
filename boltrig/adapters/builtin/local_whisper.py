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
from boltrig.emotion.prosody import analyse_prosody
from boltrig.emotion.tone import Baseline, classify
from boltrig.emotion.valence import warmth
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
        # See the voice tone section below for why these live on the instance.
        self._baselines: dict[str, Baseline] = {}

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

    # --- voice tone -----------------------------------------------------------
    #
    # WHY THE TONE IS MEASURED HERE. This adapter is the only place in the stack
    # that holds the decoded waveform: everything downstream has a transcript and
    # a transcript cannot carry tone. "Fine." typed and "Fine." snapped are the
    # same string.
    #
    # It reports rather than acts. The result gains a `tone` block and the kernel
    # decides whether to emit a voice_tone event from it -- an adapter reaching
    # into the emotion relay directly would give a governed verb a side effect
    # nobody reading the verb could see.

    #: Per-speaker baselines, keyed by the human on whose behalf the call runs.
    #: PER PROCESS, and that is a deliberate acceptance rather than an oversight:
    #: a restart loses them and the next six utterances re-learn. Persisting them
    #: would mean a store, a migration and a per-user record of how someone's
    #: voice usually sounds, which is a much heavier thing to own than a feature
    #: that recovers on its own inside one conversation.
    _MAX_SPEAKERS = 64

    def _speaker(self, context: InvocationContext) -> str:
        """The baseline key: the delegated human first, the tenant only as a
        fallback. Keying on tenant alone would average two people in one
        workspace into a single "normal", which is exactly the population
        baseline this design exists to avoid."""
        return str(context.on_behalf_of or context.tenant_id)

    def _tone(
        self, audio: bytes, text: str, context: InvocationContext
    ) -> dict[str, Any] | None:
        """Measure the delivery, or None when there is nothing defensible to say.

        Every failure path returns None and never raises: a transcript is the
        product here and tone is a garnish, so a malformed recording or an
        unexpected codec must not cost the user their words. That is also why the
        except clause is broad -- a new numeric edge in the analysis should
        degrade the garnish, not fail the verb.
        """
        try:
            prosody = analyse_prosody(audio, words=len(text.split()))
            if prosody is None:
                return None
            key = self._speaker(context)
            baseline = self._baselines.get(key, Baseline())
            tone = classify(prosody, baseline, text_valence=warmth(text))
            # Observed AFTER classifying, so an utterance is never measured
            # against a baseline it has already moved.
            self._baselines[key] = baseline.observe(prosody)
            if len(self._baselines) > self._MAX_SPEAKERS:
                self._baselines.pop(next(iter(self._baselines)))
            if tone is None:
                return None
            return {
                "tone": tone.kind.removeprefix("user_"),
                "intensity": round(tone.intensity, 3),
                "because": list(tone.because),
                "calibrated_on": baseline.heard,
            }
        except Exception:  # noqa: BLE001 - see the docstring
            return None

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
        text = str(body.get("text") or "").strip()
        payload: dict[str, Any] = {"text": text}
        tone = self._tone(audio, text, context)
        if tone is not None:
            payload["tone"] = tone
        return Result.success(payload)

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
