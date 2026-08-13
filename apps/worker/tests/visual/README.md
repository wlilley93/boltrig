# Worker visual capture harness

`parity.html` mounts the real Worker `App` and `WorkerGlobalContextProvider` with
deterministic HTTP fixtures. `states.json` is the capture contract. Its
`governed_state_ids` list is the only state set promoted by evidence capture;
the additive desktop-chat direction remains outside that seven-frame set and
uses its own source-bound capture lane.

The fixture publishes `window.__boltrigVisualCaptureContract` and adds
`html[data-visual-ready="<state>"]` only after:

- every declared request has occurred and no request missed the fixture;
- the expected route, required/forbidden DOM, text and geometry are satisfied;
- fonts are loaded; and
- that contract remains unchanged for two animation frames at 1440×900 and
  device pixel ratio 1.

The shipped Familiar does not read the machine phenotype, so Familiar states
must not require a phenotype request merely to settle. Jarvis-specific states
may bind that read when the selected character actually consumes it.

The chat fixtures deliberately pin the real `vendor-invoice-triage` summary so
the left rail exercises both `Pinned` and `Recents`. Chat-run and the additive
direction also require the transcript navigator, 31/44px task-row geometry,
compact receipt counts, and the shared semantic inspector classes used by both
the current rail and `TaskInspector`. Legacy Recents search/workspace/status,
conversation-title and governance chrome remain prohibited.

Any edit under `apps/worker/src` or this harness invalidates an existing
source-bound receipt by design. Do not repair that failure by rewriting a
digest: run the all-or-nothing governed and additive capture lanes after the UI
has stopped changing, then perform comparison and VDS review separately.
`make vds-ledgers` independently recomputes that tree digest from the scope
fixed by the capture contract, so a stale receipt cannot satisfy the required
repository gate merely because its route and metrics hashes were refreshed.

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

Capture the additive desktop-chat direction independently:

```sh
node apps/worker/tests/visual/capture-current.mjs \
  --additive-evidence \
  --reuse-server \
  --origin http://127.0.0.1:1420 \
  --timeout-ms 45000
```

This mode atomically replaces only
`docs/design/evidence/2026-08-11-chat-ui-direction/current/`. It writes the
1440×900 PNG, its SHA-256 manifest, and an additive capture receipt bound to the
exact Worker and visual-harness source digest. The canonical historical
`chat-ui-direction/shipped/` image and digest remain unchanged. The receipt is
deliberately `not_assessed`, sets `vdsReviewsUpdated` to false, and cannot act as
a VDS sign-off or conformity verdict.

Validate the current-to-Figma comparison mapping at any time:

```sh
python3 apps/worker/tests/visual/compare-current.py --check-plan
```

After `--evidence` succeeds, generate source-bound measurements without
touching the historical comparison:

```sh
python3 \
  apps/worker/tests/visual/compare-current.py
```

The comparator verifies the capture receipt, every target/current PNG digest,
the 1440×900 dimensions, and the still-current source digest. It atomically
writes only `current/diff/` and `current/metrics.json`; the resulting status is
`measured_unreviewed` and its visual verdict remains `not_assessed`.
