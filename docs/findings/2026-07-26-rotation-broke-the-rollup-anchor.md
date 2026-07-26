# Rotating the audit key made `/v1/audit/verify` report a broken audit over an intact one

Date: 2026-07-26. Found live on the Classical Visas production tenant, **after** the audit key
epoch shipped in boltrig 0.4.3. **Fixed** in the same pass.

## The finding

CV's `/v1/audit/verify`, called with the tenant's admin PAT:

```json
{
  "chain_intact": true,
  "security_chain_intact": true,
  "anchor_intact": false,
  "anchor": {"seq_start": 104, "seq_end": 111, "is_dev_fallback": true},
  "intact": false
}
```

The chain verifies, row by row, across the key rotation - that is the epoch working. The
**rollup anchor** over seqs 104-111 does not, so the endpoint's headline answer is
`intact: false`. A regulator, or an operator, asking "is this tenant's audit sound?" is told no,
about an audit that is sound.

## Cause

`segment_root_hash` (`boltrig/kernel/security_events.py`) is an HMAC over the segment's row
hashes, keyed by the **same** audit secret as the chain. It took no key parameter at all:

```python
mac = hmac.new(_HMAC_KEY, b"boltrig-audit-rollup-v1", hashlib.sha256)
```

`_HMAC_KEY` is the LIVE key. The epoch work taught `verify_chain` to resolve exactly one key per
row from its seq, and never reached one level up to the anchor. So the first rotation left every
pre-rotation anchor permanently un-verifiable: the anchor was sealed under the old key, and
verification recomputed it under the new one.

This is the same defect the epoch existed to cure, one layer higher, introduced by the fix for it.

## Why it matters more than a cosmetic false negative

A permanently-failing integrity check is indistinguishable from tampering, and it trains whoever
reads it to ignore the field. That is strictly worse than not having the check: it converts a
real signal into noise at exactly the moment - after a key compromise - when you most need it.
It also recreates the perverse incentive the epoch removed: never rotate a leaked key, because
rotating breaks your verifier.

## The fix

`key_in_force_at(seq)` is now public in `kernel/audit.py`, and **both** sides of the anchor
resolve through it on the segment's `seq_end`:

```python
root = segment_root_hash(segment, key=key_in_force_at(seq_end))          # write
segment_root_hash(segment, key=key_in_force_at(anchor.seq_end)) == ...   # verify
```

`seq_end`, not `seq_start`, and the same expression on both sides, so write and read agree by
construction:

- an anchor written before a rotation covers rows entirely below the boundary, so it resolves to
  the retired key - the key that actually sealed it;
- an anchor written after a rotation includes at least one row at or above the boundary, so it
  resolves to the live key;
- anchoring a stale range *after* a rotation seals with the retired key. That is not a new
  weakness: those rows' own hashes are already under that key, so the anchor is exactly as strong
  as what it covers, never weaker.

## Verification

`tests/security/test_audit_key_epochs.py`, seeded to fail before being believed:

| Test | What it pins |
|---|---|
| `an_anchor_sealed_before_a_rotation_still_verifies_after_it` | the live failure; reverting the fix fails exactly this one |
| `without_the_epoch_the_same_anchor_reports_a_broken_audit` | the control - the state CV was in |
| `the_anchor_still_catches_a_rewritten_row_across_the_rotation` | the fix is not "delete the check": a rewritten row inside the range still breaks it |
| `the_anchor_resolves_its_key_from_its_newest_row` | write and read use the same resolution |

## Reproduce (before the fix)

```bash
PAT=$(docker exec Opbox-Frontend printenv BOLTRIG_ADMIN_PAT)
docker exec cv-boltrig-kernel-1 python -c "
import urllib.request, json
r = urllib.request.Request('http://localhost:8000/v1/audit/verify',
                           headers={'Authorization': 'Bearer $PAT'})
print(json.loads(urllib.request.urlopen(r, timeout=20).read()))"
# -> chain_intact True, anchor_intact False, intact False
```

## The pattern this is the fifth of

An audit chain verifying green under a key published in the repository. Retention recorded BUILT
with zero callers. An approval at `consumed` whose write had failed. A secret "configured" that
was the shipped placeholder. `/readyz` calling a load-bearing gateway `disabled`. Now a verifier
crying wolf. In every one the reported state was confident and the real state was different -
in both directions. Seed the failure before believing the check, and prefer the record over any
summary of it.
