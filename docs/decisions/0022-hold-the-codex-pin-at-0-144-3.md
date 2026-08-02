# Decision 0022: hold the Codex pin at 0.144.3

**Status:** DONE, and it is a decision to NOT change. **Authority:** none needed; a
reversible, low-blast engineering call. **Occasion:** the Principal asked, 2026-08-02,
"should we get the latest pin and upgrade boltrig", after the operator seat's Codex CLI was
reconfigured to enable native Subagents v2 for the `codex-security` deep scan.

## The decision

The fleet pin stays at `CODEX_CLI_VERSION = "0.144.3"`,
`CODEX_CLI_SHA256 = "37e6f595...700b"`. No upgrade.

## Why, in order of how decisive each reason is

**1. Nothing is broken.** The pin is HEALTHY, not stale. Measured 2026-08-02:
`~/.codex/packages/standalone/releases/0.144.3-x86_64-unknown-linux-musl/bin/codex`
hashes to exactly `37e6f595...700b`. A pin whose artefact is present and matching is a
working pin, and "the number looks old" is not a fault.

**2. There is nothing to upgrade TO.** The standalone releases on this box are 0.135.0,
0.136.0, 0.137.0, 0.142.5, 0.143.0 and 0.144.3. There is no 0.145 or 0.146 standalone musl
release here. The `codex-cli 0.146.0` on PATH resolves to
`.nvm/.../node_modules/@openai/codex/bin/codex.js`, an npm JavaScript shim: a different
ARTEFACT SHAPE from the musl binary the pin describes and the cell policy hashes. Repinning
to it would not be a version bump, it would change what kind of thing is being pinned, and
every property `codex_cell_policy` verifies (regular file, not group-writable, exact digest,
opened `O_NOFOLLOW` and re-stat'ed against TOCTOU) is a property of that binary.

**3. It is a protocol migration, not a bump.** Three separate seams break:

  - `codex_native_collaboration_wire.py:10` pins the single tool namespace the ceiling
    admits as `multi_agent_v1`. That string appears ZERO times in the 0.146.0 binary, where
    `features.multi_agent_v2.tool_namespace` is a configurable field instead.
  - `schemas/codex/` holds `0.144.3` and nothing else.
  - `codex_runtime_events.py:186-190` rejects any thread whose reported `cliVersion` is not
    0.144.3.

**4. Nothing needs it.** The feature that raised the question, native subagents, is one
boltrig refuses on purpose and in four places: a zero CEILING in both lanes'
`NativeSubagentPolicy`, `BirthPolicyRejected` before admission is constructed, the
`CodexRuntimeAdmissionError` backstop pinned by SEC-159, and two fail-closed wire tripwires.
Upgrading to obtain a capability the estate deliberately refuses is not an upgrade.

## What this decision does NOT say

It does not say the pin should never move. It says moving it is a project with a design
question in it, not a chore. When it moves it will need: a 0.14x standalone release obtained
and its digest reviewed, `schemas/codex/<version>/` regenerated, the collaboration namespace
re-verified against the new binary rather than assumed, and the `cliVersion` gate updated in
the same change. A native-subagent UPLIFT on top of that would additionally need per-thread
kernel identities, a sandbox-engagement re-probe per thread, and per-cell memory bounds, none
of which exist; that one is first-impression and belongs to the court, not to this file.

## What was built alongside it

`scripts/check_codex_pin_health.py`, wired into `make check`. Two risks were live and
uncovered when this decision was taken:

  - **Nothing checked the pinned binary was still PRESENT.** `codex_cell_policy.verify`
    hashes it, but at cell start, so its absence surfaced as a cell that would not spawn. The
    artefact lives in a CACHE directory under `~/.codex`, referenced nowhere in this
    repository except a proposal document. On the same day this decision was taken, a
    cache-clearing sweep on this box removed gigabytes from neighbouring trees under
    `/var/tmp/claude` and `~/.cache`. It did not touch this one. Nothing would have stopped
    it and nothing would have reported it afterwards.
  - **The drift was undocumented.** Nothing on the estate reported that the fleet pins
    0.144.3 while the operator seat runs 0.146.0. It was rediscovered by hand.

The check is deliberately split: FATAL when `BOLTRIG_CODEX_BINARY` is set and the binary is
missing, wrong-digest or group-writable (that box intends to run cells and cannot); NOT fatal
when the variable is unset, reporting instead whether the pin is SATISFIABLE by hashing every
candidate under the releases root; and NEVER fatal on version drift, because an operator seat
running a newer CLI is expected and a check that cannot pass on an ordinary checkout is one
people learn to skip.

Seeded four ways and each run: absent binary RED, wrong bytes RED, group-writable RED, and
the positive control (correct binary, correct permissions) GREEN, which is what shows the
first three are not simply "always red".
