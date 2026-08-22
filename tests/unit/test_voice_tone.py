"""Voice tone: prosody, calibration, and the tones it will and will not claim.

The load-bearing tests here are the REFUSALS. A tone detector that answers
confidently on thin evidence is worse than none, because the emotion engine
integrates what it is told into a mood that then persists. So this asserts that
nothing is reported before a per-speaker baseline exists, that unusable audio
produces silence rather than a guess, and that sarcasm cannot fire without both
channels agreeing that they disagree.
"""

from __future__ import annotations

import io
import math
import struct
import wave

import pytest

from boltrig.adapters.voice_tone.prosody import Prosody, analyse_prosody, decode_wav
from boltrig.adapters.voice_tone.tone import MIN_UTTERANCES, Baseline, classify
from boltrig.adapters.voice_tone.valence import warmth


def tone_wav(
    *,
    seconds: float = 1.2,
    rate: int = 16000,
    f0: float = 140.0,
    amp: float = 0.22,
    wobble: float = 0.0,
    channels: int = 1,
    width: int = 2,
) -> bytes:
    """A harmonic tone, which is close enough to voiced speech for pitch work."""
    n = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            t = i / rate
            hz = f0 * (1.0 + wobble * math.sin(2.0 * math.pi * 0.8 * t))
            value = 0.0
            for harmonic, gain in ((1, 1.0), (2, 0.5), (3, 0.25), (4, 0.12)):
                value += gain * math.sin(2.0 * math.pi * hz * harmonic * t)
            sample = int(max(-1.0, min(1.0, value / 1.87 * amp)) * 32767)
            frames += struct.pack("<h", sample) * channels
        handle.writeframes(bytes(frames))
    return buf.getvalue()


def make(**kwargs: float) -> Prosody:
    """A Prosody with plausible defaults, so a test names only what it varies."""
    base = {
        "f0_mean": 140.0,
        "f0_spread": 0.10,
        "energy": 0.08,
        "energy_spread": 0.20,
        "voiced": 0.8,
        "tilt": 0.05,
        "rate": 3.0,
        "seconds": 1.5,
    }
    base.update(kwargs)
    return Prosody(**base)  # type: ignore[arg-type]


def calibrated(**kwargs: float) -> Baseline:
    """A baseline that has heard enough to be allowed to speak."""
    baseline = Baseline()
    for _ in range(MIN_UTTERANCES):
        baseline = baseline.observe(make(**kwargs))
    return baseline


# --- prosody ----------------------------------------------------------------


@pytest.mark.parametrize("f0", [110.0, 140.0, 220.0])
def test_pitch_is_recovered_within_a_few_percent(f0: float) -> None:
    result = analyse_prosody(tone_wav(f0=f0), words=5)
    assert result is not None
    # The decimated estimator quantises rate/lag, which biases slightly high and
    # by a constant fraction -- harmless for deviation-from-baseline work, which
    # is all this feeds.
    assert result.f0_mean == pytest.approx(f0, rel=0.05)


def test_spread_separates_flat_delivery_from_animated() -> None:
    flat = analyse_prosody(tone_wav(wobble=0.0), words=5)
    wide = analyse_prosody(tone_wav(wobble=0.20), words=5)
    assert flat is not None and wide is not None
    # This is the term that tells anger from excitement, so it has to move a long
    # way rather than merely in the right direction.
    assert wide.f0_spread > flat.f0_spread * 5


def test_energy_tracks_amplitude() -> None:
    quiet = analyse_prosody(tone_wav(amp=0.05), words=5)
    loud = analyse_prosody(tone_wav(amp=0.40), words=5)
    assert quiet is not None and loud is not None
    assert loud.energy > quiet.energy * 3


def test_rate_comes_from_the_transcript_and_is_optional() -> None:
    with_words = analyse_prosody(tone_wav(seconds=2.0), words=8)
    without = analyse_prosody(tone_wav(seconds=2.0))
    assert with_words is not None and without is not None
    assert with_words.rate == pytest.approx(4.0, rel=0.1)
    # -1 rather than 0: a rate of zero would read as "said nothing for two
    # seconds", which the tone rules would treat as subdued.
    assert without.rate == -1.0


def test_stereo_is_averaged_rather_than_refused() -> None:
    result = analyse_prosody(tone_wav(channels=2, f0=160.0), words=4)
    assert result is not None
    assert result.f0_mean == pytest.approx(160.0, rel=0.05)


@pytest.mark.parametrize(
    "data",
    [b"", b"not a wav", b"RIFF____WAVEfmt ", tone_wav(seconds=0.05)],
    ids=["empty", "garbage", "truncated-header", "shorter-than-a-syllable"],
)
def test_unusable_audio_is_silence_not_a_guess(data: bytes) -> None:
    assert analyse_prosody(data, words=1) is None


def test_eight_bit_wav_is_declined() -> None:
    # Only 16-bit is handled; a silent mis-read of 8-bit samples as 16-bit would
    # produce confident nonsense.
    assert decode_wav(tone_wav(width=1)) is None


def test_silence_produces_nothing() -> None:
    assert analyse_prosody(tone_wav(amp=0.0005), words=3) is None


# --- calibration ------------------------------------------------------------


def test_nothing_is_claimed_before_the_baseline_is_ready() -> None:
    baseline = Baseline()
    shouted = make(energy=0.9, f0_mean=260.0, f0_spread=0.5, rate=6.0)
    for _ in range(MIN_UTTERANCES - 1):
        assert classify(shouted, baseline) is None
        baseline = baseline.observe(make())
    assert not baseline.ready
    # And the moment it IS ready, the same utterance is classifiable.
    baseline = baseline.observe(make())
    assert baseline.ready
    assert classify(shouted, baseline) is not None


def test_the_first_utterance_seeds_rather_than_easing_from_zero() -> None:
    # Easing from zero would leave the baseline reading as a very quiet speaker
    # for several turns, and every one of those turns would classify as raised.
    seeded = Baseline().observe(make(f0_mean=180.0, energy=0.3))
    assert seeded.f0 == pytest.approx(180.0)
    assert seeded.energy == pytest.approx(0.3)


def test_the_baseline_follows_the_speaker_slowly() -> None:
    baseline = calibrated(f0_mean=120.0)
    moved = baseline.observe(make(f0_mean=240.0))
    # A baseline that chased each utterance would learn the mood along with the
    # voice and have nothing left to measure the mood against.
    assert moved.f0 < 160.0


def test_a_loud_speaker_and_a_quiet_one_are_judged_separately() -> None:
    loud_habit = calibrated(energy=0.30, f0_mean=200.0)
    quiet_habit = calibrated(energy=0.03, f0_mean=110.0)
    utterance = make(energy=0.30, f0_mean=200.0, f0_spread=0.35, rate=4.5)
    # The same absolute loudness is ordinary for one speaker and a shout for the
    # other. This is the whole reason the baseline exists.
    assert classify(utterance, loud_habit) is None
    assert classify(utterance, quiet_habit) is not None


# --- the tones --------------------------------------------------------------


def test_excited_is_loud_high_and_WIDE() -> None:
    base = calibrated()
    tone = classify(make(energy=0.16, f0_mean=190.0, f0_spread=0.30, rate=4.5), base)
    assert tone is not None
    assert tone.kind == "user_excited"


def test_cross_is_loud_high_and_NARROW() -> None:
    base = calibrated()
    tone = classify(make(energy=0.16, f0_mean=190.0, f0_spread=0.04, tilt=0.09), base)
    assert tone is not None
    # Loudness alone cannot separate these two; pitch RANGE is what does it, and
    # without that term every raised voice was reported as anger.
    assert tone.kind == "user_cross"


def test_subdued_is_quiet_flat_and_slow() -> None:
    base = calibrated()
    tone = classify(make(energy=0.04, f0_spread=0.04, rate=1.8), base)
    assert tone is not None
    assert tone.kind == "user_subdued"


def test_ordinary_speech_is_not_a_tone() -> None:
    assert classify(make(), calibrated()) is None


def test_sarcasm_needs_warm_words_AND_a_delivery_that_contradicts_them() -> None:
    base = calibrated()
    flat = make(f0_spread=0.03, energy=0.06, rate=2.0)
    # Warm words, flat delivery: the mismatch is the signal.
    tone = classify(flat, base, text_valence=0.9)
    assert tone is not None
    assert tone.kind == "user_sarcastic"
    # The same delivery with no text reading cannot be sarcasm -- there is
    # nothing for the prosody to disagree with.
    assert (classify(flat, base) or type("x", (), {"kind": ""})).kind != "user_sarcastic"
    # And warm words delivered warmly are not sarcasm either.
    warm = make(f0_spread=0.30, energy=0.16, f0_mean=190.0, rate=4.5)
    assert classify(warm, base, text_valence=0.9).kind == "user_excited"  # type: ignore[union-attr]


def test_intensity_is_bounded_and_explained() -> None:
    tone = classify(
        make(energy=0.9, f0_mean=400.0, f0_spread=0.9, rate=12.0), calibrated()
    )
    assert tone is not None
    assert 0.0 < tone.intensity <= 1.0
    # A tone nobody can account for afterwards is a tone nobody can tune.
    assert tone.because


# --- the lexical warmth gate ------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("thanks, that is brilliant", 1.0),
        ("this is broken and useless", -1.0),
        ("the deployment finished at four", None),
        ("", None),
    ],
)
def test_warmth_answers_only_when_there_is_something_to_answer(
    text: str, expected: float | None
) -> None:
    assert warmth(text) == expected


def test_warmth_is_normalised_by_hits_not_by_length() -> None:
    short = warmth("thanks")
    long = warmth("thanks, that is exactly what I needed, you have saved me an afternoon")
    assert short == long == 1.0
