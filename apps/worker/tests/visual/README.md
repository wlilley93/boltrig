# Worker visual capture harness

`parity.html` mounts the real Worker `App` and `WorkerGlobalContextProvider` with
deterministic HTTP fixtures. `states.json` is the capture contract. Its
`governed_state_ids` list is the only state set promoted by evidence capture;
the additive desktop-chat direction remains outside that seven-frame set.

The fixture publishes `window.__boltrigVisualCaptureContract` and adds
`html[data-visual-ready="<state>"]` only after:

- every declared request has occurred and no request missed the fixture;
- the expected route, required/forbidden DOM, text and geometry are satisfied;
- fonts are loaded; and
- that contract remains unchanged for two animation frames at 1440×900 and
  device pixel ratio 1.

Run an isolated smoke capture (the runner starts and stops Vite itself):

```sh
node apps/worker/tests/visual/capture-current.mjs --smoke --timeout-ms 45000
```

When a server is already listening on the manifest port, reuse must be
explicit so a stray process cannot silently become evidence:

```sh
node apps/worker/tests/visual/capture-current.mjs \
  --smoke \
  --reuse-server \
  --origin http://127.0.0.1:1420 \
  --timeout-ms 45000
```

After production and harness source have stopped changing, capture all seven
governed states to the durable, unreviewed current-source directory:

```sh
node apps/worker/tests/visual/capture-current.mjs \
  --evidence \
  --reuse-server \
  --origin http://127.0.0.1:1420 \
  --timeout-ms 45000
```

The evidence command is all-or-nothing. It captures into a sibling staging
directory, verifies every PNG is exactly 1440×900, verifies the source digest
did not change, then atomically promotes
`docs/design/evidence/2026-08-11-console-parity/current/`. That directory holds
the seven PNGs, `shipped.sha256`, and a source-bound `capture-manifest.json`
whose verdict is deliberately `not_assessed`.

This command does not replace the historical `shipped/` files, regenerate
pixel comparisons, or update VDS reviews. Those are separate review actions
after the current capture exists.

Validate the current-to-Figma comparison mapping at any time:

```sh
python3 apps/worker/tests/visual/compare-current.py --check-plan
```

After `--evidence` succeeds, generate source-bound measurements without
touching the historical comparison:

```sh
/Users/williamlilley/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  apps/worker/tests/visual/compare-current.py
```

The comparator verifies the capture receipt, every target/current PNG digest,
the 1440×900 dimensions, and the still-current source digest. It atomically
writes only `current/diff/` and `current/metrics.json`; the resulting status is
`measured_unreviewed` and its visual verdict remains `not_assessed`.
