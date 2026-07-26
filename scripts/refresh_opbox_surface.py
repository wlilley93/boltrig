#!/usr/bin/env python3
"""Re-vendor `tests/fixtures/opbox-model-surface.txt` from the opbox schema.

[2026] VJS-COUNTY 8 D9 ordered that boltrig copy "only the opbox auth/tenancy
core, never its domain models". Binding that needs to know what opbox's model
surface IS - and opbox is a SEPARATE PRIVATE REPOSITORY that boltrig's CI does not
check out.

Reading it off the author's disk at check time is not an option. That is exactly
how the prose-references gate came to pass locally and fail in CI: a check that
depends on a directory being present on one box is the defect class the goal it
serves exists to close. So the surface is VENDORED, on the same pattern and for
the same reason as `.vjs/canon-citations.txt`, and refreshed deliberately.

What is vendored is table NAMES only - not columns, not relations, not a single
line of opbox's schema. A list of table names carries no client data and no
design detail; it is the minimum needed to answer "did one of these arrive here".

Usage:
    python scripts/refresh_opbox_surface.py --opbox ~/Projects/opbox-prod
    make refresh-opbox-surface
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDORED = ROOT / "tests" / "fixtures" / "opbox-model-surface.txt"
SCHEMA = Path("opbox-frontend") / "prisma" / "schema.prisma"

HEADER = """\
# Opbox's model surface, as TABLE NAMES, vendored into boltrig.
#
# [2026] VJS-COUNTY 8 D9: boltrig copies "only the opbox auth/tenancy core, never
# its domain models". tests/security/test_opbox_domain_boundary.py holds that by
# comparing boltrig's own tables against this list, so a domain table arriving
# here fails a check rather than a code review.
#
# Vendored rather than read from ~/Projects/opbox-prod at check time: opbox is a
# separate private repository that boltrig's CI does not check out, and a gate
# that depends on a directory existing on one machine is the exact defect the
# goal it serves exists to close (it already happened once, to the
# prose-references gate). Same pattern as .vjs/canon-citations.txt.
#
# TABLE NAMES ONLY - no columns, no relations, no schema. A name list carries no
# client data and no design detail.
#
# Refresh deliberately with `make refresh-opbox-surface` when opbox's schema
# moves. A stale list is conservative here: it can miss a NEW opbox domain table,
# never invent one.
"""


def table_names(schema: str) -> list[str]:
    """Each model's table name: its `@@map(...)` if it has one, else the model."""
    names: set[str] = set()
    for name, body in re.findall(r"^model\s+(\w+)\s*\{(.*?)^\}", schema, re.MULTILINE | re.DOTALL):
        mapped = re.search(r'@@map\("([^"]+)"\)', body)
        names.add(mapped.group(1) if mapped else name)
    return sorted(names)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opbox", required=True, type=Path, help="path to the opbox repo")
    args = parser.parse_args()

    schema_path = args.opbox.expanduser() / SCHEMA
    if not schema_path.is_file():
        print(f"refresh-opbox-surface: no schema at {schema_path}", file=sys.stderr)
        return 1

    names = table_names(schema_path.read_text(encoding="utf-8"))
    if not names:
        # A schema that parses to nothing would silently empty the list and make
        # the boundary check vacuous - refuse rather than write it.
        print(f"refresh-opbox-surface: parsed NO models out of {schema_path}", file=sys.stderr)
        return 1

    VENDORED.write_text(HEADER + "\n".join(names) + "\n", encoding="utf-8")
    print(f"refresh-opbox-surface: vendored {len(names)} table names -> {VENDORED.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
