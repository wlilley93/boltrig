"""Channel attribution: a caller may label the surface, never steer the routing.

The requirement is "one conversation, two surfaces": a message typed into an
Opbox spotlight and the same thread in the boltrig UI are one conversation, and
each turn says which channel it arrived through.

The obvious implementation is a caller-supplied ``WorkItem.source`` - opbox
already stamps ``source='opbox'`` at intake, so it reads like the field's purpose.
It is a trap, and ``test_source_is_not_a_label_it_selects_a_department`` below
proves it against the real router rather than against a comment: ``source``
SELECTS THE HANDLING DEPARTMENT, so accepting it from a client would hand routing
authority to the requester through what looks like a display field.
"""

import pytest

from boltrig.fleet.chat_origin import MAX_ORIGIN_LENGTH, normalised_origin


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("opbox-spotlight", "opbox-spotlight"),
        ("  Opbox-Spotlight  ", "opbox-spotlight"),  # trimmed and folded
        ("boltrig.ui", "boltrig.ui"),
        ("app:web", "app:web"),
        ("x", "x"),
        ("a" * MAX_ORIGIN_LENGTH, "a" * MAX_ORIGIN_LENGTH),
    ],
)
def test_a_usable_label_survives_canonicalisation(raw, expected):
    assert normalised_origin(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        123,
        b"opbox",
        {"origin": "opbox"},
        "a" * (MAX_ORIGIN_LENGTH + 1),  # bounded: stored, so it cannot be unbounded
        "-leading-separator",  # must START alnum, so a label cannot read as a flag
        "opbox spotlight",  # no whitespace
        "opbox/spotlight",  # no path separator
        "opbox\nspotlight",  # no newline: it is written into records and logs
        "opbox‐ui",  # non-ASCII lookalike separator
    ],
)
def test_an_unusable_label_is_dropped_and_never_refuses_the_message(raw):
    # None leaves source_id NULL, which is exactly today's behaviour: a client
    # that sends nothing - or sends rubbish - still gets its answer. An attribution
    # label is not worth failing a person's message over.
    assert normalised_origin(raw) is None


def test_source_is_not_a_label_it_selects_a_department():
    """Why the origin is NOT ``WorkItem.source``, proven against the real router.

    This is the whole reason ``chat_origin`` exists. If someone later "simplifies"
    this by letting the caller set ``source``, this test still passes - and the
    one below it, which asserts the chat lane pins ``source='chat'``, is what goes
    red. Both are needed: this one establishes that ``source`` carries authority.
    """

    from boltrig.fleet.chief_of_staff import ChiefOfStaff

    departments = [
        type("D", (), {"name": "legal", "queue_sources": ("opbox",), "keywords": ()})(),
        type("D", (), {"name": "finance", "queue_sources": ("billing",), "keywords": ()})(),
    ]
    cos = type("C", (), {"_current_departments": lambda self: departments})()
    route = ChiefOfStaff._route_deterministic
    item = type("W", (), {"source": "billing", "intent": "anything at all"})()
    assert route(cos, item) == "finance"
    item.source = "opbox"
    assert route(cos, item) == "legal"
    # Same work, same words, different department - chosen entirely by `source`.
