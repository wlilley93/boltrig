"""What may be recorded about a schema-validation failure, and how it is read back.

The schema-validation ledger order (county, First Instance, 2026-07-27, on
SUBMISSION-2026-07-27-124116; opinion at
``docs/vjs/2026-VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001-opinion.md``).

THE RULE IT SETTLES, stated so it applies to the next field as well as this one:

    A field may enter an append-only store only if its value range is closed at build time,
    or its provenance is wholly the schema AND it is name-only. Everything else is DERIVED at
    read time from the system of record, pinned by a digest.

Three corollaries, each doing distinct work:

  1. PROVENANCE IS PER FIELD, NOT PER STRUCT. "Structured, therefore safe" is not an
     argument. ``{path, keyword, expected}`` mixes three provenances in one object: keyword
     is a closed vocabulary, path is instance-derived, expected is a schema VALUE. Decide
     them separately, or the least safe one rides in on the reputation of the other two.

  2. SCHEMA-DERIVED IS NOT VALUE-FREE. A schema is data, and for an MCP-imported verb it is
     THIRD-PARTY data: ``adapters/mcp_consumer.py`` takes ``input_schema`` verbatim from the
     remote server's ``tools/list`` response. ``const`` and ``enum`` put literals in
     ``validator_value`` by definition. The safe cut is names versus values, not schema
     versus instance.

  3. IN A STORE WHERE NOTHING CAN BE UNWRITTEN, THE TEST IS NOT "IS IT USUALLY SAFE" BUT
     "CAN IT BE WRONG". For a mutable store, presumptively-safe plus a scrubber is a
     reasonable posture, because a mistake is remediable. Here it is not: 85 rows of raw PII
     in a sibling estate's ledger are permanent and unreachable, migration 0023 REVOKEs
     UPDATE and DELETE on ``event``, and the court that found them ordered nothing because
     it could order nothing. A defence that is 99% effective against an unbounded stream of
     untrusted instances fails, in permanent ink, on a schedule.

WHY THE WRITE-TIME SCRUB IS NOT THE ANSWER. ``kernel/audit.py`` already digests
secret-shaped strings on the way in. It is a PATTERN LIST, and a pattern list is a nominal
defence: ``pii.contains_secret("'sk-live-xxx' is not of type 'integer'")`` returns None, and
so does ``contains_secret("sk-live-xxx")``, because the hyphens truncate the ``sk-[A-Za-z0-9]
{20,}`` pattern to four characters. The filing's own illustrative secret is not caught. So
the scrub stays as a SECOND line and the first line is positional: the instance is never read
on this path at all. ``tests/security/test_schema_validation_ledger.py`` proves that by
running the leak test with ``contains_secret`` monkeypatched to return None.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# The Draft 2020-12 keyword vocabulary, as an ALLOWLIST rather than a passthrough. A
# `validator` outside it, or a None, is recorded as "unknown": the value comes from the
# schema, and an MCP-imported schema is third-party data, so a custom keyword could be any
# string at all.
SCHEMA_KEYWORDS = frozenset({
    "additionalItems", "additionalProperties", "allOf", "anyOf", "const", "contains",
    "contentEncoding", "contentMediaType", "contentSchema", "dependentRequired",
    "dependentSchemas", "else", "enum", "exclusiveMaximum", "exclusiveMinimum", "format",
    "if", "items", "maxContains", "maxItems", "maxLength", "maxProperties", "maximum",
    "minContains", "minItems", "minLength", "minProperties", "minimum", "multipleOf",
    "not", "oneOf", "pattern", "patternProperties", "prefixItems", "properties",
    "propertyNames", "required", "then", "type", "unevaluatedItems", "unevaluatedProperties",
    "uniqueItems",
})

# Bounds. An append-only store cannot be trimmed later, so the ceiling is applied at the one
# moment it can be: before the row is written.
MAX_SCHEMA_ERRORS = 10
MAX_SCHEMA_PATH_DEPTH = 10
MAX_SCHEMA_PATH_SEGMENT = 64
MAX_PARAM_KEYS = 50


def schema_digest(schema: dict[str, Any] | None) -> str:
    """sha256 over the canonical form of a verb's registered schema.

    The EXPECTATION is not stored beside the failure, it is derived from the schema at read
    time, and this digest is what makes that safe. On a mismatch the reader is told the
    schema moved, rather than being handed a diff computed against a schema that was not in
    force. Storing a copy of the expectation instead would store what can be derived, and
    would import the const/enum leak for no gain.
    """
    canonical = json.dumps(schema or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def diagnose(detail: dict[str, Any] | None, schema: dict[str, Any] | None) -> dict[str, Any]:
    """Render a recorded ``schema_invalid`` failure against the schema in force NOW.

    This is the read-time half of the order. Nothing here is stored; every expectation is
    re-derived from ``schema`` on each read, which is why no expectation had to go into the
    row.

    States, and each is a distinct thing the reader needs to be able to tell apart:

      * ``not_recorded``  - the row predates the order, or is not a schema failure. There is
        nothing to diagnose and saying so beats an empty diff.
      * ``schema_moved``  - the recorded digest is not the current schema's. NO diff is
        offered. Read-time derivation is not point-in-time, and answering from a schema that
        was not in force is worse than declining (limit L2 of the order).
      * ``diagnosed``     - the recorded key names, compared against the current schema.
    """
    if not isinstance(detail, dict) or "schema_errors" not in detail:
        return {"state": "not_recorded"}

    recorded = detail.get("schema_digest")
    current = schema_digest(schema)
    if recorded != current:
        return {
            "state": "schema_moved",
            "recorded_digest": recorded,
            "current_digest": current,
            "note": (
                "the verb's schema changed after this row was written, so the failure cannot "
                "be diffed against it. The schema in force at the time is not retained."
            ),
        }

    keys = list((detail.get("params") or {}).get("keys") or [])
    properties = sorted((schema or {}).get("properties", {}) or {})
    required = list((schema or {}).get("required") or [])

    return {
        "state": "diagnosed",
        "keys_sent": keys,
        "missing": sorted(k for k in required if k not in keys),
        # Only meaningful where the schema names its properties. A schema with none accepts
        # anything at the top level, so calling every key unexpected would be noise.
        "unexpected": sorted(k for k in keys if properties and k not in properties),
        "errors": detail.get("schema_errors") or [],
        "truncated": bool(detail.get("truncated")),
    }
