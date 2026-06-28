# Secure deployment

The same images run everywhere; security is configuration, not a rebuild (P7).
This covers encryption in transit (SEC-10), encryption at rest (SEC-11), and the
corporate proxy + internal CA wiring (US-DEP-04).

## TLS in transit (SEC-10)

Run the secure overlay, which puts a Caddy TLS terminator in front of the UI and
the kernel and stops publishing their ports directly:

```bash
NANKLE_DOMAIN=nankle.example.com \
  docker compose -f docker-compose.yml -f deploy/compose.secure.yml up -d
# or: make secure-up
```

- For a public domain Caddy auto-provisions a certificate; for `localhost` it uses
  its built-in internal CA. To present an internal-CA / corporate certificate,
  replace auto-TLS in `deploy/Caddyfile.example` with `tls /certs/site.crt
  /certs/site.key` and mount those files into the `caddy` service.
- Only Caddy is reachable from outside; the kernel and UI lose their host ports in
  the overlay. Internal service-to-service traffic stays on the compose network.
- Postgres connections use TLS by putting `sslmode=require` in `DATABASE_URL`.
  For host-spanning deployments, terminate mTLS for adapter connections to
  enterprise services per the adapter's credential material.

## Encryption at rest (SEC-11)

Postgres data, library artefacts, and backups must sit on encrypted storage. The
app does not encrypt the disk; the deployment does, with no image change:

- Point the Postgres data dir at an encrypted device or path and set it via env:
  `PGDATA_HOST=/mnt/luks/nankle-pgdata docker compose ... up -d`. Use a LUKS
  volume on-prem, or a cloud encrypted disk (EBS/PD/Azure Disk with CMK).
- Put backups (`./backups`, see `backup-restore.md`) on the same encrypted media.
- The external secret store (Vault/KMS) holds credentials; the app DB stores only
  references (SEC-04), so an at-rest disk never contains plaintext secrets.

## Corporate proxy + internal CA (US-DEP-04)

- Egress proxy: set `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`. They are passed as
  build args and read at runtime; adapters honour them for outbound calls.
- Internal CA: set `CA_BUNDLE` to the in-container path of your CA bundle. The
  secure overlay mounts `${CA_BUNDLE_FILE:-./deploy/ca-bundle.crt}` to
  `/certs/ca.pem` in the kernel and fleet containers; set `CA_BUNDLE=/certs/ca.pem`.
- Air-gapped: set `AIR_GAPPED=1`, disable hosted model endpoints, and run the
  `local-model` profile; no component requires internet to start (SEC-20).

## Checklist

- [ ] `make secure-up` (TLS terminator in front; kernel/UI ports closed)
- [ ] `DATABASE_URL` has `sslmode=require`
- [ ] `PGDATA_HOST` on an encrypted device; backups on encrypted media
- [ ] `CA_BUNDLE` set and the bundle mounted; proxy env set if required
- [ ] real OIDC configured (`OIDC_*`), `NANKLE_DEV_AUTH` unset (SEC-01)
