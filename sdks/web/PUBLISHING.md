# Publishing `boltrig-web-sdk`

The shared UI-SDK core (the `ChatEvent` frame union + the `normalizeEvents` turn
reducer) is the single source of truth both frontends fold through, so the
boltrig console and opbox render identical chat/run data. Both consume it as ONE
published package (consolidation-over-fragmentation: not vendored copies, not a
per-consumer Docker-context hack).

## Route decision (VJS-ACT 6 s1) — status: RESERVED

`wlilley93/boltrig` is a **public** repository, so publishing this package to any
registry linked to it is a **public release** (`public_target == true`). Under
the **External Acts and Release Authority Act, [2026] VJS-ACT 6 s2**, a public
release requires a **release warrant or Principal authorisation** plus a human
checkpoint. It is therefore RESERVED — an agent may prepare it fully but must not
execute the publish autonomously.

For contrast (s2 test): had the repo been private, the publish would be an
ordinary external act (s1/s5) within agent authority — explicit credentials are
already present (`gh` token carries `write:packages`) and the act is neither
destructive nor irreversible (s4, package versions are deletable). The single
determinative fact is the public target.

## Everything up to the gate is DONE

- Package is publish-ready: subpath `exports` (`./types`, `./chatTurnTypes`,
  `./chatTurnNormalizer`), `prepare`/`prepublishOnly` build the (gitignored)
  `dist`, `files`/`sideEffects`/`repository`/`license` set.
- No secrets in the package (VJS-ACT 6 s3): source-only, no env/keys.
- Source-of-truth drift guard is green (`tests/drift.test.ts`): the console's
  three copies are provably identical to this package until they consume it.

## The authorised publish (one command, Principal-gated)

Decisive-call registry: **GitHub Packages** under the `@wlilley93` scope (the
`gh` token already carries `write:packages`; no new credential needed). To
authorise:

```bash
cd sdks/web
# 1. scope + registry (the reserved change):
npm pkg set name='@wlilley93/boltrig-web-sdk' private=false \
  publishConfig.registry='https://npm.pkg.github.com'
# 2. auth npm to GitHub Packages with the existing gh token:
npm config set //npm.pkg.github.com/:_authToken "$(gh auth token)"
# 3. publish (runs prepublishOnly build):
npm publish
```

Then log a release receipt (VJS-ACT 6 s6): release id `@wlilley93/boltrig-web-sdk@0.1.0`,
authority basis = Principal authorisation, human checkpoint = the authorising message.

## Post-publish wiring (unblocks once published)

1. **boltrig console** (`ui/`): add `@wlilley93/boltrig-web-sdk` as a dep; re-point
   `src/api/types.ts`, `src/panels/chatTurnTypes.ts`, `src/panels/chatTurnNormalizer.ts`
   to re-export the package subpaths; delete `tests/drift.test.ts` (obsolete once
   the copies are gone); gate `tsc && vite build && vitest`. The published dep is
   in every Docker build context, so this fixes the `context: ./ui` break that
   blocks a sibling-alias approach today.
2. **opbox** (`opbox-frontend/src/lib/ai/boltrig-frames.ts`, `boltrig-chat.ts`):
   add the dep and re-back the boltrig frame handling on the shared union +
   reducer, so opbox renders the boltrig turn identically to the console.
