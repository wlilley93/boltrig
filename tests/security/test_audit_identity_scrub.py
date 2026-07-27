"""The audit scrubber sees identity data; the refusal gates do not.

[2026] VJS-COUNTY, variation of CP3 on SUBMISSION-2026-07-27-124116.

The order first required ``contains_secret`` itself to consult the identity
patterns. It was varied because that predicate has six callers and only ONE is
the audit scrubber; at the other five a truthy answer refuses. Ratio of the
variation:

    A predicate shared by call sites that take different actions on its answer
    may not be widened for one of them. Where one consumer needs a broader
    question answered, the answer is a second predicate, not a wider one -
    because widening silently redefines every other consumer's behaviour, and the
    consumer whose behaviour changes is never the one the change was written for.

So there are two predicates, and these tests hold the line between them. The
regression lock is the load-bearing one: it fails if anyone widens
``contains_secret``, which is the change that was ordered, applied for, and
refused.
"""

from __future__ import annotations

import pytest

from boltrig.kernel import audit, pii

# Verified false positives. These decided the variation: each is ordinary content
# that the identity patterns match, and each would have been REFUSED at a memory
# recall or a phase-result admission had the predicate been widened.
_FALSE_POSITIVES = (
    ("run started at 1753600000000", "a 13-digit epoch-millis timestamp matches credit_card"),
    ("kernel at 10.0.1.42 responded", "a host address matches ipv4"),
    ("version 1.2.3.4 shipped", "a semantic version matches ipv4"),
)

# Real identity data. These must not survive the audit path.
_REAL_IDENTITY = (
    ("subject ssn 123-45-6789 on file", "123-45-6789", "ssn"),
    ("card 4111111111111111 declined", "4111111111111111", "credit_card"),
)


# --- the line itself ---------------------------------------------------------
@pytest.mark.security
def test_contains_secret_is_not_widened_by_the_identity_patterns():
    """The regression lock. Ordered as a condition of the variation.

    If this fails, someone has widened the refusal predicate and five call sites
    that refuse on its answer have changed behaviour without being heard.
    """
    for text, why in _FALSE_POSITIVES:
        assert pii.contains_secret(text) is None, f"contains_secret widened: {why} ({text!r})"
    for text, _needle, _kind in _REAL_IDENTITY:
        assert pii.contains_secret(text) is None, (
            f"contains_secret widened to cover identity data ({text!r}); the five "
            f"refusal gates would now refuse it"
        )


@pytest.mark.security
def test_contains_identity_is_the_second_predicate_and_excludes_email():
    for text, _needle, kind in _REAL_IDENTITY:
        assert pii.contains_identity(text) == kind
    # email deliberately stays in contains_secret and is NOT in the identity set:
    # moving it would change what the refusal gates refuse.
    assert pii.contains_identity("reach me at person@example.com") is None
    assert pii.contains_secret("reach me at person@example.com") == "email"


# --- the audit path ----------------------------------------------------------
@pytest.mark.security
def test_false_positives_survive_the_audit_scrub_legibly():
    """Redaction of the SPAN, not digesting of the value.

    Whole-value digesting on a false positive works directly against the order
    this serves: the point of recording a validation failure is that someone can
    later read what happened.
    """
    for text, why in _FALSE_POSITIVES:
        out = audit._scrub_value(text)
        assert isinstance(out, str), f"value was digested wholesale ({why}): {out!r}"
        assert "[REDACTED:" in out, f"expected a redacted span, got {out!r}"
        # the surrounding words stay readable - that is the whole point
        first_word = text.split()[0]
        assert first_word in out, f"context lost from {text!r} -> {out!r}"


@pytest.mark.security
def test_real_identity_does_not_survive_the_audit_scrub():
    for text, needle, kind in _REAL_IDENTITY:
        out = audit._scrub_value(text)
        rendered = out if isinstance(out, str) else str(out)
        assert needle not in rendered, f"{kind} survived the scrub: {rendered!r}"


@pytest.mark.security
def test_a_secret_still_digests_the_whole_value():
    """Unchanged behaviour: a secret taints its context, so span substitution is
    not enough. An adjacent fragment can carry the rest of the credential."""
    out = audit._scrub_value("token sk-abcdefghijklmnopqrstuvwx here")
    assert isinstance(out, dict) and out.get("_scrubbed") is True


# --- keys, which were outside the scrub entirely -----------------------------
@pytest.mark.security
def test_dict_keys_are_scrubbed_not_copied_verbatim():
    """Head 5 of the variation. The loop scanned values and copied keys.

    A caller-supplied dict key is caller-supplied data, and the principal ratio
    reaches it without extension: a record of a failure is composed from what the
    system asserted, never from what the caller supplied.
    """
    out = audit._scrub({"sk-abcdefghijklmnopqrstuvwx": "v", "ssn 123-45-6789": "w"})
    joined = " ".join(str(k) for k in out)
    assert "sk-abcdefghijklmnopqrstuvwx" not in joined, f"secret key copied verbatim: {joined!r}"
    assert "123-45-6789" not in joined, f"identity key copied verbatim: {joined!r}"


@pytest.mark.security
def test_the_known_consumer_keys_are_untouched():
    """observability.py reads id/verb_id/verb by name; the scrub must not rename them."""
    out = audit._scrub({"id": "1", "verb_id": "authoring.x", "verb": "authoring.x"})
    assert set(out) == {"id", "verb_id", "verb"}
