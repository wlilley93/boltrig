# Dependency update policy

Boltrig uses one package manager per ecosystem and commits every production
lockfile. Dependency changes are reviewed like code: the manifest and lockfile
move together, automated checks must be green, and generated lockfiles are never
hand-edited.

## Package managers and lockfiles

- Python production images install `requirements-lock.txt` with
  `pip --require-hashes`. Regenerate it with the `uv pip compile` command recorded
  at the top of that file.
- Python CI and local quality tooling install `requirements-dev-lock.txt` with
  the same hash enforcement. Application source is imported directly from the
  checkout/image; CI and production images never invoke PEP 517 build isolation.
- The UI and site use the `pnpm@11.5.0` version declared in each `package.json`.
  `pnpm-lock.yaml` is the only accepted JavaScript lockfile; do not commit
  `package-lock.json` or `yarn.lock`.
- CI and container builds install with `--frozen-lockfile`. A stale lockfile is a
  hard failure.
- Optional tool runtimes keep isolated hash-locked inputs under `deploy/`; they
  must not mutate the Boltrig application environment.

## Update cadence

Dependabot checks the application and deploy Python inputs, UI, site, GitHub
Actions, and every Dockerfile directory weekly. Minor and patch application
updates are grouped by ecosystem to keep the review queue bounded. Major updates
remain separate because they require an explicit migration and rollback
assessment.

Herdr and OpenCode are downloaded as native release assets and cannot be parsed
by Dependabot. Review both pins weekly with the dependency PR queue: update the
version plus both architecture hashes together, verify the upstream release,
and rebuild both first-party images. Never update a URL without its hashes.

Security updates do not wait for the weekly window:

- critical advisories: triage immediately and patch or mitigate before release;
- high advisories: patch before merge or document a time-bounded, owner-approved
  exception;
- moderate and low advisories: assess reachability and schedule normally.

## Required verification

For every dependency change:

1. Read upstream release and security notes, including transitive changes.
2. Regenerate only the affected lockfile with the declared package manager.
3. Run the affected unit, build, and browser tests.
4. Run `make security-source`; high and critical advisories, medium/high SAST,
   secrets, and invalid workflow changes fail, including build/test tooling.
5. For Python/container changes, rebuild the affected image and run its smoke
   test before release.
6. Record any accepted advisory with reachability, owner, expiry, and compensating
   control. Expired exceptions fail the release review.

Typical JavaScript refresh commands are:

```sh
cd ui
corepack pnpm install --frozen-lockfile
pnpm update <package>@<version> --save-exact

cd ../site
corepack pnpm install --frozen-lockfile
pnpm update <package>@<version> --save-exact
```

Do not use an unbounded `audit --fix` in a production update: it can silently
cross major versions. Apply and review the smallest explicit upgrade that closes
the advisory.

Browser Use currently needs two reviewed patch-level security overrides because
its metadata pins older transitive releases. They live in
`deploy/browser-cli-overrides.txt`; the image installs the complete hashed lock
with `--no-deps`, and both a CLI/browser smoke and `pip-audit` validate the
result. Regenerate it with the exact command recorded at the top of the lock and
remove an override as soon as upstream adopts the fixed version.
