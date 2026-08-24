# Coverage: what this corpus reaches, and what it does not

Measured mechanically on 2026-08-24 against the referent `19bcae7f`, by taking
every file tracked at that commit and asking whether any citation or link
anywhere in the corpus names it. Method: `git ls-tree -r --name-only 19bcae7f`
against the union of every `path:line` citation and every relative link target in
`docs/brownfield-spec/**`.

This file exists because "twenty areas" sounds like completeness and is not.

## The headline number, and why it is misleading

    tracked files at the referent      4,120
    source files considered            3,944   (excludes lockfiles, binaries, the corpus itself)
    named somewhere in the corpus        919   23.3 percent
    never named                        3,025   76.7 percent

Twenty-three percent is the wrong way to read this, in both directions.

It **understates** coverage: 794 of the uncited files are `.vds/proofs`
generated governance artefacts, and most of `tests/` is uncited by design. The
corpus cites a test when the test proves something a requirement row claims. It
was never trying to cite all 537 test files.

It **overstates** completeness of the areas that matter: a spec can name three
files in a directory of thirty and still read as though it covered the
subsystem. The list below is the honest part.

## Coverage by subsystem

    boltrig/api                    40/42    95%
    boltrig/distill                10/11    91%
    boltrig/memory                 26/29    90%
    boltrig/workflows              15/17    88%
    sdks/node                      12/14    86%
    boltrig/observability          10/12    83%
    boltrig/knowledge              12/15    80%
    boltrig/work                    4/5     80%
    boltrig/identity               15/20    75%
    sdks/web                       21/28    75%
    boltrig/adapters               32/48    67%
    boltrig/kernel                101/157   64%
    services/channel_gateway       14/22    64%
    ios/Boltrig                    40/67    60%
    boltrig/config                 38/65    58%
    boltrig/models                 22/55    40%
    boltrig/fleet                  79/225   35%
    boltrig/store                  36/103   35%
    boltrig/camera                  2/7     29%
    migrations/versions            25/88    28%
    apps/worker                    89/589   15%
    site/src                       13/100   13%
    libraries/skills                1/25     4%
    libraries/prompts               0/7      0%

## Directories with no citation at all

Forty-five product directories holding two or more files are named nowhere in
the corpus. The ones that are code rather than media assets, worst first:

**Unowned by any area.** No spec's scope statement claims these, so no author
was ever asked to read them.

- `tools/pixy-probe` (5 files)
- `site/obsidian/**` (roughly 29 files across frontend, backend, meta,
  templates, workflows and an `.obsidian` config directory)
- `deploy/host-m4` (5 files)

**Owned but unread.** An area's scope names the parent, and the author did not
reach these.

- `boltrig/fleet/domain` (16 files). The most serious gap in the corpus, and it is
  a HANDOFF gap rather than an oversight, which makes it the kind that survives
  review. Area 03's bound statement names the directory and explicitly disclaims
  it: "NOT read, and deliberately out of scope (area 04 owns them) ...
  `boltrig/fleet/domain/*`". Area 04 then scoped itself to the `codex_*` modules
  and never mentions `fleet/domain` at all: the string does not appear in
  SPEC-04 (bounded: `grep -c 'fleet/domain' specs/SPEC-04-fleet-runtime-codex.md`
  returns 0). Each author behaved correctly by its own bound, and the directory
  fell between them. The only trace anywhere is a passing mention of
  `boltrig/fleet/domain/model_proxy_*.py` in SPEC-10.
- `libraries/prompts` (7 files) and `libraries/skills/{playbooks,writing,analysis,growth}`
  (19 files). Area 09 claims `libraries/`. These YAML files ARE the
  everything-as-data story the doctrine rests on, and the corpus describes the
  loader without describing what it loads.
- `services/channel_gateway/clients` (2 files), area 17.
- `familiar/variants` (4 files), `apps/worker/src/bundles/jarvis` (2),
  `apps/worker/src/familiarIsland` (3), area 14.

**Disclosed samples.** These areas stated their own bound at the top of the
spec, so the gap is declared rather than hidden. It is still a gap.

- `apps/worker/src/components/{settings,onboarding,jarvis,integrations,colossus,chat/display,routine,browser,account}`,
  roughly 115 files. Area 15 says in its own words that it sampled 335 modules
  mechanically and read a named subset in full. `evidence/worker-ui-route-inventory.md`
  lists every module with its line count, so the shape is known even where the
  behaviour is not.
- `site/src/components/{brain,story,animation,common}` and `site/src/hooks`,
  roughly 45 files. Area 16 concentrated on the SDK contract and the console
  route and left the marketing site's rendering layer largely unread.

## What this means for a reader

A subsystem at 80 percent or better has been read. A subsystem at 35 percent has
had its spine described and its periphery sampled: trust the control flow, check
the code before trusting a completeness claim about it. The zero-coverage
directories are not described at all, and this corpus says nothing whatsoever
about them, which is different from saying there is nothing there.

Uncited does not mean unimportant and it does not mean dead. `boltrig/fleet/domain`
in particular should be read before anyone relies on areas 03 or 04 as a
complete account of the fleet.
