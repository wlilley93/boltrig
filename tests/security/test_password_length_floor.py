"""The password length floor, pinned in both directions.

The floor was 12 and is 10 (Principal's decision, 2026-08-24, matching the opbox
minimum lowered the same day). It was previously asserted by NOTHING: no test
named MIN_PASSWORD_LENGTH, so the constant could be moved in either direction -
including to 1 - without a single test going red. A security floor that nothing
measures is a comment.

Both controls are here deliberately. A test that only checks the accept case
passes against a floor of zero; a test that only checks the reject case passes
against a floor of a thousand. Only the pair pins the number.
"""

import pytest

from boltrig.identity.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    WeakPassword,
    validate_password_strength,
)


def test_the_floor_is_ten() -> None:
    assert MIN_PASSWORD_LENGTH == 10


def test_a_password_exactly_at_the_floor_is_accepted() -> None:
    # Exactly 10. This is the case the 12-floor refused, and the reason it moved.
    password = "HXNCtt123!"
    assert len(password) == MIN_PASSWORD_LENGTH
    validate_password_strength(password)


def test_a_password_one_short_of_the_floor_is_refused() -> None:
    # THE NEGATIVE CONTROL. Without it, every assertion above passes against a
    # floor of zero.
    password = "a" * (MIN_PASSWORD_LENGTH - 1)
    with pytest.raises(WeakPassword):
        validate_password_strength(password)


def test_the_refusal_names_the_floor_it_applied() -> None:
    with pytest.raises(WeakPassword) as caught:
        validate_password_strength("short")
    assert str(MIN_PASSWORD_LENGTH) in str(caught.value)


@pytest.mark.parametrize("bad", ["", None, 12345])
def test_a_non_string_or_empty_password_is_refused(bad: object) -> None:
    with pytest.raises(WeakPassword):
        validate_password_strength(bad)  # type: ignore[arg-type]


def test_the_dos_cap_is_unchanged_by_the_floor_move() -> None:
    # The floor moved; the upper sanity cap that stops a huge input becoming a
    # DoS through argon2 did not.
    assert MAX_PASSWORD_LENGTH == 1024
    with pytest.raises(WeakPassword):
        validate_password_strength("a" * (MAX_PASSWORD_LENGTH + 1))
