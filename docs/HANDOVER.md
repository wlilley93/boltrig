# Boltrig handover

There is no single rolling engineering handover, and this file no longer
claims there is one.

Since 2026-07-21 the working convention has been one dated, per-topic document
per session, named `HANDOVER-<YYYY-MM-DD>-<topic>.md` in this directory. Each
one covers the work of that session. None of them is a project status report,
so do not read the newest as if it were.

To find them, ask the tree rather than this file. Sorted newest first:

    ls docs/HANDOVER-*.md | sort -r

## Why this file stopped naming one

It used to say `HANDOVER-2026-07-21.md` was "the current engineering
handover". It kept saying that through sixteen later handovers across eleven
distinct dates, the first of which landed two days after the pointer was
written.

The defect was not that nobody updated it. It was that it stored a fact that
changes, in a file nothing forces you to touch when the fact changes, so it
was one edit away from wrong on the day it was written and nothing failed when
it went wrong. A pointer of that shape is worse than no pointer: it answers
confidently, so you stop looking.

The listing above is derived instead. It cannot go stale.

## What is still canonical

The creative and visual north star is a genuinely maintained canonical
document, and lives separately in
[`design/CREATIVE-HANDOVER.md`](design/CREATIVE-HANDOVER.md).
