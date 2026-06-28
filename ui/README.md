# Nankle UI

A thin React + TypeScript + Vite client over the Nankle kernel HTTP API. Three
panels (S4):

- **Router** (US-UI-01 / US-UI-03): nouns and their verbs, grouped by noun, with
  consequence, binding target (when present) and live adapter health
  cross-referenced from `/healthz`.
- **Kanban** (US-WRK-03): work items in status lanes (pending, in_flight,
  blocked, awaiting_human, done, failed). Each card links to its
  `hatchet_run_id` and can open the audit execution tree.
- **Approvals** (US-HIL-05): the canonical record of pending human-in-the-loop
  requests (approval / clarification / escalation), answered inline.

A dev identity bar sets the `x-nankle-tenant` / `x-nankle-subject` /
`x-nankle-grants` / `x-nankle-role` headers sent on every request (the kernel's
dev principal resolver trusts these). The identity persists in `localStorage`.

## Develop

```bash
npm install
npm run dev        # http://localhost:5173, proxies /v1 and /healthz to the kernel
```

The dev server proxies `/v1` and `/healthz` to `http://localhost:8000`. Point it
elsewhere with `NANKLE_KERNEL_URL`:

```bash
NANKLE_KERNEL_URL=http://127.0.0.1:9000 npm run dev
```

## Build and check

```bash
npm run typecheck  # tsc --noEmit (strict)
npm run build      # tsc && vite build -> dist/
npm run preview    # serve the production build locally
```

## Docker

The image builds the SPA and serves it with nginx, reverse-proxying `/v1` and
`/healthz` to a kernel service named `kernel` on port `8000`.

```bash
docker build -t nankle-ui .
docker run -p 8080:80 nankle-ui   # expects a reachable `kernel:8000`
```

In compose, put this service on the same network as the kernel container named
`kernel`. To use a different kernel host/port, edit `nginx.conf`.

## Layout

```
src/
  api/client.ts     typed fetch client (sends dev identity headers)
  api/types.ts      response shapes mirroring nankle/kernel/app.py
  identity.ts       localStorage-backed identity store + useIdentity hook
  useFetch.ts       loading / error / reload + optional polling hook
  panels/           RouterPanel, KanbanPanel, ApprovalsPanel
  App.tsx           identity bar, tab nav, kernel health indicator
```
