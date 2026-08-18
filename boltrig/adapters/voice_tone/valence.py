"""A lexical warmth gate -- the text half of the sarcasm test, and no more.

THIS IS NOT A SENTIMENT ANALYSER and must not be used as one. It exists for
exactly one job: :func:`boltrig.adapters.voice_tone.tone.classify` needs to know whether the
WORDS were warm, so that flat or drawled delivery of warm words can be read as
sarcasm. Sarcasm is the two channels disagreeing, so the text side only has to
answer "were these words positive", which a word list can do.

Why not an LLM pass. It would be better at this and it would cost a model round
trip on the path of every spoken turn, to produce one number that is then only
consulted when the prosody already looks contradictory. If the sarcasm signal
proves worth sharpening, replacing this with a real classifier is a one-function
change -- ``classify`` takes ``text_valence`` as a plain float and does not care
where it came from.

Its limits, stated so nobody has to discover them: no negation handling, so "not
great" reads as positive. No intensifiers. No emoji. English only. Those are
acceptable HERE because a false positive merely arms a test that prosody must
then also fail, and the appraisal it can produce is the mildest of the four.
"""

from __future__ import annotations

import re

# Deliberately short and deliberately obvious. A longer list would invite the
# belief that this measures sentiment; these are the words that actually appear
# when somebody is being nice, or being nice on the surface.
_WARM = frozenset(
    """
    great good lovely excellent perfect wonderful brilliant fantastic nice
    thanks thank cheers please love loved lovely amazing awesome super
    beautiful clever helpful kind well done congratulations impressive
    delighted pleased happy glad marvellous splendid fine grand terrific
    """.split()
)

_COLD = frozenset(
    """
    bad awful terrible broken wrong useless rubbish stupid hopeless
    annoying pointless disaster failed failing hate hated angry furious
    unacceptable ridiculous nonsense appalling dreadful
    """.split()
)

_WORD = re.compile(r"[a-z']+")


def warmth(text: str) -> float | None:
    """How warm the words are, -1..1, or None when there is nothing to judge.

    None rather than 0.0 for an empty or wordless transcript: zero would mean
    "neutral, and I checked", which is a different claim from "I cannot say", and
    the sarcasm gate treats them differently.
    """
    words = _WORD.findall(text.lower())
    if not words:
        return None
    warm = sum(1 for w in words if w in _WARM)
    cold = sum(1 for w in words if w in _COLD)
    if warm == 0 and cold == 0:
        return None
    # Normalised by the HITS, not by the length of the utterance. "thanks, that
    # is exactly what I needed, you have saved me an afternoon" should not score
    # lower than "thanks" for having more neutral words around it.
    return (warm - cold) / (warm + cold)
