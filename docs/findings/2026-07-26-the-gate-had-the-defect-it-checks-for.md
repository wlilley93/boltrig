# The gate I wrote to catch environment-dependent checks was one

Date: 2026-07-26. Self-filed, same day, same hour.

## What happened

`scripts/check_prose_references.py` gained a fifth rule: every `[YEAR] VJS-...`
order citation in prose must resolve to a filed order. Orders are federated - a
subscriber repository cites canon rulings it does not hold - so the resolver
searched two registers:

```python
ORDER_REGISTERS = (
    ROOT / ".vjs",
    Path.home() / "Projects" / "vibe-justice-system" / ".vjs",   # <- this
)
```

It passed on this machine. It reddened `main` the moment CI ran it, because that
directory exists on exactly one box. Eighteen canon citations that resolve here
resolve nowhere on a runner.

## Why it matters more than the outage

The goal this gate serves has a tier for precisely this:

> **Tier 3. Close the environment-dependent gates.** `manifest.yaml`,
> `BOLTRIG_TEST_DATABASE_URL`, and the rest of the family where a check passes for
> a reason unrelated to the code.

And its evidence table already carried the instance:

> A test asserting the retired-runtime rule | Passed on any machine with a
> gitignored `manifest.yaml`; failed only in CI

I read that row, wrote a tier about it, closed two members of the family before
lunch, and then built a third into the gate whose job is to close them. Knowing
the failure mode is not protection against it. That is the finding.

## The fix

The citator is now a file in the repository, `.vjs/canon-citations.txt`, and the
gate resolves against it. Nothing in the check path reads anything outside the
repo. Verified by moving the canon checkout aside and re-running: still green.

`scripts/refresh_canon_citations.py` (`make refresh-canon-citations`) is the one
thing allowed to read the canon register, and it is run deliberately, by a human,
when a new canon ruling starts being cited here. A citation absent from the
vendored file fails the gate. That is the point of vendoring it rather than
resolving it live: the gate's answer must depend on the repository's contents and
nothing else.

## What I would tell the next person

Two questions, asked of every check before it lands, that would have caught this:

1. **What outside this repository does this read?** If the answer is anything at
   all, the check's verdict is a fact about a machine.
2. **Run it with that thing absent.** Not reason about it - move the directory,
   unset the variable, and look. The verification here took eleven seconds and
   would have saved a red `main`.

The second is the one that matters. I could have derived the failure from the
code; I did not, and the runner did it for me.
