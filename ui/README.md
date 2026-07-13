# Boltrig UI

A thin React + TypeScript + Vite client over the Boltrig kernel HTTP API. Three
panels (S4):

- **Router** (US-UI-01 / US-UI-03): nouns and their verbs, grouped by noun, with
  consequence, binding target (when present) and live adapter health
  cross-referenced from `/healthz`.
- **Kanban** (US-WRK-03): work items in status lanes (pending, in_flight,
  blocked, awaiting_human, done, failed). Each card links to its
  `hatchet_run_id` and can open the audit execution tree.
- **Approvals** (US-HIL-05): the canonical record of pending human-in-the-loop
  requests (approval / clarification / escalation), answered inline.

A dev identity bar sets the `x-boltrig-tenant` / `x-boltrig-subject` /
`x-boltrig-grants` / `x-boltrig-role` headers sent on every request (the kernel's
dev principal resolver trusts these). The identity persists in `localStorage`.

## Develop

```bash
corepack enable
pnpm install
pnpm run dev        # http://localhost:5173, proxies /v1 and /healthz to the kernel
```

The dev server proxies `/v1` and `/healthz` to `http://localhost:8000`. Point it
elsewhere with `BOLTRIG_KERNEL_URL`:

```bash
BOLTRIG_KERNEL_URL=http://127.0.0.1:9000 pnpm run dev
```

## Build and check

```bash
pnpm run typecheck  # tsc --noEmit (strict)
pnpm run build      # tsc && vite build -> dist/
pnpm run preview    # serve the production build locally
```

## Docker

The image builds the SPA and serves it with nginx, reverse-proxying `/v1` and
`/healthz` to a kernel service named `kernel` on port `8000`.

```bash
docker build -t boltrig-ui .
docker run -p 8080:80 boltrig-ui   # expects a reachable `kernel:8000`
```

In compose, put this service on the same network as the kernel container named
`kernel`. To use a different kernel host/port, edit `nginx.conf`.

## Layout

```
src/
  api/client.ts     typed fetch client (sends dev identity headers)
  api/types.ts      response shapes mirroring boltrig/kernel/app.py
  identity.ts       localStorage-backed identity store + useIdentity hook
  useFetch.ts       loading / error / reload + optional polling hook
  panels/           RouterPanel, KanbanPanel, ApprovalsPanel
  App.tsx           identity bar, tab nav, kernel health indicator
```
