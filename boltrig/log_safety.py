"""One-line-per-record logging for values an outside party chose.

A LOG LINE IS A RECORD FORMAT, AND A NEWLINE IS ITS DELIMITER. Interpolating a
caller-supplied string into a log message lets that caller end the record and
start another one, so a URL containing ``\\n2026-01-01 INFO egress allowed for
https://evil.example`` reads back from the journal as two entries, the second of
which nothing in this system wrote. That is the whole of CWE-117: it does not
crash anything, it makes the audit trail say something false, which is worse
here than in most places because these particular records exist to prove refusals
happened.

CodeQL found five instances (``py/log-injection``) in the capability-doctrine
integration: the egress refusal line, and two dispatch failure lines carrying a
route's noun and verb.

This module has NO imports from the rest of the package on purpose. It is used
from ``boltrig/adapters`` and ``boltrig/kernel`` alike, and a shared helper that
can only be imported by half its callers gets copied instead, which is how two
copies of a rule become one copy and a disagreement.
"""

from __future__ import annotations

__all__ = ["log_safe"]

_LIMIT = 200


def log_safe(value: object, limit: int = _LIMIT) -> str:
    """Render ``value`` so it cannot forge or flood a log record.

    Three things, in this order, because each one bounds a different abuse:

    - **Every C0/C1 control character becomes an escape.** Not just CR and LF:
      the journal, `less`, and most terminals also act on NUL, backspace and
      ESC, and an ESC sequence in a log a human is reading can repaint the line
      it is on. `repr`-style ``\\xNN`` keeps the byte visible and inert.
    - **DEL and the Unicode line separators too** (U+007F, U+0085, U+2028,
      U+2029). A CR/LF-only filter is the near-miss version of this function:
      Python's own ``str.splitlines`` treats U+2028 as a line break, so a reader
      that uses it sees two lines from a string that passed the filter.
    - **Truncation, with a marker.** An unbounded field is a disk-fill and a
      make-the-real-line-scroll-away vector, and a silent truncation is a lie
      about what was received, so the length is stated.

    Returns a plain ``str``; the caller still passes it as a %-arg rather than
    concatenating, so the logging module keeps doing its own formatting.
    """

    text = value if isinstance(value, str) else str(value)
    out = []
    for ch in text:
        code = ord(ch)
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            out.append(f"\\x{code:02x}")
        elif code in (0x2028, 0x2029):
            # \u form, not \x: "\\x2028" reads as \x20 followed by "28", which
            # is a space and two digits - an escape that is itself ambiguous
            # tells the reader the wrong thing about what arrived.
            out.append(f"\\u{code:04x}")
        else:
            out.append(ch)
    rendered = "".join(out)
    if len(rendered) > limit:
        return f"{rendered[:limit]}...[{len(rendered)} chars]"
    return rendered
