"""The canonical untrusted-input envelope (M1 / SEC-72) - a neutral low-level
helper with no fleet or kernel dependencies.

Untrusted spans (external tool results, the conversation transcript, memory
recall, channel inbound text, user answers) are structurally wrapped so the
model can always tell trusted framing from attacker-controllable data. The
envelope is DATA per the governance floor (fleet/prompt_stack.py); wrapping is
structural, not a regex screen. Both the kernel (which envelopes at its HTTP
edge) and the fleet (which envelopes at prompt-composition time) share this one
implementation, so the kernel never imports the fleet for it.
"""

from __future__ import annotations

import re

# The gap a forged delimiter may hide in: whitespace, AND the invisible format
# characters that are not whitespace to Python. `\s` does not match U+200B, so
# "<\u200buntrusted>" walked straight through the defang until 2026-07-26 - and a
# zero-width space is precisely the character an attacker reaches for, because the
# model reading the prompt sees "<untrusted>" and the regex saw something else.
# U+00A0 and U+2028 were already covered (Python counts them as whitespace); the
# zero-width family and the BOM were not.
_TAG_GAP = r"[\s\u00ad\u200b-\u200f\u2060-\u2064\ufeff]*"
# Matches the '<' that begins an <untrusted...> or </untrusted...> tag (any case,
# tolerant of any such gap after '<' or '</'), so we can defang it inside content.
_UNTRUSTED_TAG_RE = re.compile(
    rf"<(?={_TAG_GAP}/?{_TAG_GAP}untrusted\b)", re.IGNORECASE
)
# Attribute values are labels, not data: strip anything that could close the tag.
_ATTR_UNSAFE_RE = re.compile(r'[<>"\r\n]')


def _neutralise_untrusted_delimiters(content: str) -> str:
    """Defang any literal ``<untrusted`` / ``</untrusted`` delimiter inside DATA so
    the span can never break out of its envelope (M1, the load-bearing part). The
    leading ``<`` of every such tag is replaced with the inert text ``&lt;``; the
    rest of the content is preserved verbatim, so the payload stays fully readable
    as data while it can no longer forge or close an envelope."""
    return _UNTRUSTED_TAG_RE.sub("&lt;", content or "")


def _safe_attr(value: str) -> str:
    """Make an attribute value (kind / source label) tag-safe."""
    return _ATTR_UNSAFE_RE.sub("_", str(value))


def wrap_untrusted(kind: str, source: str, content: str) -> str:
    """Wrap an untrusted span in a typed envelope (M1 / SEC-72).

    Produces ``<untrusted kind="..." source="...">CONTENT</untrusted>`` where
    CONTENT has every literal ``untrusted`` delimiter neutralised, so hostile text
    (e.g. a ``</untrusted>`` inside a tool result) cannot escape the envelope. The
    kind/source attributes are sanitised to a tag-safe form. The governance floor
    tells the model this content is data, never instructions."""
    body = _neutralise_untrusted_delimiters(content)
    return (
        f'<untrusted kind="{_safe_attr(kind)}" source="{_safe_attr(source)}">'
        f"{body}</untrusted>"
    )
