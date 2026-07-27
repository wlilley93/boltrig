# [2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 - opinion

First Instance, single judge, boltrig County. Case file: SUBMISSION-2026-07-27-124116.
Convening: CONVENING-county-2026-07-27-131315, case file
`sha256:701229f70038c90eb4dc11c727e8c4ac4d7421a6131d7f6b13618d06b7f50ba3`.

**No citation is minted.** `vjs next-citation` refuses to mint the canon COUNTY series at the
BOLTRIG subscriber seat ([2026] VJS-PC 19: capability is not authority), and minting at canon
offers `[2026] VJS-COUNTY 1`, which this repository's own mirror already uses. Numbering by
hand would be the colliding-citation defect of VJS-CC-VJS 1, done deliberately. See obiter O4.

**Implementation status: DISCHARGED, 2026-07-27.** All ten directives landed the same day.
Every test was shown to fail with the fix reverted.

---

## 1. Findings on the facts

All line references are to `boltrig/kernel/dispatch.py` as it stood before this order. Runtime
checks were run against the repository's own `.venv` (jsonschema 4.26.0), which is what ships.

**G1 - CONFIRMED.** Lines 445-447 validate params and raise `SchemaValidationError`.

*Unpleaded and material:* the identical construct exists for OUTPUT validation at 523-525. The
filing does not mention it. An order fixing only the input side fixes half the defect, and
leaves the worse half: the instance there is the adapter's response, which is where
credentials live.

**G2 - CONFIRMED.** Line 354 writes `detail = {"message": str(e)}`; `models/errors.py:28-30`
parks `errors` on `self.errors` and passes only `message` to `super()`. The `errors` list is
read nowhere on the audit path.

**G3 - CONFIRMED, and stronger than pleaded.** Verified at runtime: a wrong-type failure
yields `'sk-live-XYZ' is not of type 'integer'`. The instance value is in the message verbatim.

**G4 - CONFIRMED as to the two functions, MATERIALLY INCOMPLETE in four ways that change the
answer.**

(a) `_summarise_params` and `_summarise_output` exist and carry the quoted docstring.

(b) **They did not feed the audit row.** `args_summary` was computed for `self._emit` only.
"The codebase already has a value-free convention" was true of the run-event stream and of the
aspiration; it was not true of the ledger, which was strictly shallower than the chat stream
beside it.

(c) **The ledger is not value-free today.** `_resource_ref` lifts an INSTANCE VALUE
(`params["id"]`, `params["resource_id"]`, `params["key"]`, up to 128 chars) into
`AuditEvent.resource_id` on every call, under [2026] VJS-COUNTY 9 D1. A bounded instance-value
exception already exists in this ledger and was ordered by this court.

(d) **Not disclosed anywhere in the filing: `detail` is already scrubbed at write time.**
`AuditWriter.write` calls `_scrub` / `_scrub_value` (`kernel/audit.py:144-166`), which digests
any string `pii.contains_secret` hits and otherwise truncates to 256 chars. Every option was
argued as though no scrubber existed. It does, it is a PATTERN LIST, and **the filing's own
worked example is not caught**:

```
pii.contains_secret("'sk-live-xxx' is not of type 'integer'")  -> None
pii.contains_secret("sk-live-xxx")                             -> None
pii.contains_secret("Jane Okonkwo, 14 Bridge St")              -> None
```

`_SECRET_PATTERNS["openai_key"]` is `sk-[A-Za-z0-9]{20,}`; the hyphens in `sk-live-xxx`
truncate the match to four characters. The `stripe_key` pattern wants underscores. The entropy
fallback wants 32+ characters with case and digit diversity. Under Option B the filing's own
illustrative secret lands in the ledger verbatim.

(e) A note, not a breach. The filing states the convention by quoting a SOURCE-FILE DOCSTRING.
[2026] VJS-CC-OPBOX 4 forbids quoting a source comment as the words of a ruling. The filing
does not claim it is a ruling, so it is within bounds, but the authority for keys-only is
COUNTY 9 D6 and invariant K-20, not the docstring.

**G5 - CONFIRMED IN PART, CORRECTED IN THE OPERATIVE HALF.** The 85 rows are real. Two
corrections. They were in OPBOX's ledger, so the incident is precedent and not local history.
And "the remedy was scrub-by-key" is wrong in the way that matters: scrub-by-key is a
write-time, PROSPECTIVE remedy. The court recorded that it "ordered nothing because it could
order nothing"; migration 0023 REVOKEs UPDATE and DELETE on `event`; and CC-OPBOX 108
considered and expressly REFUSED post-write redaction. The 85 rows, plus 110 legacy rows and
3 more, are permanent and unreachable by any erasure request.

Corrected, G5 is considerably stronger AGAINST widening than as pleaded. It is not "we made a
mess and cleaned it up by key". It is "we made a mess, and the only thing law or engineering
could do was stop making more".

**G6 - UNVERIFIED as to the incident, CONFIRMED as to the mechanism, and one further finding.**
The production tenant's ledger is not in this tree, and by G2's own logic the record could not
evidence the cause even if it were. `opbox.get_matter` is confirmed as an MCP-imported verb.

*Further finding, unpleaded and material to G7:* an MCP-imported verb takes its schema
VERBATIM from the remote server's `tools/list` response (`adapters/mcp_consumer.py:207`,
`input_schema=t.get("inputSchema", {})`). For the very class of verb that motivates this
filing, the schema is third-party data arriving over the wire. "Schema-derived" therefore does
not mean "authored by us".

**G7 - CONFIRMED for the `required` case; the safety inference Option A draws from it is
REFUTED on two independent grounds.**

*First refutation.* Option A's Against limb treats a value-bearing `validator_value` as a
hypothetical. It is the defined semantics of two ordinary keywords: `const` yields the literal,
`enum` yields the whole list. With the G6 finding that the schema can be remote data, this is a
live vector.

*Second refutation, and the sharper one.* Option A asserts it "cannot leak instance data
because instance data is never read". **That is false.** `json_path` is derived from the
INSTANCE path:

```
schema:   {"metadata": {"type":"object","additionalProperties":{"type":"integer"}}}
instance: {"metadata": {"sk-live-SECRETKEY": "nope"}}
  json_path -> $.metadata['sk-live-SECRETKEY']
```

Option A as pleaded would write that into an append-only, hash-chained store, and per G4(d)
the scrubber would not catch it.

*What the filing missed.* The field that is genuinely name-only and instance-free is
`absolute_schema_path`, which appears nowhere in the filing. On the identical case it yields
`['properties','metadata','additionalProperties','type']`. It carries no instance value and no
schema value: only schema NAMES. That distinction is the hinge of this judgment.

*And a finding that disposes of Option A's headline claim.* Option A does not make G6
answerable. On the G6 shape the schema paths are `['required']` and `['additionalProperties']`,
and neither names `matterId` nor `matter_id`. Strip `expected`, as the const/enum vector
requires, and Option A answers nothing at all. The load-bearing field for G6 was never in the
option set: it is the recorded params KEY NAMES, which the codebase already computes and threw
away.

---

## 2. Precedent

**BINDS. [2026] VJS-COUNTY 9** (`.vjs/orders/2026-VJS-CC-BOLTRIG-AUDIT-DEPTH-001.yaml`). Same
repo, same jurisdiction, same tier, directly on this ledger. D6 keeps secrets out of every
audit and security-event row (K-20); the forbidden list names putting a secret in a row and
editing or deleting one; D2 requires an MCP-initiated row to be audited at the SAME depth as a
human action; D3 created the security stream.

It disposes of two options without argument:

- **Option B is forbidden by the ratio of a binding order of this court.** Not weighed, refused.
- **Option C rests on a false fact.** The filing says the security stream "is not append-only".
  It is. `SecurityEvent` is documented in `models/audit.py:78-104` as a hash-chained,
  append-only, keys-only row created by COUNTY 9 D3; it carries `seq` / `prev_hash` / `hash`;
  `security_events.py:30,83` imports the SAME `_scrub` and the same HMAC key; and invariant
  SEC-121 binds it. Option C's entire "For" limb is that diverting lowers the bar. It does not.
  It moves the same row to a different table and splits the record, which is Option C's own
  conceded "Against" with nothing left on the other side.

**PERSUASIVE, NOT BINDING. [2026] VJS-CC-OPBOX 4**, *Pseudonymiser verb scope*. This is the
scrub-by-key-after-credentials-and-PII ruling the court asked to have found.

It does not bind: county tier does not bind laterally, it sits in the OPBOX jurisdiction, and
it was absent from boltrig's vendored citator until D9 of this order. It also DISTINGUISHES on
direction: CC-OPBOX 4 governs removing what verbs already emit; this case governs deliberately
ADDING a field nobody has written yet. A rule about the scope of an existing scrub does not
answer the admissibility of a new one.

Two of its ratios are adopted as persuasive, both being stated as general rules: **H1**, that
where a court states a minimisation duty by its purpose and illustrates it with a list, the
purpose binds and the list does not; and **H4**, that the rule is key-only with no carve-outs,
because a name-keyed rule cannot distinguish the safe instance from the unsafe one. And one
part of it is decisive AS FACT regardless of precedential force: the correction to G5.

**PERSUASIVE, ADOPTED, AND THE MOST ON-POINT AUTHORITY IN THE ESTATE. [2026] VJS-CC-OPBOX 5**,
*Credential audited path*, H1:

> "A defence that depends on a string literal matching is not a trust boundary. Where a value
> must never reach a store, the mechanism that keeps it out must be positional or typed, never
> nominal. A nominal defence fails silently under refactor, and silence is the property that
> makes it unacceptable."

Also persuasive from the same order: the forbidden limb of treating the write-time scrub as
discharging the duty, it being a second line and not the first. G4(d) shows that is exactly
what this codebase was doing, and what all three pleaded options implicitly continued.

**PER INCURIAM: none.** COUNTY 9 was made with the chain and K-20 squarely in view.

---

## 3. Reasoning, and the ratio

The filing frames the question as *how much diagnostic power may we buy*. That is the wrong
axis, and it is why three options produced no answer. The right axis is **provenance, per
field**.

> **THE RATIO. A field may enter an append-only store only if its value range is closed at
> build time, or its provenance is wholly the schema and it is name-only. Everything else is
> derived at read time from the system of record, pinned by a digest.**

**(i) Provenance is per field, not per struct.** "Structured, therefore safe" is not an
argument. `{path, keyword, expected}` mixes three provenances in one object: `keyword` is a
closed vocabulary, `path` is instance-derived, `expected` is a schema VALUE. They must be
decided separately, or the least safe one rides in on the reputation of the other two.

**(ii) Schema-derived is not the same as value-free.** A schema is data. It may be third-party
data, and `const` and `enum` place literals in `validator_value` by definition. The safe cut is
not schema-versus-instance, it is NAMES versus VALUES: `absolute_schema_path` yields only
names, `validator_value` yields a value.

**(iii) In a store where nothing can be unwritten, the admissibility test is not "is it usually
safe" but "can it be wrong".** For a mutable store, presumptively-safe plus a scrubber is a
reasonable posture, because a mistake is remediable. For an append-only hash-chained store it
is not, because CC-OPBOX 4 establishes on the record that the remedy for a mistake is nothing:
85 rows, permanent, unreachable, and a court that ordered nothing because it could order
nothing. A defence that is 99% effective against an unbounded stream of untrusted instances is
a defence that fails, in permanent ink, on a schedule.

And, adopting CC-OPBOX 5 H1, the mechanism must be POSITIONAL: the instance is never read on
the audit path. Not "read and then scrubbed". The existing `_scrub` stays as a second line and
must never be the first, because a pattern list is nominal and G4(d) shows this one already
fails open on the filing's own example.

### Applying the ratio

| Field | Provenance | Verdict |
| --- | --- | --- |
| `e.message` | instance, verbatim | **refused** (G3) |
| `e.json_path` / `e.absolute_path` | INSTANCE path | **refused** (G7, proven leak) |
| `e.validator_value` | schema VALUE; may be a literal; may be remote | **refused**; derived at read time |
| `e.validator` | closed Draft 2020-12 keyword vocabulary | **admitted**, through a build-time allowlist |
| `e.absolute_schema_path` | schema, NAME-ONLY | **admitted**, bounded |
| top-level params key names | instance-derived NAMES | **admitted as a bounded exception**, see L1 |

The last row is load-bearing and was in none of the three options. The single change that
actually answers G6 is to put the already-computed `_summarise_params` output on the audit row,
which COUNTY 9 D2 arguably required already. Recorded keys `["limit","matter_id"]` plus keyword
`required`, joined at read time against the registered schema's `required: ["matterId"]`, turns
G6 from a guess into a diff. No instance value, no schema value, no new class of data.

That is also why `expected` need not be stored: it is ALREADY in the store, in
`verb_def.input_schema`. Storing a copy beside the record is storing what can be derived, and
it imports the const/enum leak for no gain. **Store the digest, derive the content.**

---

## 4. Disposition

Option B refused, as forbidden by COUNTY 9. Option C refused, its factual premise being false
on the record. Option A refused AS PLEADED, on all three of its named fields and on its stated
guarantee, which is untrue.

**ADOPTED: Option A as modified**, which is a materially different order. See the ten
directives in the order file.

---

## 5. Limits, recorded as limits and not dressed as orders

**L1.** A top-level param key NAME is instance-chosen. No mechanical check can guarantee it is
never itself sensitive. It is admitted because it is a name and not a value, is capped by D7,
is already durably recorded on the run-event stream, and still passes through `_scrub` as a
second line. Not because it is provably safe. **Do not write a test that pretends otherwise.**

**L2.** Read-time derivation is not point-in-time. On a digest mismatch the reader learns the
schema changed and cannot recover the schema that was in force. The cure, retaining schemas
content-addressed by digest, is named and NOT ordered: reporting the failure honestly beats
answering from a schema that was not in force, and no test can bind an unbuilt store.

**L3.** Nothing in this order reaches a row already written, and nothing may. COUNTY 9 forbids
editing or deleting an audit row, and CC-OPBOX 4 records that post-write redaction was
considered and expressly refused. This order is prevention. There is no cure.

---

## 6. Obiter

**O1.** The real defect behind G6 is not the ledger. An MCP-imported verb's wire name is
snake_case (`opbox_get_matter`) while its schema properties are camelCase (`matterId`), and
nothing at the consumer boundary reconciles them or even notices. A ledger that names the
failing field faster is a better microscope on a defect that should not exist. Normalisation at
the MCP consumer boundary is worth a separate filing and is not decided here.

**O2.** The filing offered three options and none was the answer, for the same reason
CC-OPBOX 4 FC-7 and CC-OPBOX 5 H4 both found: **the pleaded fact base was a sample presented as
a census.** It missed the existing `_scrub`, the existing instance-value exception at
`_resource_ref`, the output-validation twin at 523-525, and `absolute_schema_path`. The last is
the field the correct answer turns on, and it was one attribute away from every fact the filing
did check. Advocates should be required to state what they looked for and did NOT find, not
only what they found.

**O3.** `pii._SECRET_PATTERNS` does not catch a short `sk-live-` token and catches no
natural-person name or address at all. That is not a criticism of the patterns, which are
documented as conservative. It is why the write-time scrub can only ever be a second line, and
it means invariant K-20's test proves less than its name suggests: it proves the scrubber
catches what the scrubber was written to catch.

**O4.** Two filed boltrig orders (`RATE-LIMIT-WINDOW-001`, `WORK-ITEM-LEASE-FENCE-001`) carry
`citation: None`, and this one now makes three. Two binding rulings with no citation is the
defect class CC-OPBOX 4 FC-1 found in the opbox estate and VJS-CC-VJS 1 found in the allocator.
The allocator's refusal to mint at a subscriber seat is correct under VJS-PC 19; what is
missing is a route to mint at canon that knows this seat's mirror already occupies 1 to 12. It
is a citator hazard, it is not before me, and it should be before someone.

---

## Discharge record (2026-07-27)

All ten directives implemented. Files: `boltrig/kernel/schema_diagnosis.py` (new: the rule, the
allowlist, the bounds, `schema_digest`, `diagnose`), `boltrig/kernel/dispatch.py` (`_validate`
rewritten value-free; both raise sites carry a digest; the key summary rides every row),
`boltrig/models/errors.py` (`audit_detail`), `boltrig/kernel/platform_routes/observability.py`
(D5, read-time derivation on `/v1/audit/search`), and
`tests/security/test_schema_validation_ledger.py` (14 tests).

**Every test was shown to fail with the fix reverted.** Restoring `[e.message ...]` in
`_validate` reddens 8 of the 14. That the `scrub_live` case reddens as well as `scrub_disabled`
is the measurement in G4(d) reproducing itself, not a surprise: `pii.contains_secret` does not
match `sk-live-` at all, so the scrubber never was the thing keeping that secret out.

D3's structural check found a legitimate `.message` read on its first run: `err.message` on a
rate-limit error, in the same module. The check was narrowed to ban `.message` only inside the
function that calls `iter_errors`, which is the one place a `ValidationError` exists, and the
other four attributes module-wide. A ban broad enough to hit an unrelated attribute of the same
name would have been switched off, and a gate that gets switched off protects nothing.
