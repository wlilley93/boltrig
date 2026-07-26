# Classical Visas' audit chain was keyed by a public constant

Date: 2026-07-26. Live finding on the CV production tenant, remediated the same day.

## The finding

`cv-boltrig-kernel-1` logged, every boot:

> audit chain is using the IN-SOURCE default HMAC key: it is NOT tamper-evident. Anyone with this
> repository can forge the chain.

`BOLTRIG_AUDIT_HMAC_KEY` was set and 33 characters long, which looks configured. It was the literal
placeholder shipped in `.env.example`:

```
BOLTRIG_AUDIT_HMAC_KEY == "change-me-to-a-long-random-secret"   # True
```

So the tamper-evidence hash chain of a CLIENT's regulated matter system was keyed by a constant
published in this repository. Anyone with the repo could forge any entry and the chain would still
verify.

The trap is that it verified. `k.audit.verify('default')` returned **OK** across all 111 rows. A
green verify on a chain keyed by a public constant is worse than no verify at all: it is a false
assurance, the same shape as a deletion certificate claiming a completeness it does not have.

## What was and was NOT affected

| stack | key | state |
|---|---|---|
| **cv-boltrig** (the client) | the shipped placeholder | FORGEABLE |
| boltrig (app.boltrig.io) | 64-char secret | correct |

The tooling was never wrong: `boltrig-tenant/gen-tenant.sh:253` generates a per-tenant secret
(`gensecret`) and `env.tenant.tmpl` templates it. CV's env predates that path or was hand-built from
`.env.example`, so this is a one-tenant provisioning miss, not a systemic defect. **New tenants are
unaffected.**

Note the fatal/warn split in `api/bootstrap.py:477`: with a production signal set, a placeholder key
is a hard `RuntimeError`. Nothing sets a production signal by default (compose emits an empty
`BOLTRIG_PRODUCTION`), so a real client deployment lands in the warn branch and runs forgeable while
logging about it. **The loudest available signal was a log line nobody was reading.**

## Remediation

Rotated to `openssl rand -hex 32` and recreated the kernel + fleet-worker. Placeholder warning gone,
stack healthy, 0 restarts. Prior env kept at `boltrig.env.bak-pre-hmac-rotation`.

### The cost, stated plainly

There is **no key-rotation mechanism**. `verify_chain` re-derives from seq 1 under one key, so
rotating means the pre-rotation segment can never verify again:

```
before rotation:  verify(default) = OK    (under a public key, so it proved nothing)
after  rotation:  verify(default) = FAILS at first_bad_seq = 1
```

This was a deliberate trade, not an accident:

* the 111 pre-rotation rows had **zero** evidentiary value already - a chain anyone can forge proves
  nothing, so no real assurance was lost;
* leaving the placeholder would have kept accruing worthless entries indefinitely;
* the new state fails CLOSED (honest "cannot verify") rather than open (false "verified").

**Pre-rotation attestation**, so the discontinuity is documented rather than mistaken for tampering:

```
tenant     default
rows       111   (seq 1..111, 2026-07-24 .. 2026-07-26)
head hash  878054d58a469abb44d703eaef7653f63fa85e8749252c1001ee17938d3ca550
verify     OK under the pre-rotation key (which was public, hence not probative)
```

**Anyone seeing `verify` fail at seq 1 on cvboltrig: that is this rotation, not tampering.** Entries
from seq 112 onward are the first that were ever genuinely tamper-evident.

Checked before rotating: `fleet/anchor.py` never calls `verify` and swallows faults by design (P9),
so a non-verifying chain does not break the anchor janitor or any health check.

## Open, and worth its own change

1. **No key rotation exists.** The correct fix is a key epoch - record which key sealed which seq
   range so `verify_chain` can validate each segment under the key that sealed it. Without it, every
   future rotation permanently breaks verification of everything before it, which is a strong
   incentive never to rotate a leaked key. That is the wrong incentive to build in.
2. **A permanently failing `verify` is poor signal.** It is honest, but indistinguishable from
   tampering at a glance, and a check that always fails is a check people learn to ignore. The epoch
   fix resolves this too.
3. **Placeholder detection should be checked at PROVISIONING, not only logged at boot.** The
   predicate already exists (`config/weak_secrets.is_placeholder_secret`). A tenant should not be
   able to reach a client with a known placeholder in any secret, whatever the production signal
   says.
