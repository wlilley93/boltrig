"""Turning prosody into a tone the emotion engine can appraise.

THE CENTRAL RULE HERE IS THAT TONE IS RELATIVE. A pitch of 190 Hz is raised for
one speaker and resting for another; 0.08 RMS is a shout in a quiet room and a
mutter beside a fan. Every published caution about speech emotion recognition
says the same thing -- it generalises badly across speakers, accents and rooms --
and the failure mode is not a shrug, it is a system confidently telling somebody
they are angry when they are not. So this refuses to say anything until it has
heard enough of one speaker to know what their ordinary sounds like, and then it
speaks only in deviations from that.

That is why :class:`Baseline` exists and why :func:`classify` returns None while
it is still learning. A tone detector that answers on the first utterance is
answering about the population, not the person.

SARCASM IS THE MISMATCH, NOT A FEATURE. It cannot be heard in prosody alone and
it cannot be read in text alone, because sarcasm IS the two disagreeing: warm
words delivered flat, or praise stretched out slowly. It is the one tone here
that requires both channels, and it is the reason this takes a text valence
argument at all rather than living purely in the waveform.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from boltrig.emotion.prosody import Prosody

#: Utterances of one speaker needed before any tone is reported. Six is a
#: judgement: enough that one unusually loud sentence cannot define "normal",
#: few enough that a first conversation is not silent all the way through.
MIN_UTTERANCES = 6

#: How fast the baseline follows the speaker. Slow on purpose -- a baseline that
#: chased every utterance would learn the mood along with the voice and then have
#: nothing left to measure the mood AGAINST.
_ALPHA = 0.12

#: Deviations, in units of the baseline value, that count as "raised" or
#: "lowered". These are ratios rather than z-scores because a running variance
#: over six samples is itself too noisy to divide by.
_HIGH = 0.18
_LOW = 0.15


@dataclass(frozen=True)
class Baseline:
    """What ordinary sounds like, for one speaker.

    Frozen and returned by value from :meth:`observe`, so a caller cannot end up
    with two references to a baseline that one of them has quietly moved.
    """

    f0: float = 0.0
    energy: float = 0.0
    tilt: float = 0.0
    rate: float = 0.0
    spread: float = 0.0
    heard: int = 0

    @property
    def ready(self) -> bool:
        return self.heard >= MIN_UTTERANCES

    def observe(self, p: Prosody) -> Baseline:
        """Fold one utterance in and return the updated baseline.

        The first utterance seeds the values outright rather than easing from
        zero: easing from zero would leave the baseline reading as "very quiet
        speaker" for the first several turns, and every one of those turns would
        then be classified as raised.
        """
        rate = p.rate if p.rate >= 0.0 else self.rate
        if self.heard == 0:
            return replace(
                self,
                f0=p.f0_mean,
                energy=p.energy,
                tilt=p.tilt,
                rate=max(0.0, rate),
                spread=p.f0_spread,
                heard=1,
            )
        return replace(
            self,
            f0=_ease(self.f0, p.f0_mean),
            energy=_ease(self.energy, p.energy),
            tilt=_ease(self.tilt, p.tilt),
            rate=_ease(self.rate, rate),
            spread=_ease(self.spread, p.f0_spread),
            heard=self.heard + 1,
        )


def _ease(current: float, sample: float) -> float:
    if sample <= 0.0:
        return current
    return current + (sample - current) * _ALPHA


@dataclass(frozen=True)
class Tone:
    """An appraisal kind and how strongly to fire it."""

    kind: str
    intensity: float
    #: Which deviations produced it, for the log. A tone nobody can account for
    #: afterwards is a tone nobody can tune.
    because: tuple[str, ...]


def classify(
    p: Prosody, base: Baseline, *, text_valence: float | None = None
) -> Tone | None:
    """The speaker's tone, or None when there is nothing defensible to say.

    None is returned generously and on purpose: before the baseline is ready,
    when the utterance carried no pitch at all, and when no rule clears its
    threshold. Silence is the correct output for an uncertain tone detector --
    the emotion engine then simply gets no appraisal, and the body goes on
    showing the mood it already had.
    """
    if not base.ready or p.f0_mean <= 0.0 or base.f0 <= 0.0:
        return None

    d_f0 = _deviation(p.f0_mean, base.f0)
    d_energy = _deviation(p.energy, base.energy)
    d_tilt = _deviation(p.tilt, base.tilt)
    d_rate = _deviation(p.rate, base.rate) if p.rate >= 0.0 else 0.0
    d_spread = _deviation(p.f0_spread, base.spread)

    sarcasm = _sarcasm(text_valence, d_energy, d_rate, d_spread)
    if sarcasm is not None:
        return sarcasm

    # CROSS AND EXCITED ARE SEPARATED BY PITCH VARIATION, which is the one
    # genuinely non-obvious rule in here. Both are loud and both sit above
    # resting pitch, so loudness cannot tell them apart. Excitement RANGES --
    # the pitch moves about a lot. Anger is clamped: loud, high, hard-edged and
    # NARROW, because a held jaw does not let the pitch travel. Without the
    # spread term this reported every raised voice as anger.
    loud = d_energy > _HIGH
    high = d_f0 > _HIGH
    harsh = d_tilt > _HIGH
    if loud and (high or harsh) and d_spread < -_LOW:
        return Tone(
            "user_cross",
            _intensity(d_energy, d_tilt, abs(d_spread)),
            _why(energy=d_energy, tilt=d_tilt, spread=d_spread),
        )
    if loud and high and d_spread > _HIGH:
        return Tone(
            "user_excited",
            _intensity(d_energy, d_f0, d_spread, d_rate),
            _why(energy=d_energy, f0=d_f0, spread=d_spread, rate=d_rate),
        )
    if d_energy < -_LOW and d_spread < -_LOW and d_rate < -_LOW:
        return Tone(
            "user_subdued",
            _intensity(abs(d_energy), abs(d_spread), abs(d_rate)),
            _why(energy=d_energy, spread=d_spread, rate=d_rate),
        )
    return None


def _sarcasm(
    text_valence: float | None, d_energy: float, d_rate: float, d_spread: float
) -> Tone | None:
    """Warm words that are not delivered warmly.

    Requires a POSITIVE text reading and a delivery that contradicts it: flat
    pitch, or slowed-down emphasis. Gated on having a text valence at all --
    without one there is nothing for the prosody to disagree with, and guessing
    would make this the tone that fires whenever somebody speaks quietly.
    """
    if text_valence is None or text_valence < 0.35:
        return None
    flat = d_spread < -_LOW and d_energy < 0.0
    drawled = d_rate < -_HIGH and d_spread < 0.0
    if not (flat or drawled):
        return None
    mismatch = text_valence * (abs(d_spread) + abs(min(0.0, d_rate)))
    return Tone(
        "user_sarcastic",
        _clamp(mismatch * 1.6),
        _why(valence=text_valence, spread=d_spread, rate=d_rate),
    )


def _deviation(value: float, baseline: float) -> float:
    """Signed fractional departure from the baseline. 0.0 when unknowable."""
    if baseline <= 0.0 or value <= 0.0:
        return 0.0
    return (value - baseline) / baseline


def _intensity(*deviations: float) -> float:
    """Mean magnitude of the deviations that fired the rule, scaled to 0..1.

    Mean rather than sum, so a rule reading four terms is not automatically more
    intense than one reading two -- intensity should say how far from ordinary
    this utterance was, not how many conditions happened to be in the rule.
    """
    usable = [abs(d) for d in deviations if d != 0.0]
    if not usable:
        return 0.0
    return _clamp(sum(usable) / len(usable) * 2.2)


def _clamp(value: float) -> float:
    return max(0.05, min(1.0, value))


def _why(**terms: float) -> tuple[str, ...]:
    return tuple(f"{name}{value:+.2f}" for name, value in terms.items())
