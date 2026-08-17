"""Prosody from a spoken utterance: the half of tone that words cannot carry.

WHY THIS EXISTS SEPARATELY FROM SENTIMENT. A sentiment pass over the transcript
can tell you what was said and is deaf to how. "Fine." typed and "Fine."
snapped are the same string, and the difference is entirely in the pitch, the
energy and the pace. Those three are cheap to measure and need no model at all,
which is the whole reason to do this rather than reach for a speech-emotion
network: the signal is in the waveform whisper has already been handed.

PURE STDLIB, DELIBERATELY. numpy would make every function here three lines
shorter and it is NOT available at runtime: pyproject puts numpy in the dev
extra with an explicit note that the kernel and fleet images install
requirements-lock.txt and "do not grow an image library for a tool that never
runs in them". An import of it here would pass every test on a workstation and
fail on first use inside the container. ``audioop`` is not an option either --
it was removed in Python 3.13, which is what this runs on.

WHAT IS AND IS NOT MEASURED HERE. Pitch is a real autocorrelation estimate.
Spectral tilt is approximated by the zero-crossing rate, which correlates with
where the energy sits without needing an FFT; it is named as a proxy everywhere
it appears because it is one. Nothing here decides what a speaker FEELS -- that
is :mod:`boltrig.emotion.tone`, which needs a per-speaker baseline before it
will say anything at all.
"""

from __future__ import annotations

import array
import io
import math
import statistics
import wave
from dataclasses import dataclass

# 25 ms frames at 10 ms hops: the standard analysis window for speech, short
# enough that pitch is stationary inside one and long enough to hold two periods
# of the lowest voice this looks for.
_FRAME_MS = 25.0
_HOP_MS = 10.0

# 70 Hz to 400 Hz. Wide enough for a low male speaking voice at the bottom and a
# raised female voice at the top; anything outside it in a speech recording is
# noise rather than pitch.
_F0_MIN_HZ = 70.0
_F0_MAX_HZ = 400.0

# THE PITCH PATH IS DECIMATED AND STRIDED, and without both this is unusable.
#
# Plain autocorrelation is frames x lags x window multiplies. At 16 kHz that is
# about 100 frames, 190 candidate lags and a 400-sample window for one second of
# speech -- 7.6 MILLION float multiplies in pure Python, measured at seconds per
# utterance against an STT budget of 0.13s. The feature would have doubled the
# latency of every spoken turn.
#
# Decimating to 4 kHz divides the window and the lag range by four each, and
# taking every third frame divides the count again: the same second becomes about
# 160 thousand multiplies. 4 kHz still leaves eight samples per period at the top
# of the range, which is ample for a period estimate, and pitch does not live in
# the discarded high band anyway.
#
# Energy and the tilt proxy stay at full rate. Both are single passes over the
# samples, so they cost nothing worth optimising -- and the zero-crossing rate is
# defined against the sample rate, so decimating would silently change its scale.
_PITCH_HZ = 4000
_PITCH_FRAME_STRIDE = 3

# A frame is called voiced only if its best autocorrelation peak is this strong
# relative to lag zero. Below it the "period" found is noise structure, and
# letting those frames into the pitch statistics is what makes an estimator
# report a confident average for a recording of a fan.
_VOICED_FLOOR = 0.30

# Silence gate. Frames quieter than this contribute to neither pitch nor tilt,
# so leading and trailing room tone cannot drag the numbers.
_SILENCE_RMS = 0.012


@dataclass(frozen=True)
class Prosody:
    """What the waveform says, before anything decides what it means."""

    #: Mean pitch over voiced frames, in Hz. 0.0 when nothing was voiced.
    f0_mean: float
    #: Pitch variation as a coefficient of variation, so it is comparable
    #: between a low voice and a high one. Flat delivery sits near zero.
    f0_spread: float
    #: RMS amplitude over non-silent frames, 0..1.
    energy: float
    #: Variation in that amplitude. Steady loudness and a shout differ here.
    energy_spread: float
    #: Fraction of frames that carried pitch. Low means whispered, muttered or
    #: mostly silence.
    voiced: float
    #: PROXY for spectral tilt: zero-crossing rate, normalised 0..1. Higher
    #: means more energy up top, which is what a hard or strained voice does.
    tilt: float
    #: Words per second, or -1.0 when the caller could not say.
    rate: float
    #: Duration analysed, in seconds.
    seconds: float


def decode_wav(data: bytes) -> tuple[array.array[int], int] | None:
    """Mono 16-bit samples and a sample rate, or None if this is not usable WAV.

    None rather than an exception, and no format conversion. Anything that is
    not PCM WAV -- mp3, opus, a webm container off a browser -- returns None and
    the caller simply gets no prosody for that utterance. Shelling out to ffmpeg
    to widen this would put an external binary on the path of every spoken turn,
    which is a much larger commitment than the feature is worth; the recorder we
    control already sends WAV.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            if handle.getsampwidth() != 2:
                return None
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
            channels = handle.getnchannels()
    except (wave.Error, EOFError, ValueError):
        return None
    if rate <= 0 or not frames:
        return None

    samples = array.array("h")
    samples.frombytes(frames[: len(frames) - (len(frames) % 2)])
    if channels > 1:
        samples = _to_mono(samples, channels)
    return samples, rate


def _to_mono(samples: array.array[int], channels: int) -> array.array[int]:
    """Average the channels. A stereo mic pair would otherwise beat against
    itself in the autocorrelation and report a pitch neither channel has."""
    mono = array.array("h")
    for i in range(0, len(samples) - channels + 1, channels):
        mono.append(int(sum(samples[i : i + channels]) / channels))
    return mono


def analyse_prosody(data: bytes, *, words: int = -1) -> Prosody | None:
    """Measure one utterance. None when the audio is not usable WAV or is silent.

    ``words`` comes from the transcript, so speech rate costs nothing extra --
    whisper has already counted them for us. Passing -1 leaves rate unset rather
    than guessing, because a wrong rate is worse than a missing one: it is the
    strongest single term separating excitement from anger.
    """
    decoded = decode_wav(data)
    if decoded is None:
        return None
    samples, rate = decoded
    seconds = len(samples) / rate
    if seconds < 0.15:
        # Shorter than a syllable. Every statistic below would be one frame.
        return None

    frame_len = max(64, int(rate * _FRAME_MS / 1000.0))
    hop = max(16, int(rate * _HOP_MS / 1000.0))
    quiet, quiet_rate = _decimate(samples, rate, _PITCH_HZ)
    pitch_frame = max(48, int(quiet_rate * _FRAME_MS / 1000.0))
    pitches: list[float] = []
    energies: list[float] = []
    crossings: list[float] = []

    for index, start in enumerate(range(0, max(1, len(samples) - frame_len), hop)):
        frame = samples[start : start + frame_len]
        rms = _rms(frame)
        if rms < _SILENCE_RMS:
            continue
        energies.append(rms)
        crossings.append(_zero_crossing_rate(frame))
        if index % _PITCH_FRAME_STRIDE:
            continue
        at = int(start * quiet_rate / rate)
        low = quiet[at : at + pitch_frame]
        if len(low) < pitch_frame:
            continue
        pitch = _pitch(low, quiet_rate)
        if pitch > 0.0:
            pitches.append(pitch)

    if not energies:
        return None

    frames_kept = len(energies)
    # Voiced fraction is now voiced-pitch-frames over the frames pitch was
    # actually TRIED on, not over every energy frame -- striding means those are
    # different denominators, and using the wrong one would report a third of the
    # true voicing and make every utterance look muttered.
    pitch_attempts = max(1, (frames_kept + _PITCH_FRAME_STRIDE - 1) // _PITCH_FRAME_STRIDE)
    f0_mean = statistics.fmean(pitches) if pitches else 0.0
    return Prosody(
        f0_mean=f0_mean,
        f0_spread=(
            statistics.pstdev(pitches) / f0_mean
            if len(pitches) > 1 and f0_mean > 0.0
            else 0.0
        ),
        energy=statistics.fmean(energies),
        energy_spread=(
            statistics.pstdev(energies) / statistics.fmean(energies)
            if frames_kept > 1
            else 0.0
        ),
        voiced=min(1.0, len(pitches) / pitch_attempts),
        tilt=statistics.fmean(crossings),
        rate=(words / seconds if words >= 0 and seconds > 0 else -1.0),
        seconds=seconds,
    )


def _decimate(samples: array.array[int], rate: int, target: int) -> tuple[array.array[int], int]:
    """Drop the sample rate toward ``target`` by integer averaging.

    Averaging each group rather than picking every Nth sample: plain subsampling
    aliases the high band down on top of the pitch, which produces confident
    estimates of frequencies that are not in the recording. A box average is a
    crude low-pass, but it is the right side of crude here.
    """
    if rate <= target:
        return samples, rate
    factor = max(2, rate // target)
    out = array.array("h")
    for i in range(0, len(samples) - factor + 1, factor):
        out.append(int(sum(samples[i : i + factor]) / factor))
    return out, rate // factor


def _rms(frame: array.array[int]) -> float:
    """Amplitude, normalised to 0..1 against full-scale 16-bit."""
    if not frame:
        return 0.0
    total = 0.0
    for value in frame:
        total += float(value) * float(value)
    return math.sqrt(total / len(frame)) / 32768.0


def _zero_crossing_rate(frame: array.array[int]) -> float:
    """Sign changes per sample, 0..1 -- the tilt PROXY.

    A cheap stand-in for where the spectral energy sits: a breathy or strained
    voice crosses zero far more often than a relaxed one. It is not a spectrum
    and must not be described as one, but it needs no FFT and it moves in the
    right direction, which is what the tone rules actually consume.
    """
    if len(frame) < 2:
        return 0.0
    crossings = 0
    previous = frame[0]
    for value in frame[1:]:
        if (previous < 0) != (value < 0):
            crossings += 1
        previous = value
    return crossings / (len(frame) - 1)


def _pitch(frame: array.array[int], rate: int) -> float:
    """Autocorrelation pitch for one frame, or 0.0 if the frame is unvoiced.

    Plain time-domain autocorrelation over the lag range that 70..400 Hz
    implies. Normalised against lag zero so the voicing decision is a ratio
    rather than an absolute, which is what lets one threshold work across a
    quiet recording and a loud one.
    """
    min_lag = max(2, int(rate / _F0_MAX_HZ))
    max_lag = min(len(frame) - 1, int(rate / _F0_MIN_HZ))
    if max_lag <= min_lag:
        return 0.0

    zero = 0.0
    for value in frame:
        zero += float(value) * float(value)
    if zero <= 0.0:
        return 0.0

    best_lag = 0
    best = 0.0
    for lag in range(min_lag, max_lag + 1):
        total = 0.0
        for i in range(len(frame) - lag):
            total += float(frame[i]) * float(frame[i + lag])
        score = total / zero
        if score > best:
            best = score
            best_lag = lag

    if best < _VOICED_FLOOR or best_lag == 0:
        return 0.0
    return rate / best_lag
