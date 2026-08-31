# Boltrig scheduled backup sidecar image (M10, SEC-70).
#
# This image bakes in the exact tools the backup script needs (pg_dump, tar,
# rclone, openssl) so the sidecar does not install at runtime (IAC-003). It is used
# by the profile-gated `backup` service in docker-compose.yml.
#
# Pin the base image to a specific PostgreSQL minor + digest. For digest pinning,
# replace the tag with a sha256 reference after pulling the desired image.

# IAC-002: pinned to a stable tag + digest.
FROM postgres:16.15-bookworm@sha256:bb3e1a57e5407e0a5280b4211980a5e537f4abd234a87014ac979849a78dd825 AS base

# IAC-002: rclone is BUILT HERE from its pinned upstream source rather than
# copied from the official rclone image, because the official image is compiled
# against a Go toolchain carrying two fixable HIGH stdlib CVEs.
#
# CVE-2026-39821 (golang.org/x/net/idna, Punycode label processing) and
# CVE-2026-46600 (golang.org/x/net/dns/dnsmessage, DoS on invalid DNS records)
# are both fixed in Go 1.26.6, and both have Trivy status "fixed", so
# ignore-unfixed does not suppress them and the container gate blocks on them.
#
# There is nothing to upgrade TO. Measured 2026-08-14 with the pinned scanner
# (aquasec/trivy:0.72.0): v1.75.0 IS the latest upstream release,
# rclone/rclone:latest resolves to the very digest this file used to pin, and
# even rclone/rclone:beta / :master (built 2026-08-13) are still on go1.26.5
# and still report both CVEs. So a tag bump cannot fix this at any tag.
#
# Same source, patched compiler: the module is fetched by exact version through
# the Go module proxy, which verifies it against the sum.golang.org checksum
# database - a stronger provenance check than the digest pin it replaces, and
# the reason no vendored-source copy is kept in-tree.
#
# When upstream ships an image built on Go >= 1.26.6, prefer reverting to the
# COPY-from-official-image form: it is less build surface than compiling here.
FROM golang:1.26.6-bookworm@sha256:116d58cbd88c1297624acc6e967a060012422bacf9930927e23fb719189c6f36 AS rclone-src

# NOT named RCLONE_VERSION. rclone binds every RCLONE_* environment variable to
# the matching flag, so an ARG by that name is visible to the smoke test below
# as --version, which is a boolean, and the build dies on
# `strconv.ParseBool: parsing "v1.75.0"`.
ARG BACKUP_RCLONE_VERSION=v1.75.0
ENV CGO_ENABLED=0 \
    GOTOOLCHAIN=local \
    GOFLAGS=-trimpath

# -X fs.Version stamps the release string the upstream release process would
# have applied; without it `go install` reports the in-source "v1.75.0-DEV".
RUN go install -ldflags "-s -w -X github.com/rclone/rclone/fs.Version=${BACKUP_RCLONE_VERSION}" \
        "github.com/rclone/rclone@${BACKUP_RCLONE_VERSION}" \
    && /go/bin/rclone version

FROM base
ENV DEBIAN_FRONTEND=noninteractive \
    PGUSER=boltrig \
    PGDATABASE=boltrig

USER root

# The upstream Postgres entrypoint uses gosu, but this image replaces that
# entrypoint with the backup loop. Remove the otherwise-unused static helper so
# its embedded Go toolchain is not part of the production attack surface.
RUN rm -f /usr/local/bin/gosu

# openssl is needed for optional passphrase encryption. pg_dump is already
# present in the postgres image; rclone is copied from the pinned rclone image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        openssl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/*

COPY --from=rclone-src /go/bin/rclone /usr/local/bin/rclone
RUN rclone version

WORKDIR /app
COPY scripts/backup.sh /usr/local/bin/backup.sh
COPY scripts/backup-loop.sh /usr/local/bin/backup-loop.sh
COPY scripts/backup-healthcheck.sh /usr/local/bin/backup-healthcheck
RUN chmod +x \
        /usr/local/bin/backup.sh \
        /usr/local/bin/backup-loop.sh \
        /usr/local/bin/backup-healthcheck

# The sidecar loops the backup script at BACKUP_INTERVAL seconds. The caller
# mounts the backups directory and the rclone config directory as volumes. A
# failed run exits PID 1; Docker's restart policy retries it instead of masking a
# permanently broken backup process. The healthcheck also detects stale success.
HEALTHCHECK --interval=60s --timeout=5s --start-period=5m --retries=3 \
    CMD ["/usr/local/bin/backup-healthcheck"]
CMD ["/usr/local/bin/backup-loop.sh"]
